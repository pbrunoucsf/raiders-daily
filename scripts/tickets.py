#!/usr/bin/env python3
"""Daily ticket-price email for the Raiders games listed in GAMES.

For each game still ahead, reads Gametime's public listings feed (all-in
prices, fees included) and picks the cheapest seats overall plus the cheapest
seats in each named area (e.g. top deck near the 50) for buying TICKET_QTY
seats together, then emails one combined summary.

Stdlib only. Config comes from environment variables (GitHub secrets):
  GMAIL_ADDRESS       sending Gmail account
  GMAIL_APP_PASSWORD  16-char Google app password for that account
  EMAIL_TO            comma-separated recipients

Run with --dry-run to skip email and write the message to tickets/preview.html.
Run with --once-per-day (scheduled runs) to exit quietly if today's email
already went out, so backup schedule slots never send duplicates.
"""

import json
import os
import smtplib
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime
from email.message import EmailMessage
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
HISTORY = ROOT / "tickets" / "history.json"
PREVIEW = ROOT / "tickets" / "preview.html"

PACIFIC = ZoneInfo("America/Los_Angeles")
TICKET_QTY = 2
TOP_N = 3


def search_links(q):
    q = urllib.parse.quote(q)
    return [
        ("TickPick (no fees)", f"https://www.tickpick.com/search?q={q}"),
        ("Ticketmaster / NFL Ticket Exchange", f"https://www.ticketmaster.com/search?q={q}"),
        ("StubHub", f"https://www.stubhub.com/secure/search?q={q}"),
        ("SeatGeek", f"https://seatgeek.com/search?search={q}"),
        ("Vivid Seats", f"https://www.vividseats.com/search?searchTerm={q}"),
    ]


# Areas: (history key, heading, set of section names). Section names match
# Gametime's listing "section" field.
GAMES = [
    {
        "key": "lv",
        "title": "Rams @ Raiders",
        "day": date(2026, 10, 25),
        "when_where": "Sun Oct 25, 2026 · 1:25 PM PT · Allegiant Stadium, Las Vegas",
        "search": "rams raiders",
        "match": ("Rams", "Raiders"),
        "event_id": "695d72d1f3e001f3f409f235",
        "event_url": ("https://gametime.co/nfl-football/rams-at-raiders-tickets/"
                      "10-25-2026-las-vegas-nv-allegiant-stadium/events/695d72d1f3e001f3f409f235"),
        # Allegiant: the 400s are the top deck on both sidelines; the 50 falls at
        # 412 and 438. Five sections each side ~ between the 30s.
        "areas": [
            ("top_deck_50", "Top deck near the 50 (sections 410-414 and 436-440)",
             {"410", "411", "412", "413", "414", "436", "437", "438", "439", "440"}),
        ],
        "links": search_links("rams raiders"),
    },
    {
        "key": "sf",
        "title": "Raiders @ 49ers",
        "day": date(2026, 11, 8),
        "when_where": "Sun Nov 8, 2026 · 1:05 PM PT · Levi's Stadium, Santa Clara",
        "search": "raiders 49ers",
        "match": ("Raiders", "49ers"),
        "event_id": "698f3d2f6316f44ee4d68894",
        "event_url": ("https://gametime.co/nfl-football/raiders-at-49-ers-tickets/"
                      "11-8-2026-santa-clara-ca-levis-stadium/events/698f3d2f6316f44ee4d68894"),
        # Levi's: the 300 and 400 levels share the east sideline (opposite the
        # suite tower). Sideline sections run 406-417 and 309-320; the 50 falls
        # between 411/412 and 314/315. Four sections each ~ between the 30s.
        "areas": [
            ("top_deck_50", "Top deck near the 50 (sections 410-413)", {"410", "411", "412", "413"}),
            ("level300_50", "300 level near the 50 (313-316, just below the top deck)",
             {"313", "314", "315", "316"}),
        ],
        "links": [("TickPick (no fees)", "https://www.tickpick.com/buy-san-francisco-49ers-vs-las-vegas-raiders-tickets-levis-stadium-11-8-26-1pm/7730388/")]
                 + search_links("raiders 49ers")[1:],
    },
]

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/129.0 Safari/537.36"
)

def fetch_json(url, attempts=4):
    """GET JSON, backing off on rate limits / transient errors."""
    delay = 30
    for i in range(attempts):
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=40) as resp:
                return json.loads(resp.read())
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as err:
            print(f"fetch failed ({i + 1}/{attempts}): {url} -> {err}", file=sys.stderr)
            if i + 1 == attempts:
                raise
            time.sleep(delay)
            delay *= 2


