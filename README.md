# Raiders Daily

A one-click Las Vegas Raiders content hub: news, podcasts, videos, fan chatter,
and scores/schedule — aggregated automatically several times a day and served
as a static site on GitHub Pages. Built for a dedicated Raiders fan to open on
an iPhone home-screen icon or a Windows browser bookmark.

## How it works

- `scripts/build.py` (Python 3 stdlib only, zero dependencies) fetches RSS
  feeds, YouTube channel feeds, the r/raiders feed, and ESPN's public team API,
  and writes `docs/data.json`.
- `.github/workflows/refresh.yml` runs the script ~4x/day and commits
  `data.json` when content changed.
- `docs/` is a static, framework-free web app served by GitHub Pages. It reads
  `data.json` and renders tabs: Today · News · Podcasts · Videos · Fans · Team.

## Editing sources

All feeds live in [`scripts/sources.py`](scripts/sources.py). Add or remove
entries there — the build skips dead feeds gracefully, so a broken URL never
takes the site down.

## Local development

```bash
python3 scripts/build.py          # regenerate docs/data.json
python3 -m http.server -d docs    # then open http://localhost:8000
```

No installs required (macOS/Linux/Windows with Python 3.9+).

## Ticket price email (Raiders games)

`scripts/tickets.py` runs every morning via `.github/workflows/tickets.yml`
and sends one email covering each game in its `GAMES` list that's still
ahead: currently Rams @ Raiders (Oct 25, Allegiant) and Raiders @ 49ers
(Nov 8, Levi's). For each game it shows the cheapest seats overall and the
cheapest top-deck seats near the 50, priced for 2 seats together with all
fees included (from Gametime's public listings feed). Daily lows are kept in
`tickets/history.json`. The workflow turns itself off after the last game.

Secrets (Settings → Secrets → Actions): `GMAIL_ADDRESS`, `GMAIL_APP_PASSWORD`
(a Google app password), `EMAIL_TO` (comma-separated recipients).

```bash
python3 scripts/tickets.py --dry-run   # print + write tickets/preview.html, no email
```
