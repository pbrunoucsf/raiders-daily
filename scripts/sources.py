"""Feed and API sources for Raiders Daily.

All URLs verified working 2026-07-13. If a source dies, the build skips it
gracefully — edit or remove entries here and the site adapts automatically.
"""

NEWS_FEEDS = [
    # (source label, url)
    ("Raiders.com", "https://www.raiders.com/rss/news"),
    ("Review-Journal", "https://www.reviewjournal.com/sports/raiders/feed/"),
    ("Silver & Black Pride", "https://www.silverandblackpride.com/rss/index.xml"),
    # Google News catch-all: surfaces ESPN, Yahoo, Raiders Wire, The Athletic, etc.
    # Item titles carry a " - Publisher" suffix which build.py splits into the source label.
    ("Google News", "https://news.google.com/rss/search?q=%22Las+Vegas+Raiders%22&hl=en-US&gl=US&ceid=US:en"),
]

PODCAST_FEEDS = [
    # (show label, rss url)
    ("Locked On Raiders", "https://rss.pdrl.fm/427f18/feeds.simplecast.com/FW_wEF1P"),
    ("Raiders Insider (Bleav)", "https://feeds.simplecast.com/gBQiZMcH"),
    ("Raiders Podcast Network", "https://www.omnycontent.com/d/playlist/ca9aaa7d-6648-494d-bf2f-aef6014ed546/799de2ec-3db5-42c1-a0f5-af000100c564/5e29a931-1924-47ac-9f9c-af000100c585/podcast.rss"),
]

YOUTUBE_CHANNELS = [
    # (channel label, channel_id)
    ("Las Vegas Raiders", "UC1es5fp8FEK1L0EgHjCvmtQ"),
    ("Locked On Raiders", "UCVgPs0As0pzp6zsYJLB7zNA"),
]

REDDIT_FEED = "https://www.reddit.com/r/raiders/.rss"

# ESPN public API — Raiders team id is 13
ESPN_TEAM_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/teams/13"
ESPN_SCHEDULE_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/teams/13/schedule"

# Item caps per section of data.json
CAPS = {"news": 30, "podcasts": 15, "videos": 12, "reddit": 20}

USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 raiders-daily/1.0"