def find_event(game):
    """Locate the game in Gametime search; fall back to the known event id."""
    url = "https://mobile.gametime.co/v1/search?q=" + urllib.parse.quote(game["search"])
    try:
        for item in fetch_json(url, attempts=2).get("events", []):
            ev = item.get("event", {})
            name = ev.get("name", "")
            if (ev.get("datetime_local", "").startswith(game["day"].isoformat())
                    and all(t in name for t in game["match"]) and "Parking" not in name):
                return ev["id"], ev.get("seo_url") or game["event_url"]
    except Exception as err:  # search is a nicety; listings are what matter
        print(f"search failed, using fallback event id: {err}", file=sys.stderr)
    return game["event_id"], game["event_url"]


def get_listings(event_id):
    data = fetch_json(f"https://mobile.gametime.co/v2/listings/{event_id}")
    out = []
    for lst in data.get("listings", {}).values():
        total = (lst.get("price") or {}).get("total")
        if not total:
            continue
        out.append({
            "section": str(lst.get("section", "")),
            "row": str(lst.get("row", "")),
            "group": lst.get("section_group", ""),
            "price": total / 100,  # cents -> dollars, per ticket, fees included
            "lots": lst.get("lots") or [],  # quantities this listing can be bought in
            "view_url": lst.get("view_url"),
        })
    out.sort(key=lambda x: x["price"])
    return out


def summarize(game, listings):
    """Cheapest TICKET_QTY-together listings per area, plus the cheapest listing
    of any quantity in that area (shown when no pair is available)."""
    seated = [x for x in listings if x["group"] != "Standing Room Only"]
    areas = {"overall": seated}
    for key, _, sections in game["areas"]:
        areas[key] = [x for x in seated if x["section"] in sections]
    summary = {"count": len(seated), "any_qty": {}}
    for key, rows in areas.items():
        summary[key] = [x for x in rows if TICKET_QTY in x["lots"]][:TOP_N]
        summary["any_qty"][key] = rows[0] if rows else None
    return summary


