#!/usr/bin/env python3
"""Raiders Daily builder — fetches every source in sources.py and writes docs/data.json.

Stdlib only (no pip installs). Every source is wrapped so one dead feed
never breaks the build; it just drops out of that run's data.
"""

import html
import json
import re
import sys
import urllib.request
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).parent))
import sources

DOCS = Path(__file__).resolve().parent.parent / "docs"

ATOM = "{http://www.w3.org/2005/Atom}"
MEDIA = "{http://search.yahoo.com/mrss/}"
ITUNES = "{http://www.itunes.com/dtds/podcast-1.0.dtd}"
YT = "{http://www.youtube.com/xml/schemas/2015}"


def fetch(url, timeout=25):
    req = urllib.request.Request(url, headers={"User-Agent": sources.USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def parse_date(text):
    if not text:
        return None
    text = text.strip()
    try:
        return parsedate_to_datetime(text).astimezone(timezone.utc)
    except (ValueError, TypeError):
        pass
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def strip_html(text, limit=220):
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", html.unescape(text))
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > limit:
        text = text[:limit].rsplit(" ", 1)[0] + "…"
    return text


def iso(dt):
    return dt.isoformat() if dt else None


def parse_feed(raw):
    """Parse RSS 2.0 or Atom into a list of normalized item dicts."""
    root = ET.fromstring(raw)
    items = []
    if root.tag == "rss":
        for it in root.iter("item"):
            enc = it.find("enclosure")
            items.append({
                "title": html.unescape((it.findtext("title") or "").strip()),
                "link": (it.findtext("link") or "").strip(),
                "published": parse_date(it.findtext("pubDate")),
                "summary": it.findtext("description") or "",
                "audio_url": enc.get("url") if enc is not None else None,
                "duration": (it.findtext(f"{ITUNES}duration") or "").strip() or None,
            })
    else:  # Atom
        for e in root.iter(f"{ATOM}entry"):
            link = ""
            for l in e.findall(f"{ATOM}link"):
                if l.get("rel") in (None, "alternate"):
                    link = l.get("href", "")
                    break
            thumb = e.find(f".//{MEDIA}thumbnail")
            author = e.find(f"{ATOM}author/{ATOM}name")
            items.append({
                "title": html.unescape((e.findtext(f"{ATOM}title") or "").strip()),
                "link": link,
                "published": parse_date(e.findtext(f"{ATOM}published") or e.findtext(f"{ATOM}updated")),
                "summary": e.findtext(f"{ATOM}summary") or "",
                "thumbnail": thumb.get("url") if thumb is not None else None,
                "video_id": (e.findtext(f"{YT}videoId") or "").strip() or None,
                "author": author.text.strip() if author is not None and author.text else None,
            })
    return items


def norm_title(title):
    return re.sub(r"[^a-z0-9]+", "", title.lower())[:70]


def build_news():
    out, seen = [], set()
    for label, url in sources.NEWS_FEEDS:
        try:
            items = parse_feed(fetch(url))
        except Exception as e:
            print(f"  ! news feed {label} failed: {e}", file=sys.stderr)
            continue
        is_gnews = label == "Google News"
        for it in items:
            title, source = it["title"], label
            if is_gnews and " - " in title:
                title, source = title.rsplit(" - ", 1)
            if not title or not it["link"]:
                continue
            key = norm_title(title)
            if key in seen:
                continue
            seen.add(key)
            out.append({
                "title": title,
                "url": it["link"],
                "source": source,
                "published": iso(it["published"]),
                # Google News descriptions are just link lists — not useful text
                "summary": "" if is_gnews else strip_html(it["summary"]),
            })
    out.sort(key=lambda x: x["published"] or "", reverse=True)
    return out[: sources.CAPS["news"]]


def build_podcasts():
    out = []
    for show, url in sources.PODCAST_FEEDS:
        try:
            items = parse_feed(fetch(url))
        except Exception as e:
            print(f"  ! podcast feed {show} failed: {e}", file=sys.stderr)
            continue
        for it in items[:6]:  # recent episodes per show; merged list is capped below
            if not it["title"] or not it.get("audio_url"):
                continue
            out.append({
                "show": show,
                "title": it["title"],
                "audio_url": it["audio_url"],
                "url": it["link"],
                "published": iso(it["published"]),
                "duration": it.get("duration"),
                "summary": strip_html(it["summary"], 180),
            })
    out.sort(key=lambda x: x["published"] or "", reverse=True)
    return out[: sources.CAPS["podcasts"]]


def build_videos():
    out = []
    for label, channel_id in sources.YOUTUBE_CHANNELS:
        url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
        try:
            items = parse_feed(fetch(url))
        except Exception as e:
            print(f"  ! youtube channel {label} failed: {e}", file=sys.stderr)
            continue
        for it in items:
            if not it.get("video_id"):
                continue
            out.append({
                "title": it["title"],
                "url": it["link"] or f"https://www.youtube.com/watch?v={it['video_id']}",
                "channel": label,
                "published": iso(it["published"]),
                "thumbnail": it.get("thumbnail") or f"https://i.ytimg.com/vi/{it['video_id']}/mqdefault.jpg",
            })
    out.sort(key=lambda x: x["published"] or "", reverse=True)
    return out[: sources.CAPS["videos"]]


def build_reddit():
    try:
        items = parse_feed(fetch(sources.REDDIT_FEED))
    except Exception as e:
        print(f"  ! reddit feed failed: {e}", file=sys.stderr)
        return []
    out = []
    for it in items:
        if not it["title"] or not it["link"]:
            continue
        author = it.get("author") or ""
        if author.lstrip("/u") == "AutoModerator":
            continue
        out.append({
            "title": it["title"],
            "url": it["link"],
            "author": author,
            "published": iso(it["published"]),
        })
    return out[: sources.CAPS["reddit"]]


def game_from_event(ev):
    comp = (ev.get("competitions") or [{}])[0]
    status = comp.get("status", {}).get("type", {})
    game = {
        "date": ev.get("date"),
        "name": ev.get("name"),
        "short_name": ev.get("shortName"),
        "state": status.get("state"),  # pre | in | post
        "detail": status.get("shortDetail") or status.get("description"),
    }
    scores = []
    for c in comp.get("competitors", []):
        team = c.get("team", {})
        score = c.get("score")
        if isinstance(score, dict):
            score = score.get("displayValue")
        scores.append({
            "team": team.get("abbreviation") or team.get("displayName"),
            "home": c.get("homeAway") == "home",
            "score": score,
            "winner": c.get("winner"),
        })
    if scores:
        game["competitors"] = scores
    return game


def build_team():
    team = {}
    try:
        data = json.loads(fetch(sources.ESPN_TEAM_URL))["team"]
        record_items = data.get("record", {}).get("items", [])
        team["record"] = record_items[0].get("summary") if record_items else None
        team["standing"] = data.get("standingSummary")
        logos = data.get("logos", [])
        team["logo"] = logos[0].get("href") if logos else None
    except Exception as e:
        print(f"  ! espn team failed: {e}", file=sys.stderr)
    try:
        sched = json.loads(fetch(sources.ESPN_SCHEDULE_URL))
        games = [game_from_event(ev) for ev in sched.get("events", [])]
        # "season" is the *current* phase (e.g. 2025 Off Season); requestedSeason is the schedule shown
        team["season"] = (sched.get("requestedSeason") or sched.get("season") or {}).get("displayName")
        team["schedule"] = games
        team["next_game"] = next((g for g in games if g["state"] in ("pre", "in")), None)
        team["last_game"] = next((g for g in reversed(games) if g["state"] == "post"), None)
    except Exception as e:
        print(f"  ! espn schedule failed: {e}", file=sys.stderr)
    return team


def main():
    data = {
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "news": build_news(),
        "podcasts": build_podcasts(),
        "videos": build_videos(),
        "reddit": build_reddit(),
        "team": build_team(),
    }
    DOCS.mkdir(parents=True, exist_ok=True)
    out_path = DOCS / "data.json"
    out_path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    counts = {k: len(v) for k, v in data.items() if isinstance(v, list)}
    print(f"wrote {out_path} — {counts}, team keys: {list(data['team'])}")
    # A run that produced nothing at all is a failure worth flagging in CI
    if not any(counts.values()):
        sys.exit(1)


if __name__ == "__main__":
    main()
