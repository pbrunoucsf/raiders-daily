#!/usr/bin/env python3
"""Daily ticket-price email for Raiders at 49ers, Levi's Stadium, Sun Nov 8 2026.

Reads Gametime's public listings feed (all-in prices, fees included), picks
  * the cheapest seats overall, and
  * the cheapest top-deck (400 level) seats near the 50-yard line,
  * plus the 300-level tier just below it, near the 50,
for buying TICKET_QTY seats together, then emails the summary.

Stdlib only. Config comes from environment variables (GitHub secrets):
  GMAIL_ADDRESS       sending Gmail account
  GMAIL_APP_PASSWORD  16-char Google app password for that account
  EMAIL_TO            comma-separated recipients

Run with --dry-run to skip email and write the message to tickets/preview.html.
"""

import json
import os
import smtplib
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
HISTORY = ROOT / "tickets" / "history.json"
PREVIEW = ROOT / "tickets" / "preview.html"

PACIFIC = ZoneInfo("America/Los_Angeles")
GAME_DAY = date(2026, 11, 8)
FALLBACK_EVENT_ID = "698f3d2f6316f44ee4d68894"
FALLBACK_EVENT_URL = ("https://gametime.co/nfl-football/raiders-at-49-ers-tickets/"
                      "11-8-2026-santa-clara-ca-levis-stadium/events/698f3d2f6316f44ee4d68894")
SEARCH_QUERY = "raiders 49ers"
TICKET_QTY = 2

# Levi's Stadium: the 300 and 400 levels share the east sideline (opposite the
# suite tower). Sideline sections run 406-417 and 309-320; the 50-yard line falls
# between 411/412 and 314/315. Four sections each side ~ between the 30s.
TOP_DECK_MIDFIELD = {"410", "411", "412", "413"}
LEVEL_300_MIDFIELD = {"313", "314", "315", "316"}
TOP_N = 3

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/129.0 Safari/537.36"
)

COMPARE_LINKS = [
    ("TickPick (no fees)", "https://www.tickpick.com/buy-san-francisco-49ers-vs-las-vegas-raiders-tickets-levis-stadium-11-8-26-1pm/7730388/"),
    ("Ticketmaster / NFL Ticket Exchange", "https://www.ticketmaster.com/search?q=raiders%2049ers"),
    ("StubHub", "https://www.stubhub.com/secure/search?q=raiders%2049ers"),
    ("SeatGeek", "https://seatgeek.com/search?search=raiders%2049ers"),
    ("Vivid Seats", "https://www.vividseats.com/search?searchTerm=raiders%2049ers"),
]


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


def find_event():
    """Locate the game in Gametime search; fall back to the known event id."""
    url = "https://mobile.gametime.co/v1/search?q=" + urllib.parse.quote(SEARCH_QUERY)
    try:
        for item in fetch_json(url, attempts=2).get("events", []):
            ev = item.get("event", {})
            if ev.get("datetime_local", "").startswith(GAME_DAY.isoformat()) and "49ers" in ev.get("name", ""):
                return ev
    except Exception as err:  # search is a nicety; listings are what matter
        print(f"search failed, using fallback event id: {err}", file=sys.stderr)
    return {"id": FALLBACK_EVENT_ID, "seo_url": None}


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


def summarize(listings):
    """Cheapest TICKET_QTY-together listings per area, plus the cheapest listing
    of any quantity in that area (shown when no pair is available)."""
    seated = [x for x in listings if x["group"] != "Standing Room Only"]
    areas = {
        "overall": seated,
        "top_deck_50": [x for x in seated if x["section"] in TOP_DECK_MIDFIELD],
        "level300_50": [x for x in seated if x["section"] in LEVEL_300_MIDFIELD],
    }
    summary = {"count": len(seated), "any_qty": {}}
    for key, rows in areas.items():
        summary[key] = [x for x in rows if TICKET_QTY in x["lots"]][:TOP_N]
        summary["any_qty"][key] = rows[0] if rows else None
    return summary