def load_history():
    """One entry per day: {"date", "emailed", <game key>: {area key: best price}}."""
    try:
        history = json.loads(HISTORY.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return []
    for h in history:  # entries from before multi-game support were Levi's only
        if "overall" in h:
            h["sf"] = {k: h.pop(k) for k in ("overall", "top_deck_50", "level300_50", "listings") if k in h}
    return history


def today_entry(history, today):
    entry = next((h for h in history if h["date"] == today.isoformat()), None)
    if entry is None:
        entry = {"date": today.isoformat()}
        history.append(entry)
    return entry


def record(history, today, game, summary):
    prices = {key: (rows[0]["price"] if rows else None)
              for key, rows in summary.items() if key not in ("count", "any_qty")}
    today_entry(history, today)[game["key"]] = {**prices, "listings": summary["count"]}


def write_history(history):
    HISTORY.parent.mkdir(exist_ok=True)
    HISTORY.write_text(json.dumps(history, indent=1) + "\n")


def money(v):
    return f"${v:,.0f}"


def change_note(history, game_key, key, today):
    series = [(h["date"], h.get(game_key, {}).get(key)) for h in history]
    series = [(d, v) for d, v in series if v]
    prev = [v for d, v in series if d < today.isoformat()]
    now = next((v for d, v in series if d == today.isoformat()), None)
    if not prev or now is None:
        return ""
    diff = now - prev[-1]
    low = min(v for _, v in series)
    note = "no change since yesterday" if abs(diff) < 1 else (
        f"{'down' if diff < 0 else 'up'} {money(abs(diff))} since last check")
    if now <= low:
        note += " · lowest seen so far"
    return note


def render_game(game, summary, history, today, error, text, html):
    days = (game["day"] - today).days
    countdown = "today!" if days == 0 else f"{days} day{'s' if days != 1 else ''} to go"
    text += ["", "=" * 50, f"{game['title'].upper()}: {countdown}", game["when_where"]]
    html += [
        "<div style='border-top:3px solid #111;margin-top:24px;padding-top:12px'>",
        f"<h2 style='margin:0 0 4px'>{game['title']} <span style='font-weight:normal;color:#555;font-size:16px'>"
        f"· {countdown}</span></h2>",
        f"<p style='margin:0 0 8px;color:#555'>{game['when_where']}</p>",
    ]

    if error:
        text.append(f"Couldn't pull prices today ({error}). Will try again tomorrow.")
        html.append(f"<p><b>Couldn't pull prices today</b> ({error}). Will try again tomorrow. "
                    "Links below still work for checking by hand.</p>")
    else:
        for key, heading in [("overall", "Cheapest seats overall")] + [(k, h) for k, h, _ in game["areas"]]:
            rows = summary[key]
            note = change_note(history, game["key"], key, today)
            text += ["", heading.upper() + (f"  ({note})" if note else "")]
            html.append(f"<h3 style='margin:16px 0 6px'>{heading}</h3>")
            if note:
                html.append(f"<div style='color:#666;font-size:13px;margin-bottom:6px'>{note}</div>")
            if not rows:
                alt = summary["any_qty"].get(key)
                msg = "No pairs listed right now."
                if alt:
                    qty = "/".join(str(q) for q in alt["lots"][:4]) or "?"
                    msg += (f" Cheapest listing here: {money(alt['price'])}/ticket, Section {alt['section']}, "
                            f"Row {alt['row']} (sold in quantities of {qty}).")
                text.append("  " + msg)
                html.append(f"<p style='color:#444'>{msg}</p>")
                continue
            html.append("<table style='border-collapse:collapse;width:100%'>")
            for i, r in enumerate(rows):
                text.append(f"  {money(r['price'])}  Section {r['section']}, Row {r['row']}")
                weight = "bold" if i == 0 else "normal"
                view = (f" · <a href='{r['view_url']}'>view from seat</a>" if r.get("view_url") else "")
                html.append(
                    "<tr><td style='padding:4px 12px 4px 0;font-weight:%s;font-size:%s'>%s</td>"
                    "<td style='padding:4px 0'>Section %s, Row %s%s</td></tr>"
                    % (weight, "18px" if i == 0 else "15px", money(r["price"]), r["section"], r["row"], view))
            html.append("</table>")

    links = [("Gametime (source of these prices)", game["url"])] + game["links"]
    text += ["", "Buy / compare:"] + [f"  {n}: {u}" for n, u in links]
    html.append("<p style='margin:16px 0 4px'><b>Buy / compare:</b> "
                + " · ".join(f"<a href='{u}'>{n}</a>" for n, u in links) + "</p></div>")


def render(results, history, today):
    title = "Raiders ticket watch"
    text = [title, f"Prices are per ticket for {TICKET_QTY} seats together, all fees included (Gametime)."]
    html = [
        "<div style='font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;max-width:560px;color:#111'>",
        f"<p style='color:#555;margin:0'>Per-ticket price for <b>{TICKET_QTY} seats together</b>, "
        "all fees included (Gametime).</p>",
    ]
    for game, summary, error in results:
        render_game(game, summary, history, today, error, text, html)
    html.append("<p style='color:#888;font-size:12px;margin-top:24px'>Sent automatically every morning until "
                "game day. Other sites may show different prices; TickPick lists without fees.</p></div>")

    bits = []
    for game, summary, error in results:
        if summary["overall"] and not error:
            top = summary.get("top_deck_50")
            bits.append(f"{game['title']} from {money(summary['overall'][0]['price'])}"
                        + (f", top deck 50 {money(top[0]['price'])}" if top else ""))
    subject = title + (": " + " | ".join(bits) if bits else "")
    return subject, "\n".join(text), "\n".join(html)


def gmail_credentials():
    return (os.environ["GMAIL_ADDRESS"].strip(),
            os.environ["GMAIL_APP_PASSWORD"].replace(" ", "").strip())


def check_login():
    """Verify the Gmail credentials without sending anything."""
    sender, password = gmail_credentials()
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=60) as smtp:
        smtp.login(sender, password)
    print("Gmail login OK.")


def send(subject, text, html):
    sender, password = gmail_credentials()
    to = [a.strip() for a in os.environ["EMAIL_TO"].split(",") if a.strip()]
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = f"Raiders Ticket Watch <{sender}>"
    msg["To"] = ", ".join(to)
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=60) as smtp:
        smtp.login(sender, password)
        smtp.send_message(msg)
    print(f"Emailed {len(to)} recipient(s).")


def main():
    dry_run = "--dry-run" in sys.argv
    today = datetime.now(PACIFIC).date()
    games = [g for g in GAMES if g["day"] >= today]
    if not games:
        print("All games are over; nothing to send.")
        return
    history = load_history()
    if "--once-per-day" in sys.argv and today_entry(history, today).get("emailed"):
        print("Today's email already went out; nothing to do.")
        return

    results = []
    for game in games:
        event_id, game["url"] = find_event(game)
        summary, error = {"overall": [], "count": 0, "any_qty": {}}, None
        try:
            summary = summarize(game, get_listings(event_id))
            record(history, today, game, summary)
        except Exception as err:
            error = type(err).__name__
            print(f"{game['title']} listings failed: {err}", file=sys.stderr)
        results.append((game, summary, error))
    write_history(history)

    subject, text, html = render(results, history, today)
    print(subject + "\n")
    print(text)
    if dry_run:
        PREVIEW.parent.mkdir(exist_ok=True)
        PREVIEW.write_text(html)
        print(f"\n[dry run] wrote {PREVIEW}")
        if os.environ.get("GMAIL_APP_PASSWORD"):
            check_login()
    else:
        send(subject, text, html)
        today_entry(history, today)["emailed"] = True
        write_history(history)


if __name__ == "__main__":
    main()