def load_history():
    try:
        return json.loads(HISTORY.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def save_history(history, today, summary):
    def best(key):
        return summary[key][0]["price"] if summary[key] else None

    history = [h for h in history if h["date"] != today.isoformat()]
    history.append({
        "date": today.isoformat(),
        "overall": best("overall"),
        "top_deck_50": best("top_deck_50"),
        "level300_50": best("level300_50"),
        "listings": summary["count"],
    })
    HISTORY.parent.mkdir(exist_ok=True)
    HISTORY.write_text(json.dumps(history, indent=1) + "\n")
    return history


def money(v):
    return f"${v:,.0f}"


def change_note(history, key, today):
    prev = [h for h in history if h["date"] < today.isoformat() and h.get(key)]
    now = next((h.get(key) for h in history if h["date"] == today.isoformat()), None)
    if not prev or now is None:
        return ""
    diff = now - prev[-1][key]
    low = min(h[key] for h in history if h.get(key))
    note = "no change since yesterday" if abs(diff) < 1 else (
        f"{'down' if diff < 0 else 'up'} {money(abs(diff))} since last check")
    if now <= low:
        note += " · lowest seen so far"
    return note


def render(event_url, summary, history, today, error=None):
    days = (GAME_DAY - today).days
    title = f"Raiders @ 49ers tickets: {days} day{'s' if days != 1 else ''} to go"

    sections = [
        ("Cheapest seats overall", "overall"),
        ("Top deck near the 50 (sections 410-413)", "top_deck_50"),
        ("300 level near the 50 (313-316, just below the top deck)", "level300_50"),
    ]

    text = [title, "Sun Nov 8, 2026, 1:05 PM PT · Levi's Stadium, Santa Clara", ""]
    html = [
        "<div style='font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;max-width:560px;color:#111'>",
        f"<h2 style='margin:0 0 4px'>{title}</h2>",
        "<p style='margin:0 0 16px;color:#555'>Sun Nov 8, 2026 · 1:05 PM PT · Levi's Stadium, Santa Clara</p>",
    ]

    if error:
        text += [f"Couldn't pull prices today ({error}). Will try again tomorrow.", ""]
        html.append(f"<p><b>Couldn't pull prices today</b> ({error}). Will try again tomorrow. "
                    "Links below still work for checking by hand.</p>")
    else:
        text.append(f"Prices are per ticket for {TICKET_QTY} seats together, all fees included (Gametime).")
        html.append(f"<p style='color:#555'>Per-ticket price for <b>{TICKET_QTY} seats together</b>, "
                    "all fees included (Gametime).</p>")
        for heading, key in sections:
            rows = summary[key]
            note = change_note(history, key, today)
            text += ["", heading.upper() + (f"  ({note})" if note else "")]
            html.append(f"<h3 style='margin:20px 0 6px'>{heading}</h3>")
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

    links = [("Gametime (source of these prices)", event_url)] + COMPARE_LINKS
    text += ["", "Buy / compare:"] + [f"  {n}: {u}" for n, u in links]
    html.append("<h3 style='margin:24px 0 6px'>Buy / compare</h3><ul style='padding-left:18px'>")
    html += [f"<li><a href='{u}'>{n}</a></li>" for n, u in links]
    html.append("</ul><p style='color:#888;font-size:12px'>Sent automatically every morning until game day. "
                "Other sites may show different prices; TickPick lists without fees.</p></div>")
    return title, "\n".join(text), "\n".join(html)


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
    if today > GAME_DAY:
        print("Game is over; nothing to send.")
        return

    event = find_event()
    event_url = event.get("seo_url") or FALLBACK_EVENT_URL
    history = load_history()
    error = None
    summary = {"overall": [], "top_deck_50": [], "level300_50": [], "count": 0, "any_qty": {}}
    try:
        summary = summarize(get_listings(event["id"]))
        history = save_history(history, today, summary)
    except Exception as err:
        error = type(err).__name__
        print(f"listings failed: {err}", file=sys.stderr)

    subject, text, html = render(event_url, summary, history, today, error)
    if summary["overall"] and not error:
        cheapest = summary["overall"][0]["price"]
        top = summary["top_deck_50"][0]["price"] if summary["top_deck_50"] else None
        subject += f" · from {money(cheapest)}" + (f", top deck 50 {money(top)}" if top else "")
    print(text)
    if dry_run:
        PREVIEW.parent.mkdir(exist_ok=True)
        PREVIEW.write_text(html)
        print(f"\n[dry run] wrote {PREVIEW}")
        if os.environ.get("GMAIL_APP_PASSWORD"):
            check_login()
    else:
        send(subject, text, html)


if __name__ == "__main__":
    main()
