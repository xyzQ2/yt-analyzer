# igtt — Instagram Content Intelligence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A daily unattended job that finds high-performing public Instagram posts in the wine/meme/hospitality niche, works out why they worked, generates original content briefs for @drinktoiletwine, and measures how the published results perform.

**Architecture:** Three CLI entry points (`app.py` daily, `discover.py` weekly, `post.py` on dispatch) over one SQLite file. Collection is isolated behind `src/apify.py` so the data provider can be swapped. A free numeric scoring stage filters every post down to 40 before any AI call; Claude analyzes text, Gemini watches the top 15 videos. Output is a static HTML report plus rows in `ideas`.

**Tech Stack:** Python 3.11, stdlib `sqlite3`, `requests`, `jinja2`, `PyYAML`, `python-dotenv`, `anthropic`, `google-genai`, `pytest`, `pytest-mock`. Apify for scraping, Blotato for publishing, GitHub Actions for scheduling.

**Spec:** `docs/superpowers/specs/2026-09-07-igtt-instagram-content-intelligence-design.md`

## Global Constraints

- Python 3.11. Stdlib `sqlite3` only — no ORM, no database server.
- No Docker, no frontend framework, no Airtable/Make/Zapier.
- A metric that does not exist for a post type stores `NULL`, never `0`. Scoring skips `NULL`s; it never treats them as zero or as a low value.
- Every external call (Apify, Anthropic, Gemini, Blotato, SMTP) is wrapped. On failure it logs and returns `None`. One failed account or post never aborts the run.
- Logging via stdlib `logging` to stdout so GitHub Actions captures it. No `print()` in `src/`.
- Hard limits come from `config.yaml` and are enforced by truncation in code: `max_accounts: 75`, `posts_lookback_days: 7`, `candidate_posts_for_text_ai: 40`, `candidate_posts_for_video_ai: 15`, `daily_top_posts: 25`, `ideas.daily_count: 10`, `posting.max_per_day: 1`.
- Scoring weights, verbatim: `views_per_follower: 0.30`, `engagement_rate: 0.25`, `total_engagement: 0.20`, `raw_views: 0.15`, `comments: 0.10`, `ai_weight: 0.20`.
- Final ranking formula, verbatim: `final_score = 0.80 * performance_score + 0.20 * ai_virality_score`.
- Discovery thresholds, verbatim: `activate_above: 70`, `deactivate_below: 50`.
- `posting.auto` defaults to `false` and stays false until briefs are proven.
- No live network calls in tests, ever. All provider responses are fixtures under `tests/fixtures/`.
- Prompts live in `prompts/*.md` as plain files, never embedded in Python.
- Secrets come from `.env` locally and GitHub Actions secrets in CI. Never commit a token.
- No competitor content is copied. `similarity_risk: HIGH` ideas are rejected at generation. The repost lane requires `permission_granted = 1` and a non-empty `credit_handle`.

## File Structure

| File | Responsibility |
|---|---|
| `config.yaml` | All tunable values. The only file a non-developer edits. |
| `.env.example` | Names of every required secret. |
| `src/config.py` | Load and validate `config.yaml`, load `.env`. |
| `src/db.py` | Schema creation and every SQL statement in the project. |
| `src/apify.py` | The only module that knows scraping exists. Returns normalized post dicts. |
| `src/score.py` | Pure functions: percentiles, velocity, acceleration, performance and final scores. No I/O. |
| `src/analyze.py` | Claude text tier and Gemini video tier. JSON validation and retry. |
| `src/patterns.py` | Cluster analyses into recurring named patterns across 7/30/90-day windows. |
| `src/ideas.py` | Generate content briefs from top posts, patterns, and our own results. |
| `src/report.py` | Render `reports/latest.html`, optional SMTP send. |
| `src/blotato.py` | Media upload and Instagram publish. |
| `src/templates/report.html` | Jinja2 template, autoescape on. |
| `prompts/*.md` | analyze_text, analyze_video, patterns, ideas, discover. |
| `app.py` | Daily orchestrator. |
| `discover.py` | Weekly account discovery and re-scoring. |
| `post.py` | Publish one approved idea by id. |
| `.github/workflows/daily.yml` | Cron daily run, commits DB back. |
| `.github/workflows/post.yml` | `workflow_dispatch` with `idea_id` input. |

---

### Task 1: Repo reset, config, and database schema

Deletes the YouTube project and lays the foundation everything else builds on. The YouTube modules remain in git history.

**Files:**
- Delete: `src/fetch_channel.py`, `src/analyze_topics.py`, `src/generate_report.py`, `src/templates/report.html`, `run.py`, `tests/test_fetch_channel.py`, `tests/test_analyze_topics.py`, `tests/test_generate_report.py`, `tests/test_run.py`, `tests/conftest.py`, `tests/fixtures/sample_channel.json`, `.github/workflows/weekly.yml`
- Create: `config.yaml`, `src/config.py`, `src/db.py`
- Modify: `requirements.txt`, `.env.example`, `.gitignore`
- Test: `tests/test_db.py`, `tests/test_config.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `src.config.load_config(path: str = "config.yaml") -> dict`
  - `src.db.connect(path: str = "data/intelligence.db") -> sqlite3.Connection` — returns a connection with `row_factory = sqlite3.Row` and foreign keys on
  - `src.db.init_schema(conn: sqlite3.Connection) -> None`
  - `src.db.upsert_account(conn, username: str, platform: str = "instagram", category: str | None = None, followers: int | None = None, relevance_score: float | None = None, active: int = 1) -> int`
  - `src.db.get_active_accounts(conn) -> list[sqlite3.Row]`
  - `src.db.upsert_post(conn, post: dict) -> int`
  - `src.db.add_snapshot(conn, post_id: int, views: int | None, likes: int | None, comments: int | None, shares: int | None, captured_at: str | None = None) -> None`
  - `src.db.get_snapshots(conn, post_id: int) -> list[sqlite3.Row]` — ascending by `captured_at`

- [ ] **Step 1: Delete the YouTube project**

```bash
git rm -q src/fetch_channel.py src/analyze_topics.py src/generate_report.py \
  src/templates/report.html run.py \
  tests/test_fetch_channel.py tests/test_analyze_topics.py \
  tests/test_generate_report.py tests/test_run.py tests/conftest.py \
  tests/fixtures/sample_channel.json .github/workflows/weekly.yml
rm -rf src/__pycache__ tests/__pycache__ .pytest_cache
mkdir -p data prompts reports tests/fixtures
touch data/.gitkeep
```

- [ ] **Step 2: Rewrite `requirements.txt`**

Lower bounds rather than exact pins, so `pip` resolves current versions. `google-genai` is the current Gemini SDK; the older `google-generativeai` package is deprecated.

```
requests>=2.31
PyYAML>=6.0
python-dotenv>=1.0
jinja2>=3.1
anthropic>=0.40
google-genai>=1.0
pytest>=8.1
pytest-mock>=3.14
```

- [ ] **Step 3: Rewrite `.env.example`**

```
APIFY_TOKEN=your_apify_token_here
ANTHROPIC_API_KEY=your_anthropic_key_here
GEMINI_API_KEY=your_gemini_key_here
BLOTATO_API_KEY=your_blotato_key_here
BLOTATO_INSTAGRAM_ACCOUNT_ID=your_blotato_ig_account_id_here
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=you@gmail.com
SMTP_PASSWORD=your_gmail_app_password_here
SMTP_TO=you@gmail.com
```

- [ ] **Step 4: Append to `.gitignore`**

The database is committed deliberately (see Task 14), so it is NOT ignored. Reports are regenerated each run and the dated copies are noise.

```
reports/*.html
!reports/.gitkeep
```

- [ ] **Step 5: Write `config.yaml`**

```yaml
brand:
  name: Drink Toilet Wine
  instagram: drinktoiletwine
  voice: >
    Irreverent wine humour for people who drink cheap wine without apology.
    Service-industry insider energy. Never precious, never educational-lecture.

monitoring:
  max_accounts: 75
  posts_lookback_days: 7
  results_per_account: 20
  candidate_posts_for_text_ai: 40
  candidate_posts_for_video_ai: 15
  daily_top_posts: 25

categories:
  - wine
  - wine memes
  - alcohol
  - hospitality
  - restaurants
  - lifestyle
  - food
  - comedy

scoring:
  views_per_follower: 0.30
  engagement_rate: 0.25
  total_engagement: 0.20
  raw_views: 0.15
  comments: 0.10
  ai_weight: 0.20
  acceleration_threshold: 1.5

discovery:
  activate_above: 70
  deactivate_below: 50
  hashtags:
    - winememes
    - serverlife
    - restaurantlife
    - winetok
    - bartenderlife

ideas:
  daily_count: 10

posting:
  auto: false
  max_per_day: 1

models:
  text_analysis: claude-sonnet-5
  strategy: claude-opus-5
  video: models/gemini-2.5-flash

email:
  enabled: false
```

- [ ] **Step 6: Write the failing test for config loading**

Create `tests/test_config.py`:

```python
import pytest

from src.config import load_config


def test_load_config_reads_yaml(tmp_path):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        "brand:\n  instagram: drinktoiletwine\n"
        "monitoring:\n  max_accounts: 75\n"
    )
    cfg = load_config(str(cfg_file))
    assert cfg["brand"]["instagram"] == "drinktoiletwine"
    assert cfg["monitoring"]["max_accounts"] == 75


def test_load_config_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_config(str(tmp_path / "nope.yaml"))
```

- [ ] **Step 7: Run it and confirm it fails**

Run: `python -m pytest tests/test_config.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'src.config'`

- [ ] **Step 8: Write `src/config.py`**

```python
"""Loads config.yaml and .env. The only place either is read."""

import logging
from pathlib import Path

import yaml
from dotenv import load_dotenv

logger = logging.getLogger(__name__)


def load_config(path: str = "config.yaml") -> dict:
    """Read config.yaml and load .env into the environment."""
    cfg_path = Path(path)
    if not cfg_path.exists():
        raise FileNotFoundError(f"config not found: {cfg_path}")
    load_dotenv()
    with cfg_path.open(encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)
    logger.debug("loaded config from %s", cfg_path)
    return cfg
```

- [ ] **Step 9: Run it and confirm it passes**

Run: `python -m pytest tests/test_config.py -v`
Expected: 2 passed

- [ ] **Step 10: Write the failing tests for the database layer**

Create `tests/test_db.py`. Note what is being pinned down here: upsert is idempotent on `shortcode`, snapshots append rather than replace, and a `NULL` metric survives the round trip as `None` rather than becoming `0`.

```python
import sqlite3

import pytest

from src import db


@pytest.fixture()
def conn(tmp_path):
    c = db.connect(str(tmp_path / "test.db"))
    db.init_schema(c)
    yield c
    c.close()


def test_init_schema_creates_all_tables(conn):
    names = {
        r["name"]
        for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert {
        "accounts", "posts", "post_snapshots", "analyses",
        "patterns", "ideas", "repost_candidates",
    } <= names


def test_upsert_account_is_idempotent(conn):
    a = db.upsert_account(conn, "wineexample", category="wine", followers=82000)
    b = db.upsert_account(conn, "wineexample", category="wine", followers=90000)
    assert a == b
    rows = conn.execute("SELECT followers FROM accounts").fetchall()
    assert len(rows) == 1
    assert rows[0]["followers"] == 90000


def test_upsert_post_is_idempotent_on_shortcode(conn):
    account_id = db.upsert_account(conn, "wineexample")
    post = {
        "platform": "instagram", "shortcode": "ABC123", "account_id": account_id,
        "url": "https://instagram.com/p/ABC123", "video_url": None,
        "thumbnail_url": None, "caption": "hello", "content_type": "Video",
        "posted_at": "2026-09-01T12:00:00", "duration_sec": 14.0, "is_ours": 0,
    }
    first = db.upsert_post(conn, post)
    post["caption"] = "hello edited"
    second = db.upsert_post(conn, post)
    assert first == second
    rows = conn.execute("SELECT caption FROM posts").fetchall()
    assert len(rows) == 1
    assert rows[0]["caption"] == "hello edited"


def test_snapshots_append_and_preserve_null(conn):
    account_id = db.upsert_account(conn, "wineexample")
    post_id = db.upsert_post(conn, {
        "platform": "instagram", "shortcode": "ABC123", "account_id": account_id,
        "url": "u", "video_url": None, "thumbnail_url": None, "caption": "c",
        "content_type": "Sidecar", "posted_at": "2026-09-01T12:00:00",
        "duration_sec": None, "is_ours": 0,
    })
    db.add_snapshot(conn, post_id, views=None, likes=10, comments=2, shares=None,
                    captured_at="2026-09-01T13:00:00")
    db.add_snapshot(conn, post_id, views=None, likes=30, comments=5, shares=None,
                    captured_at="2026-09-02T13:00:00")
    snaps = db.get_snapshots(conn, post_id)
    assert len(snaps) == 2
    assert snaps[0]["likes"] == 10 and snaps[1]["likes"] == 30
    assert snaps[0]["views"] is None
    assert snaps[0]["shares"] is None


def test_get_active_accounts_excludes_inactive(conn):
    db.upsert_account(conn, "keep", active=1)
    db.upsert_account(conn, "drop", active=0)
    names = [r["username"] for r in db.get_active_accounts(conn)]
    assert names == ["keep"]
```

- [ ] **Step 11: Run them and confirm they fail**

Run: `python -m pytest tests/test_db.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'src.db'`

- [ ] **Step 12: Write `src/db.py`**

```python
"""Schema and every SQL statement in the project."""

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    id              INTEGER PRIMARY KEY,
    username        TEXT NOT NULL,
    platform        TEXT NOT NULL DEFAULT 'instagram',
    category        TEXT,
    followers       INTEGER,
    relevance_score REAL,
    active          INTEGER NOT NULL DEFAULT 1,
    last_checked    TEXT,
    added_at        TEXT NOT NULL,
    notes           TEXT,
    UNIQUE (username, platform)
);

CREATE TABLE IF NOT EXISTS posts (
    id            INTEGER PRIMARY KEY,
    platform      TEXT NOT NULL DEFAULT 'instagram',
    shortcode     TEXT NOT NULL UNIQUE,
    account_id    INTEGER REFERENCES accounts(id),
    url           TEXT,
    video_url     TEXT,
    thumbnail_url TEXT,
    caption       TEXT,
    content_type  TEXT,
    posted_at     TEXT,
    duration_sec  REAL,
    is_ours       INTEGER NOT NULL DEFAULT 0,
    first_seen_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS post_snapshots (
    id          INTEGER PRIMARY KEY,
    post_id     INTEGER NOT NULL REFERENCES posts(id),
    captured_at TEXT NOT NULL,
    views       INTEGER,
    likes       INTEGER,
    comments    INTEGER,
    shares      INTEGER
);
CREATE INDEX IF NOT EXISTS idx_snapshots_post ON post_snapshots(post_id, captured_at);

CREATE TABLE IF NOT EXISTS analyses (
    id                INTEGER PRIMARY KEY,
    post_id           INTEGER NOT NULL REFERENCES posts(id),
    tier              TEXT NOT NULL,
    json              TEXT NOT NULL,
    ai_virality_score REAL,
    model             TEXT,
    created_at        TEXT NOT NULL,
    UNIQUE (post_id, tier)
);

CREATE TABLE IF NOT EXISTS patterns (
    id               INTEGER PRIMARY KEY,
    pattern          TEXT NOT NULL UNIQUE,
    description      TEXT,
    first_seen       TEXT,
    last_seen        TEXT,
    occurrences_7d   INTEGER DEFAULT 0,
    occurrences_30d  INTEGER DEFAULT 0,
    occurrences_90d  INTEGER DEFAULT 0,
    avg_performance  REAL,
    trend_direction  TEXT,
    dtw_relevance    REAL
);

CREATE TABLE IF NOT EXISTS ideas (
    id                INTEGER PRIMARY KEY,
    created_at        TEXT NOT NULL,
    brief_json        TEXT NOT NULL,
    source_pattern_id INTEGER REFERENCES patterns(id),
    similarity_risk   TEXT,
    confidence        REAL,
    status            TEXT NOT NULL DEFAULT 'new',
    posted_shortcode  TEXT,
    posted_at         TEXT
);

CREATE TABLE IF NOT EXISTS repost_candidates (
    id                 INTEGER PRIMARY KEY,
    post_id            INTEGER NOT NULL REFERENCES posts(id),
    permission_granted INTEGER NOT NULL DEFAULT 0,
    credit_handle      TEXT,
    requested_at       TEXT,
    granted_at         TEXT,
    status             TEXT NOT NULL DEFAULT 'pending'
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path: str = "data/intelligence.db") -> sqlite3.Connection:
    """Open the database, creating the parent directory if needed."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def upsert_account(conn, username, platform="instagram", category=None,
                   followers=None, relevance_score=None, active=1) -> int:
    """Insert or update an account. Returns its id."""
    conn.execute(
        """
        INSERT INTO accounts (username, platform, category, followers,
                              relevance_score, active, added_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(username, platform) DO UPDATE SET
            category        = COALESCE(excluded.category, accounts.category),
            followers       = COALESCE(excluded.followers, accounts.followers),
            relevance_score = COALESCE(excluded.relevance_score, accounts.relevance_score),
            active          = excluded.active
        """,
        (username, platform, category, followers, relevance_score, active, _now()),
    )
    conn.commit()
    row = conn.execute(
        "SELECT id FROM accounts WHERE username = ? AND platform = ?",
        (username, platform),
    ).fetchone()
    return row["id"]


def get_active_accounts(conn) -> list:
    return conn.execute(
        "SELECT * FROM accounts WHERE active = 1 ORDER BY id"
    ).fetchall()


def set_account_score(conn, account_id: int, relevance_score: float, active: int) -> None:
    conn.execute(
        "UPDATE accounts SET relevance_score = ?, active = ?, last_checked = ? WHERE id = ?",
        (relevance_score, active, _now(), account_id),
    )
    conn.commit()


def upsert_post(conn, post: dict) -> int:
    """Insert or update a post keyed on shortcode. Returns its id."""
    conn.execute(
        """
        INSERT INTO posts (platform, shortcode, account_id, url, video_url,
                           thumbnail_url, caption, content_type, posted_at,
                           duration_sec, is_ours, first_seen_at)
        VALUES (:platform, :shortcode, :account_id, :url, :video_url,
                :thumbnail_url, :caption, :content_type, :posted_at,
                :duration_sec, :is_ours, :first_seen_at)
        ON CONFLICT(shortcode) DO UPDATE SET
            caption       = excluded.caption,
            video_url     = COALESCE(excluded.video_url, posts.video_url),
            thumbnail_url = COALESCE(excluded.thumbnail_url, posts.thumbnail_url),
            content_type  = excluded.content_type,
            duration_sec  = COALESCE(excluded.duration_sec, posts.duration_sec)
        """,
        {**{"is_ours": 0, "account_id": None, "url": None, "video_url": None,
            "thumbnail_url": None, "caption": None, "content_type": None,
            "posted_at": None, "duration_sec": None, "platform": "instagram"},
         **post, "first_seen_at": _now()},
    )
    conn.commit()
    row = conn.execute(
        "SELECT id FROM posts WHERE shortcode = ?", (post["shortcode"],)
    ).fetchone()
    return row["id"]


def add_snapshot(conn, post_id, views, likes, comments, shares, captured_at=None) -> None:
    """Append a metrics snapshot. Never overwrites an earlier one."""
    conn.execute(
        """
        INSERT INTO post_snapshots (post_id, captured_at, views, likes, comments, shares)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (post_id, captured_at or _now(), views, likes, comments, shares),
    )
    conn.commit()


def get_snapshots(conn, post_id: int) -> list:
    return conn.execute(
        "SELECT * FROM post_snapshots WHERE post_id = ? ORDER BY captured_at ASC",
        (post_id,),
    ).fetchall()
```

- [ ] **Step 13: Run the tests and confirm they pass**

Run: `python -m pytest tests/ -v`
Expected: 7 passed

- [ ] **Step 14: Commit**

```bash
git add -A
git commit -m "feat: reset repo to igtt, add config loader and sqlite schema"
```

---

### Task 2: Apify collection adapter

The only module that knows scraping exists. Everything downstream sees a normalized dict. Swapping providers or adding TikTok later touches this file alone.

**Files:**
- Create: `src/apify.py`
- Test: `tests/test_apify.py`, `tests/fixtures/apify_instagram.json`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `src.apify.normalize_post(raw: dict) -> dict | None` — returns `None` if the raw item has no `shortCode`
  - `src.apify.fetch_profile_posts(token: str, usernames: list[str], lookback_days: int, results_limit: int) -> list[dict]`
  - Normalized post dict keys, relied on by every later task: `platform`, `shortcode`, `username`, `owner_followers`, `url`, `video_url`, `thumbnail_url`, `caption`, `content_type`, `posted_at`, `duration_sec`, `views`, `likes`, `comments`, `shares`

- [ ] **Step 1: Create the fixture**

Create `tests/fixtures/apify_instagram.json`. Shape copied from the `apify~instagram-scraper` dataset output. Three items on purpose: a Reel with full metrics, a carousel with **no view count** (the `NULL` case that must not become `0`), and a junk item with no `shortCode` that must be dropped.

```json
[
  {
    "type": "Video",
    "shortCode": "DAbc123",
    "url": "https://www.instagram.com/p/DAbc123/",
    "caption": "POV: you told the sommelier you actually like $12 wine",
    "timestamp": "2026-09-05T14:02:11.000Z",
    "videoUrl": "https://scontent.cdninstagram.com/v/reel1.mp4",
    "displayUrl": "https://scontent.cdninstagram.com/v/thumb1.jpg",
    "videoViewCount": 487000,
    "videoPlayCount": 487000,
    "likesCount": 61200,
    "commentsCount": 3140,
    "videoDuration": 14.3,
    "ownerUsername": "wineexample",
    "ownerFullName": "Wine Example",
    "ownerFollowersCount": 82000
  },
  {
    "type": "Sidecar",
    "shortCode": "DXyz789",
    "url": "https://www.instagram.com/p/DXyz789/",
    "caption": "five wines under twelve dollars, ranked by regret",
    "timestamp": "2026-09-04T09:30:00.000Z",
    "displayUrl": "https://scontent.cdninstagram.com/v/thumb2.jpg",
    "likesCount": 4100,
    "commentsCount": 220,
    "ownerUsername": "wineexample",
    "ownerFollowersCount": 82000
  },
  {
    "type": "Image",
    "caption": "no shortcode, must be dropped"
  }
]
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_apify.py`:

```python
import json
from pathlib import Path

from src import apify

FIXTURE = Path(__file__).parent / "fixtures" / "apify_instagram.json"


def raw_items():
    return json.loads(FIXTURE.read_text())


def test_normalize_reel_maps_every_field():
    post = apify.normalize_post(raw_items()[0])
    assert post["shortcode"] == "DAbc123"
    assert post["username"] == "wineexample"
    assert post["owner_followers"] == 82000
    assert post["content_type"] == "Video"
    assert post["video_url"] == "https://scontent.cdninstagram.com/v/reel1.mp4"
    assert post["views"] == 487000
    assert post["likes"] == 61200
    assert post["comments"] == 3140
    assert post["duration_sec"] == 14.3
    assert post["posted_at"].startswith("2026-09-05T14:02:11")


def test_carousel_views_stay_none_not_zero():
    post = apify.normalize_post(raw_items()[1])
    assert post["views"] is None, "a carousel has no view count; None is not zero"
    assert post["shares"] is None
    assert post["video_url"] is None
    assert post["likes"] == 4100


def test_item_without_shortcode_is_dropped():
    assert apify.normalize_post(raw_items()[2]) is None


def test_fetch_profile_posts_builds_expected_request(mocker):
    mock_post = mocker.patch("src.apify.requests.post")
    mock_post.return_value.status_code = 200
    mock_post.return_value.json.return_value = raw_items()

    posts = apify.fetch_profile_posts("tok", ["wineexample"], lookback_days=7,
                                      results_limit=20)

    assert len(posts) == 2, "the junk item must be dropped"
    url, kwargs = mock_post.call_args[0][0], mock_post.call_args[1]
    assert "apify~instagram-scraper" in url
    assert "token" not in url, "token belongs in the header, not the query string"
    assert kwargs["headers"]["Authorization"] == "Bearer tok"
    body = kwargs["json"]
    assert body["directUrls"] == ["https://www.instagram.com/wineexample/"]
    assert body["onlyPostsNewerThan"] == "7 days"
    assert body["resultsLimit"] == 20
    assert body["resultsType"] == "posts"


def test_fetch_profile_posts_returns_empty_on_http_error(mocker):
    mock_post = mocker.patch("src.apify.requests.post")
    mock_post.side_effect = Exception("connection reset")
    assert apify.fetch_profile_posts("tok", ["a"], 7, 20) == []
```

- [ ] **Step 3: Run them and confirm they fail**

Run: `python -m pytest tests/test_apify.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'src.apify'`

- [ ] **Step 4: Write `src/apify.py`**

Note the token goes in the `Authorization` header, not the URL query string as the source n8n workflow did. Query-string tokens leak into logs and proxy history.

```python
"""Apify adapter. The only module in the project that knows scraping exists."""

import logging

import requests

logger = logging.getLogger(__name__)

ACTOR_URL = ("https://api.apify.com/v2/acts/apify~instagram-scraper/"
             "run-sync-get-dataset-items")
TIMEOUT = 600


def normalize_post(raw: dict) -> dict | None:
    """Map one Apify dataset item to the project's post shape.

    Returns None for items with no shortCode. A metric the platform does not
    report stays None; it never becomes 0.
    """
    shortcode = raw.get("shortCode")
    if not shortcode:
        logger.debug("dropping item with no shortCode")
        return None

    views = raw.get("videoPlayCount") or raw.get("videoViewCount")

    return {
        "platform": "instagram",
        "shortcode": shortcode,
        "username": raw.get("ownerUsername"),
        "owner_followers": raw.get("ownerFollowersCount"),
        "url": raw.get("url"),
        "video_url": raw.get("videoUrl"),
        "thumbnail_url": raw.get("displayUrl"),
        "caption": raw.get("caption"),
        "content_type": raw.get("type"),
        "posted_at": raw.get("timestamp"),
        "duration_sec": raw.get("videoDuration"),
        "views": views,
        "likes": raw.get("likesCount"),
        "comments": raw.get("commentsCount"),
        "shares": None,  # Instagram does not expose share counts publicly
    }


def fetch_profile_posts(token: str, usernames: list[str], lookback_days: int,
                        results_limit: int) -> list[dict]:
    """Fetch recent posts for the given usernames. Returns [] on any failure."""
    if not usernames:
        return []

    body = {
        "directUrls": [f"https://www.instagram.com/{u}/" for u in usernames],
        "resultsType": "posts",
        "resultsLimit": results_limit,
        "onlyPostsNewerThan": f"{lookback_days} days",
        "addParentData": False,
    }
    try:
        resp = requests.post(
            ACTOR_URL,
            headers={"Authorization": f"Bearer {token}"},
            json=body,
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        items = resp.json()
    except Exception as exc:
        logger.error("apify fetch failed for %d accounts: %s", len(usernames), exc)
        return []

    posts = [p for p in (normalize_post(i) for i in items) if p]
    logger.info("apify returned %d items, %d usable posts", len(items), len(posts))
    return posts
```

- [ ] **Step 5: Run the tests and confirm they pass**

Run: `python -m pytest tests/test_apify.py -v`
Expected: 5 passed

- [ ] **Step 6: Commit**

```bash
git add src/apify.py tests/test_apify.py tests/fixtures/apify_instagram.json
git commit -m "feat: add apify instagram collection adapter"
```

---

### Task 3: Scoring — percentiles, velocity, acceleration

Pure functions over lists of dicts. No I/O, no database, no network. This is the stage that makes the whole system cheap: it ranks everything for free so only survivors reach a model.

**Files:**
- Create: `src/score.py`
- Test: `tests/test_score.py`

**Interfaces:**
- Consumes: normalized post dicts from Task 2.
- Produces:
  - `src.score.percentile_ranks(values: list[float | None]) -> list[float | None]` — 0-100, `None` in gives `None` out
  - `src.score.post_metrics(post: dict) -> dict` — keys `views_per_follower`, `engagement_rate`, `total_engagement`, `raw_views`, `comments_per_follower`, each `float | None`
  - `src.score.velocity(snapshots: list[dict], threshold: float = 1.5) -> dict` — keys `views_per_hour`, `acceleration`, `accelerating`
  - `src.score.score_posts(posts: list[dict], weights: dict) -> list[dict]` — returns the same dicts with `performance_score` added, sorted descending
  - `src.score.final_score(performance_score: float, ai_virality_score: float | None, ai_weight: float) -> float`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_score.py`. The `None`-handling tests are the important ones — that is where a naive implementation silently corrupts the ranking.

```python
import pytest

from src import score


def test_percentile_ranks_basic():
    assert score.percentile_ranks([10, 20, 30, 40]) == [0.0, 100 / 3, 200 / 3, 100.0]


def test_percentile_ranks_none_passes_through():
    out = score.percentile_ranks([10, None, 30])
    assert out[1] is None, "a missing metric must not be ranked as a low value"
    assert out[0] == 0.0 and out[2] == 100.0


def test_percentile_ranks_all_identical_gives_fifty():
    assert score.percentile_ranks([5, 5, 5]) == [50.0, 50.0, 50.0]


def test_percentile_ranks_empty():
    assert score.percentile_ranks([]) == []


def test_post_metrics_reel():
    m = score.post_metrics({
        "views": 487000, "likes": 61200, "comments": 3140, "shares": None,
        "owner_followers": 82000,
    })
    assert m["views_per_follower"] == pytest.approx(5.939, rel=1e-3)
    assert m["engagement_rate"] == pytest.approx((61200 + 3140) / 487000, rel=1e-6)
    assert m["total_engagement"] == 64340
    assert m["raw_views"] == 487000
    assert m["comments_per_follower"] == pytest.approx(3140 / 82000, rel=1e-6)


def test_post_metrics_carousel_has_none_view_metrics():
    m = score.post_metrics({
        "views": None, "likes": 4100, "comments": 220, "shares": None,
        "owner_followers": 82000,
    })
    assert m["views_per_follower"] is None
    assert m["engagement_rate"] is None, "no views means no engagement rate"
    assert m["raw_views"] is None
    assert m["total_engagement"] == 4320
    assert m["comments_per_follower"] == pytest.approx(220 / 82000, rel=1e-6)


def test_post_metrics_zero_followers_does_not_divide_by_zero():
    m = score.post_metrics({"views": 100, "likes": 1, "comments": 0,
                            "shares": None, "owner_followers": 0})
    assert m["views_per_follower"] is None


def test_velocity_needs_two_snapshots():
    v = score.velocity([{"captured_at": "2026-09-01T00:00:00", "views": 1000}])
    assert v["views_per_hour"] is None
    assert v["accelerating"] is False


def test_velocity_and_acceleration():
    snaps = [
        {"captured_at": "2026-09-01T00:00:00+00:00", "views": 31000},
        {"captured_at": "2026-09-02T00:00:00+00:00", "views": 89000},
        {"captured_at": "2026-09-03T00:00:00+00:00", "views": 241000},
    ]
    v = score.velocity(snaps, threshold=1.5)
    assert v["views_per_hour"] == pytest.approx((241000 - 89000) / 24)
    assert v["acceleration"] == pytest.approx((241000 - 89000) / (89000 - 31000))
    assert v["accelerating"] is True


def test_velocity_flat_post_is_not_accelerating():
    snaps = [
        {"captured_at": "2026-09-01T00:00:00+00:00", "views": 1000},
        {"captured_at": "2026-09-02T00:00:00+00:00", "views": 2000},
        {"captured_at": "2026-09-03T00:00:00+00:00", "views": 2500},
    ]
    assert score.velocity(snaps)["accelerating"] is False


WEIGHTS = {
    "views_per_follower": 0.30, "engagement_rate": 0.25,
    "total_engagement": 0.20, "raw_views": 0.15, "comments": 0.10,
}


def test_score_posts_ranks_the_overperformer_first():
    posts = [
        {"shortcode": "small", "views": 1000, "likes": 10, "comments": 1,
         "shares": None, "owner_followers": 100000},
        {"shortcode": "banger", "views": 487000, "likes": 61200, "comments": 3140,
         "shares": None, "owner_followers": 82000},
    ]
    ranked = score.score_posts(posts, WEIGHTS)
    assert ranked[0]["shortcode"] == "banger"
    assert 0 <= ranked[0]["performance_score"] <= 100


def test_score_posts_reweights_when_a_metric_is_missing():
    """A carousel is scored on the metrics it has, not penalised for the rest."""
    posts = [
        {"shortcode": "reel", "views": 5000, "likes": 100, "comments": 10,
         "shares": None, "owner_followers": 1000},
        {"shortcode": "carousel", "views": None, "likes": 9000, "comments": 900,
         "shares": None, "owner_followers": 1000},
    ]
    ranked = score.score_posts(posts, WEIGHTS)
    by_code = {p["shortcode"]: p for p in ranked}
    assert by_code["carousel"]["performance_score"] > 0
    assert by_code["carousel"]["performance_score"] == pytest.approx(100.0)


def test_final_score_blends_eighty_twenty():
    assert score.final_score(90.0, 50.0, 0.20) == pytest.approx(82.0)


def test_final_score_without_ai_uses_performance_only():
    assert score.final_score(90.0, None, 0.20) == pytest.approx(90.0)
```

- [ ] **Step 2: Run them and confirm they fail**

Run: `python -m pytest tests/test_score.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'src.score'`

- [ ] **Step 3: Write `src/score.py`**

```python
"""Numeric ranking. Pure functions — no I/O, no network, no database.

This stage runs over every collected post at zero API cost and is what keeps
the AI spend bounded.
"""

import logging
from datetime import datetime

logger = logging.getLogger(__name__)

METRIC_KEYS = (
    "views_per_follower",
    "engagement_rate",
    "total_engagement",
    "raw_views",
    "comments_per_follower",
)

# config.yaml names the last weight "comments"; the metric is per-follower.
WEIGHT_KEY_FOR = {
    "views_per_follower": "views_per_follower",
    "engagement_rate": "engagement_rate",
    "total_engagement": "total_engagement",
    "raw_views": "raw_views",
    "comments_per_follower": "comments",
}


def percentile_ranks(values: list) -> list:
    """Rank values 0-100 by position. None in, None out.

    None means the platform does not report that metric for that post type.
    Ranking it as a low value would penalise carousels for not being videos.
    """
    present = [v for v in values if v is not None]
    if not present:
        return [None] * len(values)
    lo, hi = min(present), max(present)
    if hi == lo:
        return [None if v is None else 50.0 for v in values]
    span = hi - lo
    return [None if v is None else (v - lo) / span * 100.0 for v in values]


def post_metrics(post: dict) -> dict:
    """Derive the five ranking metrics for one post. Missing stays None."""
    views = post.get("views")
    likes = post.get("likes") or 0
    comments = post.get("comments") or 0
    shares = post.get("shares") or 0
    followers = post.get("owner_followers") or 0

    engagement = likes + comments + shares

    return {
        "views_per_follower": (views / followers) if views and followers else None,
        "engagement_rate": (engagement / views) if views else None,
        "total_engagement": float(engagement),
        "raw_views": float(views) if views else None,
        "comments_per_follower": (comments / followers) if followers else None,
    }


def velocity(snapshots: list, threshold: float = 1.5) -> dict:
    """Views per hour in the latest window, and whether the post is speeding up.

    Needs two snapshots for a rate and three for an acceleration. Fewer than
    that returns Nones rather than guessing.
    """
    usable = [s for s in snapshots if s.get("views") is not None]
    if len(usable) < 2:
        return {"views_per_hour": None, "acceleration": None, "accelerating": False}

    def window(a, b):
        t0 = datetime.fromisoformat(a["captured_at"])
        t1 = datetime.fromisoformat(b["captured_at"])
        hours = (t1 - t0).total_seconds() / 3600
        if hours <= 0:
            return None
        return (b["views"] - a["views"]) / hours

    latest = window(usable[-2], usable[-1])
    if len(usable) < 3:
        return {"views_per_hour": latest, "acceleration": None, "accelerating": False}

    previous = window(usable[-3], usable[-2])
    if not previous or previous <= 0 or latest is None:
        return {"views_per_hour": latest, "acceleration": None, "accelerating": False}

    accel = latest / previous
    return {
        "views_per_hour": latest,
        "acceleration": accel,
        "accelerating": accel >= threshold,
    }


def score_posts(posts: list, weights: dict) -> list:
    """Add performance_score (0-100) to each post, sorted best first.

    Weights of metrics that are None for a given post are redistributed across
    the metrics it does have, so post types compete fairly.
    """
    if not posts:
        return []

    metrics = [post_metrics(p) for p in posts]
    ranked = {
        key: percentile_ranks([m[key] for m in metrics]) for key in METRIC_KEYS
    }

    scored = []
    for i, post in enumerate(posts):
        total, weight_used = 0.0, 0.0
        for key in METRIC_KEYS:
            pct = ranked[key][i]
            if pct is None:
                continue
            w = weights.get(WEIGHT_KEY_FOR[key], 0.0)
            total += w * pct
            weight_used += w
        out = dict(post)
        out["performance_score"] = (total / weight_used) if weight_used else 0.0
        scored.append(out)

    scored.sort(key=lambda p: p["performance_score"], reverse=True)
    return scored


def final_score(performance_score: float, ai_virality_score, ai_weight: float) -> float:
    """0.80 * performance + 0.20 * ai virality. No AI score means performance alone."""
    if ai_virality_score is None:
        return performance_score
    return (1 - ai_weight) * performance_score + ai_weight * ai_virality_score
```

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `python -m pytest tests/test_score.py -v`
Expected: 14 passed

- [ ] **Step 5: Commit**

```bash
git add src/score.py tests/test_score.py
git commit -m "feat: add numeric scoring with velocity and acceleration"
```

---

### Task 4: Prompts and the Claude text-analysis tier

Tier 1: the top 40 posts by `performance_score` get a strategist analysis from caption, metrics and context. No video, no vision.

**Files:**
- Create: `prompts/analyze_text.md`, `prompts/analyze_video.md`, `src/analyze.py`
- Test: `tests/test_analyze.py`

**Interfaces:**
- Consumes: `src.score.score_posts` output (Task 3), `src.config.load_config` (Task 1).
- Produces:
  - `src.analyze.load_prompt(name: str) -> str` — reads `prompts/<name>.md`
  - `src.analyze.extract_json(text: str) -> dict | None` — tolerates ```json fences
  - `src.analyze.analyze_text(client, post: dict, brand: dict, model: str) -> dict | None` — returns the strategist JSON with an `ai_virality_score` key, or `None`
  - Strategist JSON keys, relied on by Tasks 6, 7 and 8: `hook`, `hook_type`, `payoff`, `emotional_driver`, `humor_mechanism`, `social_driver`, `comment_driver`, `rewatch_driver`, `visual_structure`, `caption_role`, `audience`, `timing`, `why_it_overperformed` (list of 3), `reusable_pattern`, `scores` (object with `hook`, `shareability`, `originality`, `relatability`, `rewatchability`, `cultural_relevance`), `ai_virality_score`

- [ ] **Step 1: Write `prompts/analyze_text.md`**

Placeholders `{brand_name}`, `{brand_voice}`, `{post_json}` are filled with `str.format`.

```markdown
Analyze this social-media post as a content strategist.

Target brand: {brand_name}
Brand voice: {brand_voice}

Do not copy the content. Extract reusable structure only.

Post data:
{post_json}

Determine:

HOOK — what grabs attention immediately?
HOOK TYPE — curiosity / controversy / relatability / surprise / identity / aspiration / humor / disgust / status
PAYOFF — what does the viewer get for continuing?
EMOTIONAL DRIVER — why does anyone care?
HUMOR MECHANISM — if relevant.
SOCIAL DRIVER — why would someone tag or send this to a friend?
COMMENT DRIVER — why would people respond?
REWATCH DRIVER — does the format encourage looping or replay?
VISUAL STRUCTURE — describe the creative format.
CAPTION ROLE — how does the caption contribute?
AUDIENCE — who feels specifically understood by this?
TIMING — is there a cultural or trend component?
WHY IT OVERPERFORMED — the three strongest explanations.
REUSABLE PATTERN — abstract this into a formula reusable without copying it.
  Example: "Highly recognizable situation + escalating frustration + absurd visual payoff."

Score each 0-100: hook, shareability, originality, relatability, rewatchability,
cultural_relevance. Then give an overall ai_virality_score 0-100.

Respond with ONLY a JSON object, no prose and no markdown fence, in exactly this shape:

{{
  "hook": "", "hook_type": "", "payoff": "", "emotional_driver": "",
  "humor_mechanism": "", "social_driver": "", "comment_driver": "",
  "rewatch_driver": "", "visual_structure": "", "caption_role": "",
  "audience": "", "timing": "",
  "why_it_overperformed": ["", "", ""],
  "reusable_pattern": "",
  "scores": {{"hook": 0, "shareability": 0, "originality": 0,
              "relatability": 0, "rewatchability": 0, "cultural_relevance": 0}},
  "ai_virality_score": 0
}}
```

- [ ] **Step 2: Write `prompts/analyze_video.md`**

Schema reused verbatim from the existing n8n "Short Form Video Analyzer" workflow. Used in Task 5; written now so both prompts land in one commit.

```markdown
You are an expert viral video analyst focused on creating actionable recreation
blueprints. Analyze the provided video and produce a guide a creator can implement
immediately. Do not copy the content — abstract it.

1. Core concept and hook analysis: central idea, target audience, and the first three
   seconds broken into visual elements, audio elements, psychological trigger, and a
   hook formula template others can reuse.
2. Content structure: opening, development, climax/payoff, call to action.
3. Production and editing: layout, text overlays, camera work, UI style, speaker
   framing, music.
4. Recreation framework: universal elements, customizable elements, common variations.

Keep it concise and specific. Prefer templates and formulas over description.

Respond with ONLY a JSON object, no prose and no markdown fence, in exactly this shape:

{
  "core_concept": "", "target_audience": "",
  "hook_analysis": {"visual_elements": "", "audio_elements": "",
                    "psychological_trigger": "", "hook_formula": ""},
  "content_structure": {"opening": "", "development": "",
                        "climax_payoff": "", "call_to_action": ""},
  "visual_style": {"layout": "", "text_overlays": "", "camera_work": "",
                   "ui_style": "", "speaker_framing": "", "music": ""},
  "recreation_framework": {"universal_elements": [], "customizable_elements": [],
                           "common_variations": []}
}
```

- [ ] **Step 3: Write the failing tests**

Create `tests/test_analyze.py`:

```python
import json

import pytest

from src import analyze


def fake_response(text):
    class Block:
        def __init__(self, t):
            self.text = t
    class Msg:
        def __init__(self, t):
            self.content = [Block(t)]
    return Msg(text)


VALID = {
    "hook": "POV setup", "hook_type": "relatability", "payoff": "absurd reveal",
    "emotional_driver": "recognition", "humor_mechanism": "escalation",
    "social_driver": "tag a coworker", "comment_driver": "share your worst shift",
    "rewatch_driver": "fast cut loop", "visual_structure": "single take",
    "caption_role": "sets the premise", "audience": "restaurant staff",
    "timing": "none",
    "why_it_overperformed": ["specific", "recognisable", "short"],
    "reusable_pattern": "Insider frustration + recognisable setup + outsized reaction",
    "scores": {"hook": 92, "shareability": 88, "originality": 70,
               "relatability": 95, "rewatchability": 80, "cultural_relevance": 60},
    "ai_virality_score": 89,
}


def test_load_prompt_reads_file():
    text = analyze.load_prompt("analyze_text")
    assert "REUSABLE PATTERN" in text


def test_extract_json_plain():
    assert analyze.extract_json('{"a": 1}') == {"a": 1}


def test_extract_json_strips_markdown_fence():
    assert analyze.extract_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_extract_json_returns_none_on_garbage():
    assert analyze.extract_json("I'm sorry, I can't do that") is None


def test_analyze_text_returns_parsed_json(mocker):
    client = mocker.Mock()
    client.messages.create.return_value = fake_response(json.dumps(VALID))
    out = analyze.analyze_text(client, {"shortcode": "A", "caption": "c"},
                               {"name": "DTW", "voice": "v"}, "claude-sonnet-5")
    assert out["ai_virality_score"] == 89
    assert out["reusable_pattern"].startswith("Insider frustration")


def test_analyze_text_retries_once_then_gives_up(mocker):
    client = mocker.Mock()
    client.messages.create.return_value = fake_response("not json at all")
    out = analyze.analyze_text(client, {"shortcode": "A"}, {"name": "D", "voice": "v"},
                               "claude-sonnet-5")
    assert out is None
    assert client.messages.create.call_count == 2, "one retry, then give up"


def test_analyze_text_rejects_response_missing_required_keys(mocker):
    client = mocker.Mock()
    client.messages.create.return_value = fake_response('{"hook": "only this"}')
    assert analyze.analyze_text(client, {"shortcode": "A"},
                                {"name": "D", "voice": "v"}, "claude-sonnet-5") is None


def test_analyze_text_survives_api_exception(mocker):
    client = mocker.Mock()
    client.messages.create.side_effect = Exception("rate limited")
    assert analyze.analyze_text(client, {"shortcode": "A"},
                                {"name": "D", "voice": "v"}, "claude-sonnet-5") is None
```

- [ ] **Step 4: Run them and confirm they fail**

Run: `python -m pytest tests/test_analyze.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'src.analyze'`

- [ ] **Step 5: Write `src/analyze.py`** (text tier only; Task 5 appends the video tier)

```python
"""AI analysis. Claude handles text; Gemini handles video (see analyze_video)."""

import json
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

PROMPT_DIR = Path(__file__).parent.parent / "prompts"
MAX_ATTEMPTS = 2

TEXT_REQUIRED_KEYS = {
    "hook", "hook_type", "payoff", "emotional_driver", "social_driver",
    "comment_driver", "rewatch_driver", "visual_structure", "caption_role",
    "audience", "timing", "why_it_overperformed", "reusable_pattern",
    "scores", "ai_virality_score",
}

_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def load_prompt(name: str) -> str:
    return (PROMPT_DIR / f"{name}.md").read_text(encoding="utf-8")


def extract_json(text: str):
    """Parse a JSON object out of a model response. None if there isn't one."""
    if not text:
        return None
    candidate = text.strip()
    fenced = _FENCE.search(candidate)
    if fenced:
        candidate = fenced.group(1)
    start, end = candidate.find("{"), candidate.rfind("}")
    if start == -1 or end == -1:
        return None
    try:
        return json.loads(candidate[start:end + 1])
    except json.JSONDecodeError:
        return None


def _call_claude(client, model: str, prompt: str, max_tokens: int = 2000):
    resp = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(block.text for block in resp.content if hasattr(block, "text"))


def analyze_text(client, post: dict, brand: dict, model: str):
    """Tier 1 strategist analysis of one post. None on any failure."""
    payload = {k: post.get(k) for k in (
        "shortcode", "username", "caption", "content_type", "posted_at",
        "duration_sec", "views", "likes", "comments", "owner_followers",
        "performance_score",
    )}
    prompt = load_prompt("analyze_text").format(
        brand_name=brand.get("name", ""),
        brand_voice=brand.get("voice", ""),
        post_json=json.dumps(payload, indent=2, default=str),
    )

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            raw = _call_claude(client, model, prompt)
        except Exception as exc:
            logger.error("claude text analysis failed for %s: %s",
                         post.get("shortcode"), exc)
            return None
        data = extract_json(raw)
        if data and TEXT_REQUIRED_KEYS <= set(data):
            return data
        logger.warning("bad text analysis for %s (attempt %d/%d)",
                       post.get("shortcode"), attempt, MAX_ATTEMPTS)
    return None
```

- [ ] **Step 6: Run the tests and confirm they pass**

Run: `python -m pytest tests/test_analyze.py -v`
Expected: 8 passed

- [ ] **Step 7: Commit**

```bash
git add prompts/analyze_text.md prompts/analyze_video.md src/analyze.py tests/test_analyze.py
git commit -m "feat: add prompts and claude text-tier analysis"
```

---

### Task 5: Gemini video-analysis tier

Tier 2: the top 15 surviving posts that actually have a `video_url`. Gemini 2.5 Flash ingests the MP4 and returns the recreation blueprint. Claude has no native video input, which is the whole reason this vendor split exists.

**Files:**
- Modify: `src/analyze.py`
- Test: `tests/test_analyze.py` (append)

**Interfaces:**
- Consumes: `load_prompt`, `extract_json` from Task 4.
- Produces:
  - `src.analyze.analyze_video(api_key: str, video_url: str, model: str) -> dict | None` — returns the blueprint JSON or `None`
  - Blueprint JSON keys, relied on by Tasks 7 and 8: `core_concept`, `target_audience`, `hook_analysis`, `content_structure`, `visual_style`, `recreation_framework`

- [ ] **Step 1: Write the failing tests (append to `tests/test_analyze.py`)**

```python
VALID_BLUEPRINT = {
    "core_concept": "server rates guest wine orders",
    "target_audience": "restaurant workers",
    "hook_analysis": {"visual_elements": "close on wine list",
                      "audio_elements": "'you ordered WHAT'",
                      "psychological_trigger": "in-group recognition",
                      "hook_formula": "Show [X] + State '[Y]' + Promise '[Z]'"},
    "content_structure": {"opening": "cold open", "development": "three examples",
                          "climax_payoff": "worst order", "call_to_action": "comment yours"},
    "visual_style": {"layout": "single shot", "text_overlays": "captions bottom third",
                     "camera_work": "handheld push-in", "ui_style": "none",
                     "speaker_framing": "medium close", "music": "none"},
    "recreation_framework": {"universal_elements": ["insider POV"],
                             "customizable_elements": ["the niche"],
                             "common_variations": ["ranked list version"]},
}


def test_analyze_video_downloads_and_parses(mocker):
    mock_get = mocker.patch("src.analyze.requests.get")
    mock_get.return_value.status_code = 200
    mock_get.return_value.content = b"fake mp4 bytes"

    mock_client_cls = mocker.patch("src.analyze.genai.Client")
    client = mock_client_cls.return_value
    client.models.generate_content.return_value.text = json.dumps(VALID_BLUEPRINT)

    out = analyze.analyze_video("key", "https://cdn/reel.mp4", "models/gemini-2.5-flash")
    assert out["recreation_framework"]["universal_elements"] == ["insider POV"]
    mock_get.assert_called_once()


def test_analyze_video_returns_none_without_url():
    assert analyze.analyze_video("key", None, "models/gemini-2.5-flash") is None


def test_analyze_video_survives_download_failure(mocker):
    mocker.patch("src.analyze.requests.get", side_effect=Exception("404"))
    mocker.patch("src.analyze.genai.Client")
    assert analyze.analyze_video("key", "https://cdn/x.mp4",
                                 "models/gemini-2.5-flash") is None


def test_analyze_video_rejects_incomplete_blueprint(mocker):
    mock_get = mocker.patch("src.analyze.requests.get")
    mock_get.return_value.status_code = 200
    mock_get.return_value.content = b"bytes"
    mock_client_cls = mocker.patch("src.analyze.genai.Client")
    mock_client_cls.return_value.models.generate_content.return_value.text = (
        '{"core_concept": "only this"}'
    )
    assert analyze.analyze_video("key", "https://cdn/x.mp4",
                                 "models/gemini-2.5-flash") is None
```

- [ ] **Step 2: Run them and confirm they fail**

Run: `python -m pytest tests/test_analyze.py -k video -v`
Expected: FAIL, `AttributeError: module 'src.analyze' has no attribute 'analyze_video'`

- [ ] **Step 3: Append to `src/analyze.py`**

Add these imports at the top of the file, alongside the existing ones:

```python
import requests
from google import genai
from google.genai import types as genai_types
```

Add this constant next to `TEXT_REQUIRED_KEYS`:

```python
VIDEO_REQUIRED_KEYS = {
    "core_concept", "target_audience", "hook_analysis",
    "content_structure", "visual_style", "recreation_framework",
}
VIDEO_MAX_BYTES = 20 * 1024 * 1024  # inline upload ceiling
```

Add this function at the end of the file:

```python
def analyze_video(api_key: str, video_url, model: str):
    """Tier 2 recreation blueprint from the actual video. None on any failure.

    Claude cannot take video input, so Gemini handles this one job.
    """
    if not video_url:
        return None

    try:
        resp = requests.get(video_url, timeout=120)
        resp.raise_for_status()
        video_bytes = resp.content
    except Exception as exc:
        logger.error("video download failed for %s: %s", video_url, exc)
        return None

    if len(video_bytes) > VIDEO_MAX_BYTES:
        logger.warning("video too large (%d bytes), skipping: %s",
                       len(video_bytes), video_url)
        return None

    prompt = load_prompt("analyze_video")
    try:
        client = genai.Client(api_key=api_key)
        result = client.models.generate_content(
            model=model,
            contents=[
                genai_types.Part.from_bytes(data=video_bytes, mime_type="video/mp4"),
                prompt,
            ],
        )
        data = extract_json(result.text)
    except Exception as exc:
        logger.error("gemini video analysis failed for %s: %s", video_url, exc)
        return None

    if data and VIDEO_REQUIRED_KEYS <= set(data):
        return data
    logger.warning("incomplete blueprint for %s", video_url)
    return None
```

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `python -m pytest tests/test_analyze.py -v`
Expected: 12 passed

- [ ] **Step 5: Commit**

```bash
git add src/analyze.py tests/test_analyze.py
git commit -m "feat: add gemini video-tier recreation blueprint analysis"
```

---

### Task 6: Pattern detection across 7/30/90-day windows

Claude is never asked "what trends do you see today". It receives the accumulated analyses across three windows and clusters the `reusable_pattern` fields into named recurring formats with movement.

**Files:**
- Create: `prompts/patterns.md`, `src/patterns.py`
- Modify: `src/db.py` (add `save_analysis`, `get_analyses_since`, `save_pattern`, `get_patterns`)
- Test: `tests/test_patterns.py`

**Interfaces:**
- Consumes: `src.analyze.extract_json` (Task 4), `src.db.connect` (Task 1).
- Produces:
  - `src.db.save_analysis(conn, post_id: int, tier: str, payload: dict, ai_virality_score: float | None, model: str) -> int`
  - `src.db.get_analyses_since(conn, days: int) -> list[sqlite3.Row]` — joins `posts`, returns rows with `json`, `tier`, `shortcode`, `posted_at`
  - `src.db.save_pattern(conn, pattern: dict) -> int`
  - `src.db.get_patterns(conn, limit: int = 20) -> list[sqlite3.Row]` — ordered by `occurrences_7d` descending
  - `src.patterns.detect_patterns(client, windows: dict, model: str) -> list[dict]` — `windows` is `{"7": [...], "30": [...], "90": [...]}` of analysis dicts; returns pattern dicts with keys `pattern`, `description`, `occurrences_7d`, `occurrences_30d`, `occurrences_90d`, `avg_performance`, `trend_direction`, `dtw_relevance`

- [ ] **Step 1: Write `prompts/patterns.md`**

```markdown
You are a content strategist tracking format trends for {brand_name}.

Below are structured analyses of high-performing posts across three time windows.
Each analysis contains a "reusable_pattern" field describing an abstracted format.

Last 7 days:
{window_7}

Last 30 days:
{window_30}

Last 90 days:
{window_90}

Cluster these into named recurring content patterns. A pattern is a repeatable
format, not a topic — "Service-industry confessionals" not "wine".

For each pattern give: a short name, a one-sentence description, how many posts in
each window match it, the average performance_score of its matching posts, a
trend_direction of "rising" / "flat" / "falling" based on 7-day count versus the
prior 7 days implied by the 30-day window, and dtw_relevance 0-100 for how well the
pattern suits {brand_name}.

Return at most 12 patterns, most significant first.

Respond with ONLY a JSON array, no prose and no markdown fence:

[
  {{"pattern": "", "description": "", "occurrences_7d": 0, "occurrences_30d": 0,
    "occurrences_90d": 0, "avg_performance": 0, "trend_direction": "rising",
    "dtw_relevance": 0}}
]
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_patterns.py`:

```python
import json

import pytest

from src import db, patterns


@pytest.fixture()
def conn(tmp_path):
    c = db.connect(str(tmp_path / "t.db"))
    db.init_schema(c)
    yield c
    c.close()


def fake_response(text):
    class Block:
        def __init__(self, t):
            self.text = t
    class Msg:
        def __init__(self, t):
            self.content = [Block(t)]
    return Msg(text)


PATTERNS = [
    {"pattern": "Service-industry confessionals",
     "description": "Insider admits something about the job",
     "occurrences_7d": 18, "occurrences_30d": 40, "occurrences_90d": 95,
     "avg_performance": 88.2, "trend_direction": "rising", "dtw_relevance": 92},
]


def test_save_and_read_analysis(conn):
    account_id = db.upsert_account(conn, "wineexample")
    post_id = db.upsert_post(conn, {
        "shortcode": "A1", "account_id": account_id,
        "posted_at": "2026-09-06T10:00:00+00:00",
    })
    db.save_analysis(conn, post_id, "text", {"reusable_pattern": "x"}, 89.0,
                     "claude-sonnet-5")
    rows = db.get_analyses_since(conn, days=7)
    assert len(rows) == 1
    assert json.loads(rows[0]["json"])["reusable_pattern"] == "x"
    assert rows[0]["shortcode"] == "A1"


def test_save_analysis_is_idempotent_per_tier(conn):
    account_id = db.upsert_account(conn, "wineexample")
    post_id = db.upsert_post(conn, {"shortcode": "A1", "account_id": account_id,
                                    "posted_at": "2026-09-06T10:00:00+00:00"})
    db.save_analysis(conn, post_id, "text", {"a": 1}, 50.0, "m")
    db.save_analysis(conn, post_id, "text", {"a": 2}, 60.0, "m")
    rows = conn.execute("SELECT json FROM analyses").fetchall()
    assert len(rows) == 1
    assert json.loads(rows[0]["json"])["a"] == 2


def test_get_analyses_since_excludes_old_posts(conn):
    account_id = db.upsert_account(conn, "wineexample")
    old = db.upsert_post(conn, {"shortcode": "OLD", "account_id": account_id,
                                "posted_at": "2020-01-01T00:00:00+00:00"})
    db.save_analysis(conn, old, "text", {"a": 1}, 10.0, "m")
    assert db.get_analyses_since(conn, days=7) == []


def test_save_pattern_upserts_on_name(conn):
    db.save_pattern(conn, {**PATTERNS[0], "occurrences_7d": 3})
    db.save_pattern(conn, PATTERNS[0])
    rows = db.get_patterns(conn)
    assert len(rows) == 1
    assert rows[0]["occurrences_7d"] == 18


def test_detect_patterns_parses_array(mocker):
    client = mocker.Mock()
    client.messages.create.return_value = fake_response(json.dumps(PATTERNS))
    out = patterns.detect_patterns(
        client, {"7": [{"reusable_pattern": "x"}], "30": [], "90": []},
        "claude-opus-5", brand_name="Drink Toilet Wine")
    assert out[0]["pattern"] == "Service-industry confessionals"
    assert out[0]["trend_direction"] == "rising"


def test_detect_patterns_returns_empty_with_no_analyses(mocker):
    client = mocker.Mock()
    out = patterns.detect_patterns(client, {"7": [], "30": [], "90": []},
                                   "claude-opus-5", brand_name="D")
    assert out == []
    client.messages.create.assert_not_called()


def test_detect_patterns_survives_bad_response(mocker):
    client = mocker.Mock()
    client.messages.create.return_value = fake_response("sorry")
    out = patterns.detect_patterns(client, {"7": [{"reusable_pattern": "x"}],
                                            "30": [], "90": []},
                                   "claude-opus-5", brand_name="D")
    assert out == []
```

- [ ] **Step 3: Run them and confirm they fail**

Run: `python -m pytest tests/test_patterns.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'src.patterns'`

- [ ] **Step 4: Append the new functions to `src/db.py`**

```python
def save_analysis(conn, post_id: int, tier: str, payload: dict,
                  ai_virality_score, model: str) -> int:
    """Store one AI analysis. One row per (post, tier); re-running replaces it."""
    import json as _json
    conn.execute(
        """
        INSERT INTO analyses (post_id, tier, json, ai_virality_score, model, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(post_id, tier) DO UPDATE SET
            json = excluded.json,
            ai_virality_score = excluded.ai_virality_score,
            model = excluded.model,
            created_at = excluded.created_at
        """,
        (post_id, tier, _json.dumps(payload), ai_virality_score, model, _now()),
    )
    conn.commit()
    row = conn.execute(
        "SELECT id FROM analyses WHERE post_id = ? AND tier = ?", (post_id, tier)
    ).fetchone()
    return row["id"]


def get_analyses_since(conn, days: int) -> list:
    """Analyses for posts published within the last N days."""
    from datetime import timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    return conn.execute(
        """
        SELECT a.*, p.shortcode, p.posted_at, p.url, p.caption
        FROM analyses a
        JOIN posts p ON p.id = a.post_id
        WHERE p.posted_at >= ?
        ORDER BY p.posted_at DESC
        """,
        (cutoff,),
    ).fetchall()


def save_pattern(conn, pattern: dict) -> int:
    """Upsert a pattern keyed on its name."""
    conn.execute(
        """
        INSERT INTO patterns (pattern, description, first_seen, last_seen,
                              occurrences_7d, occurrences_30d, occurrences_90d,
                              avg_performance, trend_direction, dtw_relevance)
        VALUES (:pattern, :description, :now, :now, :occurrences_7d,
                :occurrences_30d, :occurrences_90d, :avg_performance,
                :trend_direction, :dtw_relevance)
        ON CONFLICT(pattern) DO UPDATE SET
            description     = excluded.description,
            last_seen       = excluded.last_seen,
            occurrences_7d  = excluded.occurrences_7d,
            occurrences_30d = excluded.occurrences_30d,
            occurrences_90d = excluded.occurrences_90d,
            avg_performance = excluded.avg_performance,
            trend_direction = excluded.trend_direction,
            dtw_relevance   = excluded.dtw_relevance
        """,
        {**{"description": None, "occurrences_7d": 0, "occurrences_30d": 0,
            "occurrences_90d": 0, "avg_performance": None,
            "trend_direction": None, "dtw_relevance": None},
         **pattern, "now": _now()},
    )
    conn.commit()
    row = conn.execute("SELECT id FROM patterns WHERE pattern = ?",
                       (pattern["pattern"],)).fetchone()
    return row["id"]


def get_patterns(conn, limit: int = 20) -> list:
    return conn.execute(
        "SELECT * FROM patterns ORDER BY occurrences_7d DESC, dtw_relevance DESC LIMIT ?",
        (limit,),
    ).fetchall()
```

- [ ] **Step 5: Write `src/patterns.py`**

```python
"""Cluster stored analyses into named recurring content formats."""

import json
import logging

from src.analyze import extract_json, load_prompt

logger = logging.getLogger(__name__)

MAX_PATTERNS = 12


def _summarise(analyses: list) -> list:
    """Trim analyses to the fields the clustering prompt actually needs."""
    out = []
    for a in analyses:
        out.append({
            "reusable_pattern": a.get("reusable_pattern"),
            "hook_type": a.get("hook_type"),
            "audience": a.get("audience"),
            "ai_virality_score": a.get("ai_virality_score"),
            "performance_score": a.get("performance_score"),
        })
    return out


def detect_patterns(client, windows: dict, model: str, brand_name: str) -> list:
    """Cluster the 7/30/90-day analyses into patterns. [] on failure or no data."""
    if not any(windows.get(k) for k in ("7", "30", "90")):
        logger.info("no analyses to cluster")
        return []

    prompt = load_prompt("patterns").format(
        brand_name=brand_name,
        window_7=json.dumps(_summarise(windows.get("7", [])), indent=1),
        window_30=json.dumps(_summarise(windows.get("30", [])), indent=1),
        window_90=json.dumps(_summarise(windows.get("90", [])), indent=1),
    )

    try:
        resp = client.messages.create(
            model=model, max_tokens=4000,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = "".join(b.text for b in resp.content if hasattr(b, "text"))
    except Exception as exc:
        logger.error("pattern detection failed: %s", exc)
        return []

    data = extract_json(raw)
    if data is None:
        start, end = raw.find("["), raw.rfind("]")
        if start != -1 and end != -1:
            try:
                data = json.loads(raw[start:end + 1])
            except json.JSONDecodeError:
                data = None
    if not isinstance(data, list):
        logger.warning("pattern detection returned no usable array")
        return []

    return [p for p in data if p.get("pattern")][:MAX_PATTERNS]
```

- [ ] **Step 6: Run the tests and confirm they pass**

Run: `python -m pytest tests/test_patterns.py -v`
Expected: 7 passed

- [ ] **Step 7: Commit**

```bash
git add prompts/patterns.md src/patterns.py src/db.py tests/test_patterns.py
git commit -m "feat: add pattern clustering across 7/30/90-day windows"
```

---

### Task 7: Idea generation with similarity rejection

Ten briefs a day. `similarity_risk: HIGH` is rejected before it ever reaches the report — that is the line between abstracting a format and copying a post.

**Files:**
- Create: `prompts/ideas.md`, `src/ideas.py`
- Modify: `src/db.py` (add `save_idea`, `get_recent_ideas`, `get_idea`, `mark_idea_posted`)
- Test: `tests/test_ideas.py`

**Interfaces:**
- Consumes: `src.analyze.load_prompt` and `extract_json` (Task 4), `src.db` (Task 1).
- Produces:
  - `src.db.save_idea(conn, brief: dict, source_pattern_id: int | None, similarity_risk: str, confidence: float | None) -> int`
  - `src.db.get_recent_ideas(conn, limit: int = 20) -> list[sqlite3.Row]`
  - `src.db.get_idea(conn, idea_id: int) -> sqlite3.Row | None`
  - `src.db.mark_idea_posted(conn, idea_id: int, shortcode: str) -> None`
  - `src.ideas.generate_ideas(client, context: dict, model: str, count: int) -> list[dict]` — `context` has keys `brand`, `top_posts`, `patterns`, `previous_ideas`, `our_results`
  - Brief keys, relied on by Tasks 9 and 12: `concept`, `why_now`, `source_pattern`, `hook`, `opening_frame`, `script`, `on_screen_text`, `shot_list`, `caption`, `cta`, `format`, `difficulty`, `confidence`, `similarity_risk`

- [ ] **Step 1: Write `prompts/ideas.md`**

```markdown
You are the content strategist for {brand_name}.
Brand voice: {brand_voice}

Generate {count} original short-form content ideas.

Today's top-performing posts in the niche:
{top_posts}

Recurring patterns detected across recent weeks:
{patterns}

Ideas already generated recently — do not repeat these:
{previous_ideas}

How our own published posts actually performed:
{our_results}

Rules:
- Build on the abstracted PATTERNS, never on one specific competitor post.
- If an idea would be recognisably the same video as a single source post, mark its
  similarity_risk HIGH. Prefer ideas that are LOW.
- Weight toward patterns and formats that our own results show working for us.
- Write in the brand voice. No corporate tone, no wine education lectures.

For each idea give: concept, why_now, source_pattern (the pattern name it builds on),
hook (the spoken or written first line), opening_frame (what is on screen at 0:00),
script (the full spoken script), on_screen_text, shot_list (list of shots), caption,
cta, format (Reel / carousel / static), difficulty (easy / medium / hard),
confidence 0-100, and similarity_risk (LOW / MEDIUM / HIGH).

Respond with ONLY a JSON array, no prose and no markdown fence:

[
  {{"concept": "", "why_now": "", "source_pattern": "", "hook": "",
    "opening_frame": "", "script": "", "on_screen_text": "", "shot_list": [],
    "caption": "", "cta": "", "format": "Reel", "difficulty": "easy",
    "confidence": 0, "similarity_risk": "LOW"}}
]
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_ideas.py`:

```python
import json

import pytest

from src import db, ideas


@pytest.fixture()
def conn(tmp_path):
    c = db.connect(str(tmp_path / "t.db"))
    db.init_schema(c)
    yield c
    c.close()


def fake_response(text):
    class Block:
        def __init__(self, t):
            self.text = t
    class Msg:
        def __init__(self, t):
            self.content = [Block(t)]
    return Msg(text)


def brief(concept, risk="LOW", confidence=80):
    return {
        "concept": concept, "why_now": "pattern rising", "source_pattern": "P",
        "hook": "POV: ...", "opening_frame": "close on glass", "script": "...",
        "on_screen_text": "...", "shot_list": ["a", "b"], "caption": "c",
        "cta": "tag a coworker", "format": "Reel", "difficulty": "easy",
        "confidence": confidence, "similarity_risk": risk,
    }


CONTEXT = {
    "brand": {"name": "Drink Toilet Wine", "voice": "irreverent"},
    "top_posts": [], "patterns": [], "previous_ideas": [], "our_results": [],
}


def test_generate_ideas_returns_parsed_briefs(mocker):
    client = mocker.Mock()
    client.messages.create.return_value = fake_response(
        json.dumps([brief("The Sommelier Is Watching")])
    )
    out = ideas.generate_ideas(client, CONTEXT, "claude-opus-5", count=10)
    assert out[0]["concept"] == "The Sommelier Is Watching"


def test_high_similarity_ideas_are_rejected(mocker):
    client = mocker.Mock()
    client.messages.create.return_value = fake_response(json.dumps([
        brief("safe one", risk="LOW"),
        brief("too close to a real post", risk="HIGH"),
        brief("borderline", risk="MEDIUM"),
    ]))
    out = ideas.generate_ideas(client, CONTEXT, "claude-opus-5", count=10)
    concepts = [i["concept"] for i in out]
    assert "too close to a real post" not in concepts
    assert concepts == ["safe one", "borderline"]


def test_generate_ideas_truncates_to_count(mocker):
    client = mocker.Mock()
    client.messages.create.return_value = fake_response(
        json.dumps([brief(f"idea {i}") for i in range(20)])
    )
    out = ideas.generate_ideas(client, CONTEXT, "claude-opus-5", count=10)
    assert len(out) == 10


def test_generate_ideas_survives_api_failure(mocker):
    client = mocker.Mock()
    client.messages.create.side_effect = Exception("overloaded")
    assert ideas.generate_ideas(client, CONTEXT, "claude-opus-5", count=10) == []


def test_save_and_get_idea_roundtrip(conn):
    idea_id = db.save_idea(conn, brief("x"), None, "LOW", 80.0)
    row = db.get_idea(conn, idea_id)
    assert json.loads(row["brief_json"])["concept"] == "x"
    assert row["status"] == "new"


def test_mark_idea_posted(conn):
    idea_id = db.save_idea(conn, brief("x"), None, "LOW", 80.0)
    db.mark_idea_posted(conn, idea_id, "SHORT1")
    row = db.get_idea(conn, idea_id)
    assert row["status"] == "posted"
    assert row["posted_shortcode"] == "SHORT1"


def test_get_recent_ideas_newest_first(conn):
    a = db.save_idea(conn, brief("first"), None, "LOW", 50.0)
    b = db.save_idea(conn, brief("second"), None, "LOW", 50.0)
    rows = db.get_recent_ideas(conn, limit=5)
    assert [r["id"] for r in rows] == [b, a]
```

- [ ] **Step 3: Run them and confirm they fail**

Run: `python -m pytest tests/test_ideas.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'src.ideas'`

- [ ] **Step 4: Append to `src/db.py`**

```python
def save_idea(conn, brief: dict, source_pattern_id, similarity_risk: str,
              confidence) -> int:
    import json as _json
    cur = conn.execute(
        """
        INSERT INTO ideas (created_at, brief_json, source_pattern_id,
                           similarity_risk, confidence, status)
        VALUES (?, ?, ?, ?, ?, 'new')
        """,
        (_now(), _json.dumps(brief), source_pattern_id, similarity_risk, confidence),
    )
    conn.commit()
    return cur.lastrowid


def get_recent_ideas(conn, limit: int = 20) -> list:
    return conn.execute(
        "SELECT * FROM ideas ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()


def get_idea(conn, idea_id: int):
    return conn.execute("SELECT * FROM ideas WHERE id = ?", (idea_id,)).fetchone()


def mark_idea_posted(conn, idea_id: int, shortcode: str) -> None:
    conn.execute(
        "UPDATE ideas SET status = 'posted', posted_shortcode = ?, posted_at = ? WHERE id = ?",
        (shortcode, _now(), idea_id),
    )
    conn.commit()
```

- [ ] **Step 5: Write `src/ideas.py`**

```python
"""Generate original content briefs from patterns, top posts, and our own results."""

import json
import logging

from src.analyze import extract_json, load_prompt

logger = logging.getLogger(__name__)

REQUIRED_KEYS = {"concept", "hook", "script", "caption", "similarity_risk"}


def generate_ideas(client, context: dict, model: str, count: int) -> list:
    """Return up to `count` briefs. HIGH similarity_risk ideas are dropped."""
    brand = context.get("brand", {})
    prompt = load_prompt("ideas").format(
        brand_name=brand.get("name", ""),
        brand_voice=brand.get("voice", ""),
        count=count,
        top_posts=json.dumps(context.get("top_posts", []), indent=1, default=str),
        patterns=json.dumps(context.get("patterns", []), indent=1, default=str),
        previous_ideas=json.dumps(context.get("previous_ideas", []), indent=1, default=str),
        our_results=json.dumps(context.get("our_results", []), indent=1, default=str),
    )

    try:
        resp = client.messages.create(
            model=model, max_tokens=8000,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = "".join(b.text for b in resp.content if hasattr(b, "text"))
    except Exception as exc:
        logger.error("idea generation failed: %s", exc)
        return []

    data = extract_json(raw)
    if data is None:
        start, end = raw.find("["), raw.rfind("]")
        if start != -1 and end != -1:
            try:
                data = json.loads(raw[start:end + 1])
            except json.JSONDecodeError:
                data = None
    if not isinstance(data, list):
        logger.warning("idea generation returned no usable array")
        return []

    kept = []
    for item in data:
        if not isinstance(item, dict) or not REQUIRED_KEYS <= set(item):
            continue
        if str(item.get("similarity_risk", "")).upper() == "HIGH":
            logger.info("rejected idea for HIGH similarity risk: %s",
                        item.get("concept"))
            continue
        kept.append(item)

    return kept[:count]
```

- [ ] **Step 6: Run the tests and confirm they pass**

Run: `python -m pytest tests/test_ideas.py -v`
Expected: 7 passed

- [ ] **Step 7: Commit**

```bash
git add prompts/ideas.md src/ideas.py src/db.py tests/test_ideas.py
git commit -m "feat: add idea generation with similarity-risk rejection"
```

---

### Task 8: HTML report and optional email

A standalone file you open every morning. Autoescape on — captions are attacker-influenced text from the public internet and go straight into HTML.

**Files:**
- Create: `src/report.py`, `src/templates/report.html`
- Test: `tests/test_report.py`

**Interfaces:**
- Consumes: outputs of Tasks 3, 6, 7.
- Produces:
  - `src.report.render_report(context: dict, output_path: str) -> None` — `context` keys: `report_date`, `brand`, `stats`, `fastest_rising`, `top_posts`, `patterns`, `ideas`, `our_results`, `repo_url`
  - `src.report.send_email(html: str, subject: str, cfg: dict) -> bool` — returns `False` on any failure and never raises

- [ ] **Step 1: Write the failing tests**

Create `tests/test_report.py`:

```python
from pathlib import Path

from src import report


CONTEXT = {
    "report_date": "2026-09-07",
    "brand": {"name": "Drink Toilet Wine", "instagram": "drinktoiletwine"},
    "stats": {"accounts": 67, "posts": 184, "text_analyzed": 40, "video_analyzed": 15},
    "fastest_rising": {
        "username": "wineexample", "url": "https://instagram.com/p/A",
        "views": 487000, "owner_followers": 82000, "views_per_follower": 5.9,
        "final_score": 96.0, "accelerating": True,
        "analysis": {"why_it_overperformed": ["a", "b", "c"],
                     "reusable_pattern": "Insider frustration + setup + reaction"},
    },
    "top_posts": [
        {"username": "wineexample", "url": "https://instagram.com/p/A",
         "caption": "wine", "views": 487000, "likes": 61200, "comments": 3140,
         "final_score": 96.0, "accelerating": True,
         "analysis": {"hook": "POV", "reusable_pattern": "X"}},
    ],
    "patterns": [
        {"pattern": "Service-industry confessionals", "occurrences_7d": 18,
         "occurrences_30d": 40, "trend_direction": "rising", "dtw_relevance": 92},
    ],
    "ideas": [
        {"id": 1, "concept": "The Sommelier Is Watching",
         "hook": "POV: you told the sommelier you actually like $12 wine",
         "script": "...", "caption": "...", "cta": "tag someone",
         "format": "Reel", "difficulty": "easy", "confidence": 88,
         "similarity_risk": "LOW", "shot_list": ["a", "b"]},
    ],
    "our_results": [
        {"shortcode": "OURS1", "views": 12000, "baseline_views": 4000,
         "vs_baseline": 3.0},
    ],
    "repo_url": "https://github.com/xyzQ2/igtt",
}


def test_render_report_writes_file(tmp_path):
    out = tmp_path / "latest.html"
    report.render_report(CONTEXT, str(out))
    html = out.read_text()
    assert "Drink Toilet Wine" in html
    assert "Service-industry confessionals" in html
    assert "The Sommelier Is Watching" in html
    assert "wineexample" in html


def test_render_report_escapes_captions(tmp_path):
    ctx = dict(CONTEXT)
    ctx["top_posts"] = [{**CONTEXT["top_posts"][0],
                         "caption": "<script>alert(1)</script>"}]
    out = tmp_path / "latest.html"
    report.render_report(ctx, str(out))
    html = out.read_text()
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_render_report_includes_idea_id_for_dispatch(tmp_path):
    out = tmp_path / "latest.html"
    report.render_report(CONTEXT, str(out))
    html = out.read_text()
    assert "idea_id" in html or "#1" in html
    assert "actions/workflows/post.yml" in html


def test_send_email_returns_false_when_disabled():
    assert report.send_email("<p>hi</p>", "subject", {"enabled": False}) is False


def test_send_email_returns_false_on_smtp_failure(mocker):
    mocker.patch("src.report.smtplib.SMTP", side_effect=Exception("no route"))
    cfg = {"enabled": True, "host": "h", "port": 587, "user": "u",
           "password": "p", "to": "t@example.com"}
    assert report.send_email("<p>hi</p>", "subject", cfg) is False


def test_send_email_sends_when_configured(mocker):
    smtp = mocker.patch("src.report.smtplib.SMTP")
    cfg = {"enabled": True, "host": "h", "port": 587, "user": "u",
           "password": "p", "to": "t@example.com"}
    assert report.send_email("<p>hi</p>", "subject", cfg) is True
    smtp.return_value.__enter__.return_value.send_message.assert_called_once()
```

- [ ] **Step 2: Run them and confirm they fail**

Run: `python -m pytest tests/test_report.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'src.report'`

- [ ] **Step 3: Write `src/templates/report.html`**

```html
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{{ brand.name }} Intelligence — {{ report_date }}</title>
<style>
  body { font: 15px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
         max-width: 820px; margin: 0 auto; padding: 24px; color: #1a1a1a; }
  h1 { font-size: 26px; margin-bottom: 4px; }
  h2 { margin-top: 36px; border-bottom: 2px solid #eee; padding-bottom: 6px; }
  .stats { color: #666; font-size: 14px; }
  .card { border: 1px solid #e4e4e4; border-radius: 8px; padding: 14px 16px;
          margin: 12px 0; }
  .hot { border-color: #c0392b; background: #fdf6f5; }
  .metrics { color: #555; font-size: 13px; }
  .pattern { display: flex; justify-content: space-between; }
  .rising::after { content: " ↑"; color: #27ae60; }
  .falling::after { content: " ↓"; color: #c0392b; }
  .risk-LOW { color: #27ae60; } .risk-MEDIUM { color: #d68910; }
  pre { white-space: pre-wrap; background: #fafafa; padding: 10px; border-radius: 6px; }
  a { color: #1a5fb4; }
</style>
</head>
<body>

<h1>🍷 {{ brand.name }} Intelligence — {{ report_date }}</h1>
<p class="stats">
  Accounts monitored: {{ stats.accounts }} ·
  New posts collected: {{ stats.posts }} ·
  Text-analyzed: {{ stats.text_analyzed }} ·
  Video-analyzed: {{ stats.video_analyzed }}
</p>

{% if fastest_rising %}
<h2>🚀 Fastest-rising post</h2>
<div class="card hot">
  <strong>@{{ fastest_rising.username }}</strong>
  <a href="{{ fastest_rising.url }}">view</a>
  <p class="metrics">
    Views: {{ "{:,}".format(fastest_rising.views or 0) }} ·
    Followers: {{ "{:,}".format(fastest_rising.owner_followers or 0) }} ·
    Views/follower: {{ "%.1f"|format(fastest_rising.views_per_follower or 0) }}× ·
    Score: {{ "%.0f"|format(fastest_rising.final_score or 0) }}
    {% if fastest_rising.accelerating %} · <strong>accelerating</strong>{% endif %}
  </p>
  {% if fastest_rising.analysis %}
    <p><strong>Why it's working</strong></p>
    <ul>{% for r in fastest_rising.analysis.why_it_overperformed %}<li>{{ r }}</li>{% endfor %}</ul>
    <p><strong>Reusable formula:</strong> {{ fastest_rising.analysis.reusable_pattern }}</p>
  {% endif %}
</div>
{% endif %}

<h2>🏆 Top {{ top_posts|length }}</h2>
{% for p in top_posts %}
<div class="card">
  <strong>{{ loop.index }}. @{{ p.username }}</strong>
  <a href="{{ p.url }}">view</a>
  {% if p.accelerating %} · <strong>accelerating</strong>{% endif %}
  <p class="metrics">
    Score {{ "%.0f"|format(p.final_score or 0) }} ·
    {{ "{:,}".format(p.views or 0) }} views ·
    {{ "{:,}".format(p.likes or 0) }} likes ·
    {{ "{:,}".format(p.comments or 0) }} comments
  </p>
  <p>{{ p.caption }}</p>
  {% if p.analysis %}
    <p class="metrics"><strong>Hook:</strong> {{ p.analysis.hook }}<br>
    <strong>Pattern:</strong> {{ p.analysis.reusable_pattern }}</p>
  {% endif %}
</div>
{% endfor %}

<h2>📈 Emerging patterns</h2>
{% for pat in patterns %}
<div class="card">
  <div class="pattern">
    <strong class="{{ pat.trend_direction }}">{{ pat.pattern }}</strong>
    <span class="metrics">{{ pat.occurrences_7d }} this week / {{ pat.occurrences_30d }} in 30d</span>
  </div>
  <p class="metrics">DTW relevance: {{ pat.dtw_relevance }}</p>
</div>
{% endfor %}

{% if our_results %}
<h2>📊 How ours did</h2>
{% for r in our_results %}
<div class="card">
  <strong>{{ r.shortcode }}</strong>
  <p class="metrics">
    {{ "{:,}".format(r.views or 0) }} views vs {{ "{:,}".format(r.baseline_views or 0) }} baseline
    ({{ "%.1f"|format(r.vs_baseline or 0) }}× )
  </p>
</div>
{% endfor %}
{% endif %}

<h2>💡 Make these next</h2>
{% for i in ideas %}
<div class="card">
  <strong>#{{ i.id }} — {{ i.concept }}</strong>
  <span class="risk-{{ i.similarity_risk }}">[{{ i.similarity_risk }} similarity]</span>
  <p class="metrics">
    {{ i.format }} · {{ i.difficulty }} · confidence {{ i.confidence }}
  </p>
  <p><strong>Hook:</strong> {{ i.hook }}</p>
  <pre>{{ i.script }}</pre>
  <p><strong>Shots:</strong> {% for s in i.shot_list %}{{ s }}{% if not loop.last %} → {% endif %}{% endfor %}</p>
  <p><strong>Caption:</strong> {{ i.caption }}</p>
  <p><strong>CTA:</strong> {{ i.cta }}</p>
  <p><a href="{{ repo_url }}/actions/workflows/post.yml">Publish this — run the workflow with idea_id {{ i.id }}</a></p>
</div>
{% endfor %}

</body>
</html>
```

- [ ] **Step 4: Write `src/report.py`**

```python
"""Render the daily HTML report and optionally email it."""

import logging
import smtplib
from email.message import EmailMessage
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

logger = logging.getLogger(__name__)

TEMPLATE_DIR = Path(__file__).parent / "templates"


def render_report(context: dict, output_path: str) -> None:
    """Render report.html to output_path. Autoescape is on: captions are hostile input."""
    env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)), autoescape=True)
    html = env.get_template("report.html").render(**context)
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")
    logger.info("report written to %s", path)


def send_email(html: str, subject: str, cfg: dict) -> bool:
    """Send the report. Returns False on any failure — never fails the daily run."""
    if not cfg.get("enabled"):
        logger.info("email disabled, skipping send")
        return False

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = cfg.get("user", "")
    msg["To"] = cfg.get("to", "")
    msg.set_content("HTML report attached inline.")
    msg.add_alternative(html, subtype="html")

    try:
        with smtplib.SMTP(cfg["host"], int(cfg["port"]), timeout=30) as smtp:
            smtp.starttls()
            smtp.login(cfg["user"], cfg["password"])
            smtp.send_message(msg)
        logger.info("report emailed to %s", cfg.get("to"))
        return True
    except Exception as exc:
        logger.error("email send failed (report still on disk): %s", exc)
        return False
```

- [ ] **Step 5: Run the tests and confirm they pass**

Run: `python -m pytest tests/test_report.py -v`
Expected: 6 passed

- [ ] **Step 6: Commit**

```bash
git add src/report.py src/templates/report.html tests/test_report.py
git commit -m "feat: add daily html report and optional smtp delivery"
```

---

### Task 9: `app.py` daily orchestrator, end to end

Wires every stage together. One command performs a whole daily run. Includes the end-to-end fixture test that proves the pipeline holds.

**Files:**
- Create: `app.py`, `tests/test_app.py`
- Modify: `src/db.py` (add `get_posts_for_snapshotting`, `latest_metrics`)

**Interfaces:**
- Consumes: everything from Tasks 1-8.
- Produces:
  - `app.run_daily(config_path: str = "config.yaml", db_path: str | None = None, dry_run: bool = False) -> dict` — returns the stats dict that goes into the report
  - `src.db.get_posts_for_snapshotting(conn, days: int) -> list[sqlite3.Row]`
  - `src.db.latest_metrics(conn, post_id: int) -> dict` — keys `views`, `likes`, `comments`, `shares`, all `int | None`

- [ ] **Step 1: Write the failing end-to-end test**

Create `tests/test_app.py`. Every external boundary is mocked; the pipeline itself is real.

```python
import json
from pathlib import Path

import pytest

import app
from src import db

FIXTURE = Path(__file__).parent / "fixtures" / "apify_instagram.json"


@pytest.fixture()
def cfg_file(tmp_path):
    src = Path("config.yaml").read_text()
    p = tmp_path / "config.yaml"
    p.write_text(src)
    return str(p)


def fake_claude_response(text):
    class Block:
        def __init__(self, t):
            self.text = t
    class Msg:
        def __init__(self, t):
            self.content = [Block(t)]
    return Msg(text)


ANALYSIS = {
    "hook": "POV", "hook_type": "relatability", "payoff": "p",
    "emotional_driver": "e", "humor_mechanism": "h", "social_driver": "s",
    "comment_driver": "c", "rewatch_driver": "r", "visual_structure": "v",
    "caption_role": "cr", "audience": "a", "timing": "t",
    "why_it_overperformed": ["1", "2", "3"], "reusable_pattern": "P",
    "scores": {"hook": 90, "shareability": 80, "originality": 70,
               "relatability": 90, "rewatchability": 80, "cultural_relevance": 60},
    "ai_virality_score": 88,
}
PATTERNS = [{"pattern": "P", "description": "d", "occurrences_7d": 3,
             "occurrences_30d": 5, "occurrences_90d": 9, "avg_performance": 80,
             "trend_direction": "rising", "dtw_relevance": 90}]
IDEAS = [{"concept": "idea one", "why_now": "w", "source_pattern": "P",
          "hook": "h", "opening_frame": "o", "script": "s", "on_screen_text": "t",
          "shot_list": ["a"], "caption": "c", "cta": "cta", "format": "Reel",
          "difficulty": "easy", "confidence": 85, "similarity_risk": "LOW"}]


def test_daily_run_end_to_end(tmp_path, cfg_file, mocker, monkeypatch):
    monkeypatch.setenv("APIFY_TOKEN", "t")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "t")
    monkeypatch.setenv("GEMINI_API_KEY", "t")

    db_path = str(tmp_path / "test.db")
    conn = db.connect(db_path)
    db.init_schema(conn)
    db.upsert_account(conn, "wineexample", category="wine", followers=82000)
    conn.close()

    # Apify returns the fixture
    mocker.patch("app.apify.fetch_profile_posts",
                 return_value=[p for p in
                               (__import__("src.apify", fromlist=["x"]).normalize_post(i)
                                for i in json.loads(FIXTURE.read_text())) if p])

    # Claude answers analysis, patterns, then ideas in that order
    claude = mocker.Mock()
    claude.messages.create.side_effect = [
        fake_claude_response(json.dumps(ANALYSIS)),
        fake_claude_response(json.dumps(ANALYSIS)),
        fake_claude_response(json.dumps(PATTERNS)),
        fake_claude_response(json.dumps(IDEAS)),
    ]
    mocker.patch("app.Anthropic", return_value=claude)

    # Gemini video tier
    mocker.patch("app.analyze.analyze_video", return_value=None)

    report_path = tmp_path / "latest.html"
    stats = app.run_daily(config_path=cfg_file, db_path=db_path,
                          report_path=str(report_path))

    assert stats["posts"] == 2
    assert report_path.exists()
    html = report_path.read_text()
    assert "idea one" in html

    conn = db.connect(db_path)
    assert len(db.get_recent_ideas(conn)) == 1
    assert len(conn.execute("SELECT * FROM post_snapshots").fetchall()) == 2
    conn.close()


def test_daily_run_survives_total_apify_failure(tmp_path, cfg_file, mocker, monkeypatch):
    monkeypatch.setenv("APIFY_TOKEN", "t")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "t")
    db_path = str(tmp_path / "test.db")
    conn = db.connect(db_path)
    db.init_schema(conn)
    db.upsert_account(conn, "wineexample", followers=1000)
    conn.close()

    mocker.patch("app.apify.fetch_profile_posts", return_value=[])
    mocker.patch("app.Anthropic", return_value=mocker.Mock())
    report_path = tmp_path / "latest.html"

    stats = app.run_daily(config_path=cfg_file, db_path=db_path,
                          report_path=str(report_path))
    assert stats["posts"] == 0
    assert report_path.exists(), "an empty day still produces a report"


def test_ai_limits_are_enforced(tmp_path, cfg_file, mocker, monkeypatch):
    """40 text analyses max, regardless of how many posts came back."""
    monkeypatch.setenv("APIFY_TOKEN", "t")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "t")
    db_path = str(tmp_path / "test.db")
    conn = db.connect(db_path)
    db.init_schema(conn)
    db.upsert_account(conn, "wineexample", followers=1000)
    conn.close()

    many = [{
        "platform": "instagram", "shortcode": f"S{i}", "username": "wineexample",
        "owner_followers": 1000, "url": "u", "video_url": None,
        "thumbnail_url": None, "caption": "c", "content_type": "Video",
        "posted_at": "2026-09-06T10:00:00+00:00", "duration_sec": 10.0,
        "views": 1000 + i, "likes": 10, "comments": 1, "shares": None,
    } for i in range(100)]
    mocker.patch("app.apify.fetch_profile_posts", return_value=many)
    mocker.patch("app.analyze.analyze_text", return_value=ANALYSIS)
    mocker.patch("app.analyze.analyze_video", return_value=None)
    mocker.patch("app.patterns.detect_patterns", return_value=[])
    mocker.patch("app.ideas.generate_ideas", return_value=[])
    mocker.patch("app.Anthropic", return_value=mocker.Mock())

    stats = app.run_daily(config_path=cfg_file, db_path=db_path,
                          report_path=str(tmp_path / "r.html"))
    assert stats["text_analyzed"] == 40
```

- [ ] **Step 2: Run them and confirm they fail**

Run: `python -m pytest tests/test_app.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'app'`

- [ ] **Step 3: Append the two helpers to `src/db.py`**

```python
def get_posts_for_snapshotting(conn, days: int) -> list:
    """Posts published within the window — these get re-measured each run."""
    from datetime import timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    return conn.execute(
        "SELECT * FROM posts WHERE posted_at >= ? ORDER BY posted_at DESC",
        (cutoff,),
    ).fetchall()


def latest_metrics(conn, post_id: int) -> dict:
    """Most recent snapshot for a post, or all-None if it has never been measured."""
    row = conn.execute(
        """
        SELECT views, likes, comments, shares FROM post_snapshots
        WHERE post_id = ? ORDER BY captured_at DESC LIMIT 1
        """,
        (post_id,),
    ).fetchone()
    if row is None:
        return {"views": None, "likes": None, "comments": None, "shares": None}
    return dict(row)
```

- [ ] **Step 4: Write `app.py`**

```python
"""Daily run: collect, snapshot, score, analyze, cluster, generate, report."""

import argparse
import json
import logging
import os
import sys
from datetime import date
from pathlib import Path

from anthropic import Anthropic

from src import analyze, apify, db, ideas, patterns, report, score
from src.config import load_config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("app")

REPO_URL = "https://github.com/xyzQ2/igtt"


def run_daily(config_path: str = "config.yaml", db_path: str | None = None,
              report_path: str = "reports/latest.html") -> dict:
    cfg = load_config(config_path)
    mon = cfg["monitoring"]
    conn = db.connect(db_path or "data/intelligence.db")
    db.init_schema(conn)

    stats = {"accounts": 0, "posts": 0, "text_analyzed": 0, "video_analyzed": 0,
             "failures": 0}

    # 1. Collect ---------------------------------------------------------
    accounts = db.get_active_accounts(conn)[: mon["max_accounts"]]
    stats["accounts"] = len(accounts)
    account_id_by_username = {a["username"]: a["id"] for a in accounts}
    followers_by_username = {a["username"]: a["followers"] for a in accounts}

    raw_posts = apify.fetch_profile_posts(
        os.environ.get("APIFY_TOKEN", ""),
        [a["username"] for a in accounts],
        mon["posts_lookback_days"],
        mon["results_per_account"],
    )
    stats["posts"] = len(raw_posts)
    logger.info("collected %d posts from %d accounts", len(raw_posts), len(accounts))

    # 2. Store and snapshot ----------------------------------------------
    posts = []
    for p in raw_posts:
        username = p.get("username")
        account_id = account_id_by_username.get(username)
        if account_id is None:
            account_id = db.upsert_account(conn, username,
                                           followers=p.get("owner_followers"))
            account_id_by_username[username] = account_id
        post_id = db.upsert_post(conn, {
            "platform": p["platform"], "shortcode": p["shortcode"],
            "account_id": account_id, "url": p["url"], "video_url": p["video_url"],
            "thumbnail_url": p["thumbnail_url"], "caption": p["caption"],
            "content_type": p["content_type"], "posted_at": p["posted_at"],
            "duration_sec": p["duration_sec"], "is_ours": 0,
        })
        db.add_snapshot(conn, post_id, p["views"], p["likes"], p["comments"],
                        p["shares"])
        enriched = dict(p)
        enriched["post_id"] = post_id
        enriched["owner_followers"] = (p.get("owner_followers")
                                       or followers_by_username.get(username))
        vel = score.velocity(
            [dict(s) for s in db.get_snapshots(conn, post_id)],
            cfg["scoring"]["acceleration_threshold"],
        )
        enriched.update(vel)
        posts.append(enriched)

    # 3. Rank for free ---------------------------------------------------
    ranked = score.score_posts(posts, cfg["scoring"])

    # 4. Tier 1: text ----------------------------------------------------
    client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))
    text_candidates = ranked[: mon["candidate_posts_for_text_ai"]]
    for post in text_candidates:
        result = analyze.analyze_text(client, post, cfg["brand"],
                                      cfg["models"]["text_analysis"])
        if not result:
            stats["failures"] += 1
            continue
        post["analysis"] = result
        post["ai_virality_score"] = result.get("ai_virality_score")
        db.save_analysis(conn, post["post_id"], "text", result,
                         result.get("ai_virality_score"),
                         cfg["models"]["text_analysis"])
        stats["text_analyzed"] += 1

    for post in ranked:
        post["final_score"] = score.final_score(
            post["performance_score"], post.get("ai_virality_score"),
            cfg["scoring"]["ai_weight"],
        )
    ranked.sort(key=lambda p: p["final_score"], reverse=True)

    # 5. Tier 2: video ---------------------------------------------------
    video_candidates = [p for p in ranked if p.get("video_url")][
        : mon["candidate_posts_for_video_ai"]]
    for post in video_candidates:
        blueprint = analyze.analyze_video(os.environ.get("GEMINI_API_KEY", ""),
                                          post["video_url"], cfg["models"]["video"])
        if not blueprint:
            stats["failures"] += 1
            continue
        post["blueprint"] = blueprint
        db.save_analysis(conn, post["post_id"], "video", blueprint, None,
                         cfg["models"]["video"])
        stats["video_analyzed"] += 1

    # 6. Patterns --------------------------------------------------------
    windows = {
        w: [json.loads(r["json"]) for r in db.get_analyses_since(conn, int(w))
            if r["tier"] == "text"]
        for w in ("7", "30", "90")
    }
    for pat in patterns.detect_patterns(client, windows, cfg["models"]["strategy"],
                                        cfg["brand"]["name"]):
        db.save_pattern(conn, pat)
    stored_patterns = [dict(r) for r in db.get_patterns(conn)]

    # 7. Ideas -----------------------------------------------------------
    top_posts = ranked[: mon["daily_top_posts"]]
    our_results = build_our_results(conn, cfg)
    briefs = ideas.generate_ideas(
        client,
        {
            "brand": cfg["brand"],
            "top_posts": [{k: p.get(k) for k in
                           ("username", "caption", "final_score", "analysis")}
                          for p in top_posts],
            "patterns": stored_patterns,
            "previous_ideas": [json.loads(r["brief_json"])["concept"]
                               for r in db.get_recent_ideas(conn, 20)],
            "our_results": our_results,
        },
        cfg["models"]["strategy"],
        cfg["ideas"]["daily_count"],
    )
    idea_rows = []
    for brief in briefs:
        idea_id = db.save_idea(conn, brief, None, brief.get("similarity_risk"),
                               brief.get("confidence"))
        idea_rows.append({**brief, "id": idea_id})

    # 8. Report ----------------------------------------------------------
    fastest = next((p for p in ranked if p.get("accelerating")),
                   ranked[0] if ranked else None)
    context = {
        "report_date": date.today().isoformat(),
        "brand": cfg["brand"], "stats": stats,
        "fastest_rising": fastest, "top_posts": top_posts,
        "patterns": stored_patterns, "ideas": idea_rows,
        "our_results": our_results, "repo_url": REPO_URL,
    }
    report.render_report(context, report_path)

    email_cfg = dict(cfg.get("email", {}))
    email_cfg.update({
        "host": os.environ.get("SMTP_HOST"), "port": os.environ.get("SMTP_PORT", 587),
        "user": os.environ.get("SMTP_USER"),
        "password": os.environ.get("SMTP_PASSWORD"),
        "to": os.environ.get("SMTP_TO"),
    })
    report.send_email(Path(report_path).read_text(encoding="utf-8"),
                      f"{cfg['brand']['name']} Intelligence — {context['report_date']}",
                      email_cfg)

    conn.close()
    logger.info("daily run complete: %s", stats)
    return stats


def build_our_results(conn, cfg) -> list:
    """Placeholder until Task 10 fills it in."""
    return []


def main() -> None:
    parser = argparse.ArgumentParser(description="igtt daily intelligence run")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--db", default="data/intelligence.db")
    parser.add_argument("--report", default="reports/latest.html")
    args = parser.parse_args()
    run_daily(args.config, args.db, args.report)


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run the whole suite and confirm it passes**

Run: `python -m pytest tests/ -v`
Expected: all pass, including the three in `tests/test_app.py`

- [ ] **Step 6: Commit**

```bash
git add app.py src/db.py tests/test_app.py
git commit -m "feat: add daily orchestrator wiring the full pipeline"
```

---

### Task 10: Own-post tracking and the feedback loop

Without this the system only ever admires other people's posts. DTW's own content flows through the identical collect/snapshot/score path, and its measured results are fed back into idea generation.

**Files:**
- Modify: `app.py` (collect own account, implement `build_our_results`)
- Modify: `src/db.py` (add `get_our_posts`, `account_baseline`)
- Test: `tests/test_feedback.py`

**Interfaces:**
- Consumes: Tasks 1-9.
- Produces:
  - `src.db.get_our_posts(conn, days: int = 30) -> list[sqlite3.Row]` — posts where `is_ours = 1`
  - `src.db.account_baseline(conn, account_id: int, days: int = 30) -> float | None` — median views across that account's posts in the window, `None` if fewer than three measured posts
  - `app.build_our_results(conn, cfg) -> list[dict]` — keys `shortcode`, `caption`, `views`, `baseline_views`, `vs_baseline`, `source_pattern`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_feedback.py`:

```python
import pytest

import app
from src import db


@pytest.fixture()
def conn(tmp_path):
    c = db.connect(str(tmp_path / "t.db"))
    db.init_schema(c)
    yield c
    c.close()


def add_post(conn, account_id, shortcode, views, is_ours=0,
             posted_at="2026-09-05T10:00:00+00:00"):
    pid = db.upsert_post(conn, {
        "shortcode": shortcode, "account_id": account_id, "posted_at": posted_at,
        "is_ours": is_ours, "caption": "c", "url": "u",
    })
    db.add_snapshot(conn, pid, views=views, likes=10, comments=1, shares=None)
    return pid


def test_account_baseline_is_median_views(conn):
    aid = db.upsert_account(conn, "drinktoiletwine")
    for i, v in enumerate([1000, 3000, 5000, 100000]):
        add_post(conn, aid, f"S{i}", v, is_ours=1)
    assert db.account_baseline(conn, aid) == 4000.0


def test_account_baseline_none_with_too_few_posts(conn):
    aid = db.upsert_account(conn, "drinktoiletwine")
    add_post(conn, aid, "S1", 1000, is_ours=1)
    assert db.account_baseline(conn, aid) is None, \
        "two posts is not a baseline, and a bad baseline is worse than none"


def test_get_our_posts_excludes_competitors(conn):
    ours = db.upsert_account(conn, "drinktoiletwine")
    theirs = db.upsert_account(conn, "wineexample")
    add_post(conn, ours, "MINE", 5000, is_ours=1)
    add_post(conn, theirs, "THEIRS", 500000, is_ours=0)
    codes = [r["shortcode"] for r in db.get_our_posts(conn)]
    assert codes == ["MINE"]


def test_build_our_results_computes_multiple_of_baseline(conn):
    aid = db.upsert_account(conn, "drinktoiletwine")
    for i, v in enumerate([1000, 2000, 3000, 4000]):
        add_post(conn, aid, f"OLD{i}", v, is_ours=1)
    add_post(conn, aid, "HIT", 12500, is_ours=1)
    cfg = {"brand": {"instagram": "drinktoiletwine"}}
    results = app.build_our_results(conn, cfg)
    hit = next(r for r in results if r["shortcode"] == "HIT")
    assert hit["baseline_views"] == 3000.0
    assert hit["vs_baseline"] == pytest.approx(12500 / 3000)


def test_build_our_results_empty_when_we_have_posted_nothing(conn):
    db.upsert_account(conn, "drinktoiletwine")
    assert app.build_our_results(conn, {"brand": {"instagram": "drinktoiletwine"}}) == []
```

- [ ] **Step 2: Run them and confirm they fail**

Run: `python -m pytest tests/test_feedback.py -v`
Expected: FAIL, `AttributeError: module 'src.db' has no attribute 'get_our_posts'`

- [ ] **Step 3: Append to `src/db.py`**

```python
def get_our_posts(conn, days: int = 30) -> list:
    """Our own published posts within the window."""
    from datetime import timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    return conn.execute(
        "SELECT * FROM posts WHERE is_ours = 1 AND posted_at >= ? ORDER BY posted_at DESC",
        (cutoff,),
    ).fetchall()


def account_baseline(conn, account_id: int, days: int = 30):
    """Median views for an account's recent posts. None below three measured posts.

    Median rather than mean: one viral post would otherwise raise the bar so far
    that every normal post looks like a failure.
    """
    from datetime import timedelta
    from statistics import median
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    rows = conn.execute(
        """
        SELECT MAX(s.views) AS views
        FROM posts p
        JOIN post_snapshots s ON s.post_id = p.id
        WHERE p.account_id = ? AND p.posted_at >= ? AND s.views IS NOT NULL
        GROUP BY p.id
        """,
        (account_id, cutoff),
    ).fetchall()
    values = [r["views"] for r in rows if r["views"] is not None]
    if len(values) < 3:
        return None
    return float(median(values))
```

- [ ] **Step 4: Replace the `build_our_results` placeholder in `app.py`**

```python
def build_our_results(conn, cfg) -> list:
    """How our own recent posts performed against our own 30-day baseline."""
    import json as _json

    our_posts = db.get_our_posts(conn, days=30)
    if not our_posts:
        return []

    results = []
    for post in our_posts:
        baseline = db.account_baseline(conn, post["account_id"], days=30)
        metrics = db.latest_metrics(conn, post["id"])
        views = metrics.get("views")

        source_pattern = None
        idea = conn.execute(
            "SELECT brief_json FROM ideas WHERE posted_shortcode = ?",
            (post["shortcode"],),
        ).fetchone()
        if idea:
            source_pattern = _json.loads(idea["brief_json"]).get("source_pattern")

        results.append({
            "shortcode": post["shortcode"],
            "caption": post["caption"],
            "views": views,
            "baseline_views": baseline,
            "vs_baseline": (views / baseline) if views and baseline else None,
            "source_pattern": source_pattern,
        })
    return results
```

- [ ] **Step 5: Add our own account to the collection step in `app.py`**

Inside `run_daily`, immediately after `accounts = db.get_active_accounts(conn)[: mon["max_accounts"]]`, add:

```python
    # Our own account is collected and measured exactly like a competitor's.
    own_handle = cfg["brand"]["instagram"]
    own_id = db.upsert_account(conn, own_handle, category="own", active=1)
    if own_handle not in [a["username"] for a in accounts]:
        accounts = list(accounts) + [db.get_account(conn, own_id)]
```

And mark our posts as ours — in the storing loop, replace `"is_ours": 0,` with:

```python
            "is_ours": 1 if username == own_handle else 0,
```

Add the missing accessor to `src/db.py`:

```python
def get_account(conn, account_id: int):
    return conn.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
```

- [ ] **Step 6: Run the whole suite and confirm it passes**

Run: `python -m pytest tests/ -v`
Expected: all pass

- [ ] **Step 7: Commit**

```bash
git add app.py src/db.py tests/test_feedback.py
git commit -m "feat: track our own posts and feed results back into idea generation"
```

---

### Task 11: Blotato publishing and `post.py`

Publishing without building an approval UI. `post.py` takes one idea id; a `workflow_dispatch` supplies it from the phone.

**Files:**
- Create: `src/blotato.py`, `post.py`, `.github/workflows/post.yml`
- Test: `tests/test_blotato.py`, `tests/test_post.py`

**Interfaces:**
- Consumes: `src.db.get_idea`, `src.db.mark_idea_posted` (Task 7).
- Produces:
  - `src.blotato.upload_media(api_key: str, url: str) -> str | None` — returns the Blotato-hosted media URL
  - `src.blotato.publish_instagram(api_key: str, account_id: str, text: str, media_url: str) -> dict | None`
  - `post.publish_idea(idea_id: int, config_path: str = "config.yaml", db_path: str = "data/intelligence.db") -> bool`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_blotato.py`:

```python
from src import blotato


def test_upload_media_returns_hosted_url(mocker):
    m = mocker.patch("src.blotato.requests.post")
    m.return_value.status_code = 200
    m.return_value.json.return_value = {"url": "https://blotato.cdn/abc.mp4"}
    out = blotato.upload_media("k", "https://source/v.mp4")
    assert out == "https://blotato.cdn/abc.mp4"
    assert m.call_args[0][0] == "https://backend.blotato.com/v2/media"
    assert m.call_args[1]["headers"]["blotato-api-key"] == "k"


def test_upload_media_returns_none_on_failure(mocker):
    mocker.patch("src.blotato.requests.post", side_effect=Exception("500"))
    assert blotato.upload_media("k", "https://source/v.mp4") is None


def test_publish_instagram_posts_expected_body(mocker):
    m = mocker.patch("src.blotato.requests.post")
    m.return_value.status_code = 200
    m.return_value.json.return_value = {"id": "p1"}
    out = blotato.publish_instagram("k", "acct1", "caption here",
                                    "https://blotato.cdn/abc.mp4")
    assert out == {"id": "p1"}
    body = m.call_args[1]["json"]["post"]
    assert body["target"]["targetType"] == "instagram"
    assert body["content"]["platform"] == "instagram"
    assert body["content"]["text"] == "caption here"
    assert body["content"]["mediaUrls"] == ["https://blotato.cdn/abc.mp4"]
    assert body["accountId"] == "acct1"


def test_publish_instagram_returns_none_on_failure(mocker):
    mocker.patch("src.blotato.requests.post", side_effect=Exception("timeout"))
    assert blotato.publish_instagram("k", "a", "t", "u") is None
```

Create `tests/test_post.py`:

```python
import pytest

import post
from src import db


BRIEF = {"concept": "c", "hook": "h", "script": "s", "caption": "the caption",
         "similarity_risk": "LOW", "media_url": "https://mine/video.mp4"}


@pytest.fixture()
def db_path(tmp_path):
    p = str(tmp_path / "t.db")
    conn = db.connect(p)
    db.init_schema(conn)
    conn.close()
    return p


def test_publish_idea_uploads_and_posts(db_path, mocker, monkeypatch):
    monkeypatch.setenv("BLOTATO_API_KEY", "k")
    monkeypatch.setenv("BLOTATO_INSTAGRAM_ACCOUNT_ID", "acct1")
    conn = db.connect(db_path)
    idea_id = db.save_idea(conn, BRIEF, None, "LOW", 90.0)
    conn.close()

    mocker.patch("post.blotato.upload_media", return_value="https://cdn/v.mp4")
    mocker.patch("post.blotato.publish_instagram",
                 return_value={"id": "p1", "shortcode": "NEWCODE"})

    assert post.publish_idea(idea_id, db_path=db_path) is True

    conn = db.connect(db_path)
    row = db.get_idea(conn, idea_id)
    assert row["status"] == "posted"
    assert row["posted_shortcode"] == "NEWCODE"
    conn.close()


def test_publish_idea_refuses_unknown_id(db_path):
    assert post.publish_idea(999, db_path=db_path) is False


def test_publish_idea_refuses_already_posted(db_path, monkeypatch):
    monkeypatch.setenv("BLOTATO_API_KEY", "k")
    conn = db.connect(db_path)
    idea_id = db.save_idea(conn, BRIEF, None, "LOW", 90.0)
    db.mark_idea_posted(conn, idea_id, "ALREADY")
    conn.close()
    assert post.publish_idea(idea_id, db_path=db_path) is False


def test_publish_idea_refuses_high_similarity_risk(db_path, monkeypatch):
    monkeypatch.setenv("BLOTATO_API_KEY", "k")
    conn = db.connect(db_path)
    idea_id = db.save_idea(conn, {**BRIEF, "similarity_risk": "HIGH"}, None,
                           "HIGH", 90.0)
    conn.close()
    assert post.publish_idea(idea_id, db_path=db_path) is False


def test_publish_idea_stops_when_upload_fails(db_path, mocker, monkeypatch):
    monkeypatch.setenv("BLOTATO_API_KEY", "k")
    monkeypatch.setenv("BLOTATO_INSTAGRAM_ACCOUNT_ID", "acct1")
    conn = db.connect(db_path)
    idea_id = db.save_idea(conn, BRIEF, None, "LOW", 90.0)
    conn.close()
    mocker.patch("post.blotato.upload_media", return_value=None)
    publish = mocker.patch("post.blotato.publish_instagram")
    assert post.publish_idea(idea_id, db_path=db_path) is False
    publish.assert_not_called()
```

- [ ] **Step 2: Run them and confirm they fail**

Run: `python -m pytest tests/test_blotato.py tests/test_post.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'src.blotato'`

- [ ] **Step 3: Write `src/blotato.py`**

```python
"""Blotato publishing. Chosen over the Instagram Graph API to skip Meta app review."""

import logging

import requests

logger = logging.getLogger(__name__)

MEDIA_URL = "https://backend.blotato.com/v2/media"
POSTS_URL = "https://backend.blotato.com/v2/posts"
TIMEOUT = 120


def _headers(api_key: str) -> dict:
    return {"blotato-api-key": api_key, "Content-Type": "application/json"}


def upload_media(api_key: str, url: str):
    """Hand Blotato a source URL, get back a hosted one. None on failure."""
    try:
        resp = requests.post(MEDIA_URL, headers=_headers(api_key),
                             json={"url": url}, timeout=TIMEOUT)
        resp.raise_for_status()
        return resp.json().get("url")
    except Exception as exc:
        logger.error("blotato media upload failed for %s: %s", url, exc)
        return None


def publish_instagram(api_key: str, account_id: str, text: str, media_url: str):
    """Publish one Instagram post. None on failure."""
    body = {
        "post": {
            "target": {"targetType": "instagram"},
            "content": {"text": text, "platform": "instagram",
                        "mediaUrls": [media_url]},
            "accountId": account_id,
        }
    }
    try:
        resp = requests.post(POSTS_URL, headers=_headers(api_key), json=body,
                             timeout=TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        logger.error("blotato publish failed: %s", exc)
        return None
```

- [ ] **Step 4: Write `post.py`**

```python
"""Publish one approved idea. Invoked by hand or by the post.yml workflow."""

import argparse
import json
import logging
import os
import sys

from src import blotato, db
from src.config import load_config

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                    stream=sys.stdout)
logger = logging.getLogger("post")


def publish_idea(idea_id: int, config_path: str = "config.yaml",
                 db_path: str = "data/intelligence.db") -> bool:
    load_config(config_path)
    conn = db.connect(db_path)

    idea = db.get_idea(conn, idea_id)
    if idea is None:
        logger.error("no idea with id %s", idea_id)
        return False
    if idea["status"] == "posted":
        logger.error("idea %s was already posted as %s", idea_id,
                     idea["posted_shortcode"])
        return False
    if str(idea["similarity_risk"]).upper() == "HIGH":
        logger.error("refusing to publish idea %s: HIGH similarity risk", idea_id)
        return False

    brief = json.loads(idea["brief_json"])
    media_url = brief.get("media_url")
    if not media_url:
        logger.error("idea %s has no media_url — add the finished video's URL to the "
                     "brief before publishing", idea_id)
        return False

    api_key = os.environ.get("BLOTATO_API_KEY", "")
    account_id = os.environ.get("BLOTATO_INSTAGRAM_ACCOUNT_ID", "")
    if not api_key or not account_id:
        logger.error("BLOTATO_API_KEY and BLOTATO_INSTAGRAM_ACCOUNT_ID must be set")
        return False

    hosted = blotato.upload_media(api_key, media_url)
    if not hosted:
        return False

    result = blotato.publish_instagram(api_key, account_id,
                                       brief.get("caption", ""), hosted)
    if not result:
        return False

    shortcode = result.get("shortcode") or result.get("id") or "unknown"
    db.mark_idea_posted(conn, idea_id, shortcode)
    logger.info("published idea %s as %s", idea_id, shortcode)
    conn.close()
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Publish one approved igtt idea")
    parser.add_argument("idea_id", type=int)
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--db", default="data/intelligence.db")
    args = parser.parse_args()
    if not publish_idea(args.idea_id, args.config, args.db):
        sys.exit(1)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4b: Enforce the repost permission gate**

The spec requires `post.py` to refuse a repost that has no recorded permission. Nothing
populates `repost_candidates` yet, but the enforcement point belongs here now — adding
it later means the first row inserted is the one that slips through.

Append to `tests/test_post.py`:

```python
def test_publish_idea_refuses_unpermitted_repost(db_path, monkeypatch):
    monkeypatch.setenv("BLOTATO_API_KEY", "k")
    monkeypatch.setenv("BLOTATO_INSTAGRAM_ACCOUNT_ID", "acct1")
    conn = db.connect(db_path)
    account_id = db.upsert_account(conn, "wineexample")
    post_id = db.upsert_post(conn, {"shortcode": "THEIRS", "account_id": account_id,
                                    "posted_at": "2026-09-05T10:00:00+00:00"})
    conn.execute(
        "INSERT INTO repost_candidates (post_id, permission_granted, credit_handle) "
        "VALUES (?, 0, NULL)", (post_id,))
    conn.commit()
    idea_id = db.save_idea(conn, {**BRIEF, "repost_of_shortcode": "THEIRS"},
                           None, "LOW", 90.0)
    conn.close()
    assert post.publish_idea(idea_id, db_path=db_path) is False


def test_publish_idea_allows_permitted_repost(db_path, mocker, monkeypatch):
    monkeypatch.setenv("BLOTATO_API_KEY", "k")
    monkeypatch.setenv("BLOTATO_INSTAGRAM_ACCOUNT_ID", "acct1")
    conn = db.connect(db_path)
    account_id = db.upsert_account(conn, "wineexample")
    post_id = db.upsert_post(conn, {"shortcode": "THEIRS", "account_id": account_id,
                                    "posted_at": "2026-09-05T10:00:00+00:00"})
    conn.execute(
        "INSERT INTO repost_candidates (post_id, permission_granted, credit_handle) "
        "VALUES (?, 1, '@wineexample')", (post_id,))
    conn.commit()
    idea_id = db.save_idea(conn, {**BRIEF, "repost_of_shortcode": "THEIRS"},
                           None, "LOW", 90.0)
    conn.close()
    mocker.patch("post.blotato.upload_media", return_value="https://cdn/v.mp4")
    mocker.patch("post.blotato.publish_instagram", return_value={"shortcode": "NEW"})
    assert post.publish_idea(idea_id, db_path=db_path) is True
```

Add to `src/db.py`:

```python
def repost_permission(conn, shortcode: str):
    """Permission row for a repost, or None if there isn't one."""
    return conn.execute(
        """
        SELECT rc.* FROM repost_candidates rc
        JOIN posts p ON p.id = rc.post_id
        WHERE p.shortcode = ?
        """,
        (shortcode,),
    ).fetchone()
```

Add to `publish_idea` in `post.py`, immediately after the `similarity_risk` check and
before `brief = json.loads(...)` is used:

```python
    brief = json.loads(idea["brief_json"])

    repost_of = brief.get("repost_of_shortcode")
    if repost_of:
        permission = db.repost_permission(conn, repost_of)
        if not permission or not permission["permission_granted"] \
                or not permission["credit_handle"]:
            logger.error("refusing to repost %s: no recorded permission and credit "
                         "handle", repost_of)
            return False
```

Delete the now-duplicated `brief = json.loads(idea["brief_json"])` line further down.

Run: `python -m pytest tests/test_post.py -v`
Expected: 7 passed

- [ ] **Step 5: Write `.github/workflows/post.yml`**

```yaml
name: Publish approved idea

on:
  workflow_dispatch:
    inputs:
      idea_id:
        description: 'Idea id from the daily report'
        required: true
        type: string

permissions:
  contents: write

jobs:
  publish:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
          cache: 'pip'
      - run: pip install -r requirements.txt
      - name: Publish
        env:
          BLOTATO_API_KEY: ${{ secrets.BLOTATO_API_KEY }}
          BLOTATO_INSTAGRAM_ACCOUNT_ID: ${{ secrets.BLOTATO_INSTAGRAM_ACCOUNT_ID }}
        run: python post.py "${{ inputs.idea_id }}"
      - name: Commit updated database
        uses: stefanzweifel/git-auto-commit-action@8621497c8c39c72f3e2a999a26b4ca1b5058a842  # v5.0.1
        with:
          commit_message: "chore: published idea ${{ inputs.idea_id }}"
          file_pattern: data/intelligence.db
```

- [ ] **Step 6: Run the tests and confirm they pass**

Run: `python -m pytest tests/ -v`
Expected: all pass

- [ ] **Step 7: Commit**

```bash
git add src/blotato.py post.py .github/workflows/post.yml tests/test_blotato.py tests/test_post.py
git commit -m "feat: add blotato publishing and dispatch-driven post.py"
```

---

### Task 12: `discover.py` — evolving the account pool

Weekly. Finds candidate accounts from niche hashtags, scores them 0-100 with Claude, activates above 70, deactivates below 50.

**Files:**
- Create: `prompts/discover.md`, `discover.py`
- Modify: `src/apify.py` (add `search_hashtag_accounts`)
- Test: `tests/test_discover.py`, `tests/fixtures/apify_hashtag.json`

**Interfaces:**
- Consumes: `src.apify` (Task 2), `src.db` (Task 1), `src.analyze.extract_json` (Task 4).
- Produces:
  - `src.apify.search_hashtag_accounts(token: str, hashtags: list[str], limit: int) -> list[dict]` — dicts with `username`, `followers`, `sample_captions`
  - `discover.score_candidates(client, candidates: list[dict], brand: dict, model: str) -> list[dict]` — adds `relevance_score` and `category`
  - `discover.run_discovery(config_path: str = "config.yaml", db_path: str = "data/intelligence.db") -> dict` — returns `{"evaluated": n, "activated": n, "deactivated": n}`

- [ ] **Step 1: Create `tests/fixtures/apify_hashtag.json`**

```json
[
  {"ownerUsername": "winememequeen", "ownerFollowersCount": 145000,
   "caption": "when he says he only drinks natural wine"},
  {"ownerUsername": "winememequeen", "ownerFollowersCount": 145000,
   "caption": "rating my customers by their wine order"},
  {"ownerUsername": "corporate_wine_seminars", "ownerFollowersCount": 900,
   "caption": "Join our Q3 viticulture compliance webinar"},
  {"ownerFollowersCount": 500, "caption": "no username, must be dropped"}
]
```

- [ ] **Step 2: Write `prompts/discover.md`**

```markdown
You are evaluating Instagram accounts as monitoring targets for {brand_name}.
Brand voice: {brand_voice}

Score each candidate 0-100 on how useful it is to monitor, weighting:
- Audience relevance 30%
- Content overlap 25%
- Humor/style compatibility 20%
- Recent performance 15%
- Originality/inspiration value 10%

An account that posts corporate or educational content in the same industry is NOT
relevant — style compatibility matters as much as topic.

Also assign each a category from: {categories}

Candidates:
{candidates}

Respond with ONLY a JSON array, no prose and no markdown fence:

[{{"username": "", "relevance_score": 0, "category": "", "reason": ""}}]
```

- [ ] **Step 3: Write the failing tests**

Create `tests/test_discover.py`:

```python
import json
from pathlib import Path

import pytest

import discover
from src import apify, db

FIXTURE = Path(__file__).parent / "fixtures" / "apify_hashtag.json"


def fake_response(text):
    class Block:
        def __init__(self, t):
            self.text = t
    class Msg:
        def __init__(self, t):
            self.content = [Block(t)]
    return Msg(text)


@pytest.fixture()
def db_path(tmp_path):
    p = str(tmp_path / "t.db")
    conn = db.connect(p)
    db.init_schema(conn)
    conn.close()
    return p


def test_search_hashtag_accounts_dedupes_by_username(mocker):
    m = mocker.patch("src.apify.requests.post")
    m.return_value.status_code = 200
    m.return_value.json.return_value = json.loads(FIXTURE.read_text())
    out = apify.search_hashtag_accounts("tok", ["winememes"], limit=50)
    usernames = [c["username"] for c in out]
    assert usernames == ["winememequeen", "corporate_wine_seminars"]
    queen = out[0]
    assert queen["followers"] == 145000
    assert len(queen["sample_captions"]) == 2


def test_search_hashtag_accounts_empty_on_failure(mocker):
    mocker.patch("src.apify.requests.post", side_effect=Exception("boom"))
    assert apify.search_hashtag_accounts("tok", ["x"], 50) == []


def test_score_candidates_attaches_scores(mocker):
    client = mocker.Mock()
    client.messages.create.return_value = fake_response(json.dumps([
        {"username": "winememequeen", "relevance_score": 88, "category": "wine memes",
         "reason": "same audience, same humour"},
        {"username": "corporate_wine_seminars", "relevance_score": 12,
         "category": "wine", "reason": "corporate tone, wrong audience"},
    ]))
    out = discover.score_candidates(
        client,
        [{"username": "winememequeen", "followers": 145000, "sample_captions": []},
         {"username": "corporate_wine_seminars", "followers": 900,
          "sample_captions": []}],
        {"name": "DTW", "voice": "v"}, "claude-opus-5",
        categories=["wine", "wine memes"],
    )
    by_name = {c["username"]: c for c in out}
    assert by_name["winememequeen"]["relevance_score"] == 88
    assert by_name["corporate_wine_seminars"]["relevance_score"] == 12


def test_score_candidates_returns_empty_on_bad_response(mocker):
    client = mocker.Mock()
    client.messages.create.return_value = fake_response("nope")
    assert discover.score_candidates(client, [{"username": "a"}],
                                     {"name": "D", "voice": "v"},
                                     "claude-opus-5", categories=[]) == []


def test_run_discovery_activates_and_deactivates(db_path, mocker, monkeypatch):
    monkeypatch.setenv("APIFY_TOKEN", "t")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "t")

    conn = db.connect(db_path)
    stale_id = db.upsert_account(conn, "corporate_wine_seminars", active=1)
    conn.close()

    mocker.patch("discover.apify.search_hashtag_accounts", return_value=[
        {"username": "winememequeen", "followers": 145000, "sample_captions": []},
        {"username": "corporate_wine_seminars", "followers": 900,
         "sample_captions": []},
    ])
    mocker.patch("discover.score_candidates", return_value=[
        {"username": "winememequeen", "relevance_score": 88, "category": "wine memes"},
        {"username": "corporate_wine_seminars", "relevance_score": 12,
         "category": "wine"},
    ])
    mocker.patch("discover.Anthropic", return_value=mocker.Mock())

    stats = discover.run_discovery(config_path="config.yaml", db_path=db_path)
    assert stats["activated"] == 1
    assert stats["deactivated"] == 1

    conn = db.connect(db_path)
    active = [r["username"] for r in db.get_active_accounts(conn)]
    assert "winememequeen" in active
    assert "corporate_wine_seminars" not in active
    conn.close()


def test_run_discovery_respects_max_accounts(db_path, mocker, monkeypatch):
    """Never activate past monitoring.max_accounts — that is the spend ceiling."""
    monkeypatch.setenv("APIFY_TOKEN", "t")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "t")
    conn = db.connect(db_path)
    for i in range(75):
        db.upsert_account(conn, f"existing{i}", relevance_score=80, active=1)
    conn.close()

    mocker.patch("discover.apify.search_hashtag_accounts",
                 return_value=[{"username": "newcomer", "followers": 1,
                                "sample_captions": []}])
    mocker.patch("discover.score_candidates",
                 return_value=[{"username": "newcomer", "relevance_score": 99,
                                "category": "wine"}])
    mocker.patch("discover.Anthropic", return_value=mocker.Mock())

    stats = discover.run_discovery(config_path="config.yaml", db_path=db_path)
    assert stats["activated"] == 0

    conn = db.connect(db_path)
    assert len(db.get_active_accounts(conn)) == 75
    conn.close()
```

- [ ] **Step 4: Run them and confirm they fail**

Run: `python -m pytest tests/test_discover.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'discover'`

- [ ] **Step 5: Append `search_hashtag_accounts` to `src/apify.py`**

```python
HASHTAG_LIMIT_PER_TAG = 50


def search_hashtag_accounts(token: str, hashtags: list, limit: int) -> list:
    """Find distinct accounts posting under the given hashtags. [] on failure."""
    if not hashtags:
        return []

    body = {
        "search": hashtags[0] if len(hashtags) == 1 else " ".join(hashtags),
        "searchType": "hashtag",
        "searchLimit": len(hashtags),
        "resultsType": "posts",
        "resultsLimit": limit,
        "addParentData": False,
    }
    try:
        resp = requests.post(ACTOR_URL, headers={"Authorization": f"Bearer {token}"},
                             json=body, timeout=TIMEOUT)
        resp.raise_for_status()
        items = resp.json()
    except Exception as exc:
        logger.error("apify hashtag search failed: %s", exc)
        return []

    by_username: dict = {}
    for item in items:
        username = item.get("ownerUsername")
        if not username:
            continue
        entry = by_username.setdefault(username, {
            "username": username,
            "followers": item.get("ownerFollowersCount"),
            "sample_captions": [],
        })
        caption = item.get("caption")
        if caption and len(entry["sample_captions"]) < 5:
            entry["sample_captions"].append(caption)

    logger.info("hashtag search found %d distinct accounts", len(by_username))
    return list(by_username.values())
```

- [ ] **Step 6: Write `discover.py`**

```python
"""Weekly: find new accounts worth monitoring, retire the ones that stopped fitting."""

import argparse
import json
import logging
import os
import sys

from anthropic import Anthropic

from src import apify, db
from src.analyze import extract_json, load_prompt
from src.config import load_config

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                    stream=sys.stdout)
logger = logging.getLogger("discover")


def score_candidates(client, candidates: list, brand: dict, model: str,
                     categories: list) -> list:
    """Score candidate accounts 0-100 for monitoring value. [] on failure."""
    if not candidates:
        return []

    prompt = load_prompt("discover").format(
        brand_name=brand.get("name", ""),
        brand_voice=brand.get("voice", ""),
        categories=", ".join(categories),
        candidates=json.dumps(candidates, indent=1, default=str),
    )
    try:
        resp = client.messages.create(
            model=model, max_tokens=4000,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = "".join(b.text for b in resp.content if hasattr(b, "text"))
    except Exception as exc:
        logger.error("candidate scoring failed: %s", exc)
        return []

    data = extract_json(raw)
    if data is None:
        start, end = raw.find("["), raw.rfind("]")
        if start != -1 and end != -1:
            try:
                data = json.loads(raw[start:end + 1])
            except json.JSONDecodeError:
                data = None
    if not isinstance(data, list):
        logger.warning("candidate scoring returned no usable array")
        return []

    return [c for c in data
            if isinstance(c, dict) and c.get("username")
            and c.get("relevance_score") is not None]


def run_discovery(config_path: str = "config.yaml",
                  db_path: str = "data/intelligence.db") -> dict:
    cfg = load_config(config_path)
    conn = db.connect(db_path)
    db.init_schema(conn)

    disc = cfg["discovery"]
    max_accounts = cfg["monitoring"]["max_accounts"]

    existing = {r["username"]: r for r in db.get_active_accounts(conn)}
    candidates = apify.search_hashtag_accounts(
        os.environ.get("APIFY_TOKEN", ""), disc["hashtags"], limit=200)
    for username, row in existing.items():
        if username not in [c["username"] for c in candidates]:
            candidates.append({"username": username,
                               "followers": row["followers"],
                               "sample_captions": []})

    client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))
    scored = score_candidates(client, candidates, cfg["brand"],
                              cfg["models"]["strategy"], cfg["categories"])

    stats = {"evaluated": len(scored), "activated": 0, "deactivated": 0}
    active_count = len(existing)

    for cand in scored:
        username = cand["username"]
        raw_score = cand.get("relevance_score")
        try:
            relevance = float(raw_score)
        except (TypeError, ValueError):
            logger.warning("skipping %s: unusable relevance_score %r",
                           username, raw_score)
            continue
        is_active = username in existing

        if relevance < disc["deactivate_below"]:
            if is_active:
                db.set_account_score(conn, existing[username]["id"], relevance, 0)
                stats["deactivated"] += 1
                active_count -= 1
                logger.info("deactivated %s (score %.0f)", username, relevance)
            continue

        if relevance >= disc["activate_above"] and not is_active:
            if active_count >= max_accounts:
                logger.info("at max_accounts (%d), not adding %s",
                            max_accounts, username)
                continue
            db.upsert_account(conn, username, category=cand.get("category"),
                              followers=cand.get("followers"),
                              relevance_score=relevance, active=1)
            stats["activated"] += 1
            active_count += 1
            logger.info("activated %s (score %.0f)", username, relevance)
        elif is_active:
            db.set_account_score(conn, existing[username]["id"], relevance, 1)

    conn.close()
    logger.info("discovery complete: %s", stats)
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="igtt weekly account discovery")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--db", default="data/intelligence.db")
    args = parser.parse_args()
    run_discovery(args.config, args.db)


if __name__ == "__main__":
    main()
```

- [ ] **Step 7: Run the tests and confirm they pass**

Run: `python -m pytest tests/ -v`
Expected: all pass

- [ ] **Step 8: Commit**

```bash
git add prompts/discover.md discover.py src/apify.py tests/test_discover.py tests/fixtures/apify_hashtag.json
git commit -m "feat: add weekly account discovery with relevance scoring"
```

---

### Task 13: Scheduling, seed accounts, and README

Last task. The cron workflows, a way to load the starting account list, and the operating instructions.

**Files:**
- Create: `.github/workflows/daily.yml`, `.github/workflows/discover.yml`, `seed_accounts.py`, `seeds.txt`, `README.md`
- Test: `tests/test_seed.py`

**Interfaces:**
- Consumes: `src.db.upsert_account` (Task 1).
- Produces: `seed_accounts.py:load_seeds(path: str, db_path: str) -> int` — returns the number of accounts inserted.

- [ ] **Step 1: Write the failing test**

Create `tests/test_seed.py`:

```python
import seed_accounts
from src import db


def test_load_seeds_inserts_accounts(tmp_path):
    seeds = tmp_path / "seeds.txt"
    seeds.write_text(
        "# wine\n"
        "wineexample, wine\n"
        "winememequeen, wine memes\n"
        "\n"
        "serverproblems, hospitality\n"
    )
    db_path = str(tmp_path / "t.db")
    count = seed_accounts.load_seeds(str(seeds), db_path)
    assert count == 3

    conn = db.connect(db_path)
    rows = {r["username"]: r["category"] for r in db.get_active_accounts(conn)}
    assert rows["winememequeen"] == "wine memes"
    assert "#" not in "".join(rows)
    conn.close()


def test_load_seeds_is_rerunnable(tmp_path):
    seeds = tmp_path / "seeds.txt"
    seeds.write_text("wineexample, wine\n")
    db_path = str(tmp_path / "t.db")
    seed_accounts.load_seeds(str(seeds), db_path)
    seed_accounts.load_seeds(str(seeds), db_path)
    conn = db.connect(db_path)
    assert len(db.get_active_accounts(conn)) == 1
    conn.close()
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `python -m pytest tests/test_seed.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'seed_accounts'`

- [ ] **Step 3: Write `seed_accounts.py`**

```python
"""One-time (re-runnable) loader for the starting account list."""

import argparse
import logging
import sys
from pathlib import Path

from src import db

logging.basicConfig(level=logging.INFO, stream=sys.stdout)
logger = logging.getLogger("seed")


def load_seeds(path: str, db_path: str = "data/intelligence.db") -> int:
    """Load `username, category` lines. Blank lines and # comments ignored."""
    conn = db.connect(db_path)
    db.init_schema(conn)
    count = 0
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        username, _, category = line.partition(",")
        db.upsert_account(conn, username.strip().lstrip("@"),
                          category=category.strip() or None, active=1)
        count += 1
    conn.close()
    logger.info("seeded %d accounts", count)
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed the igtt account list")
    parser.add_argument("--file", default="seeds.txt")
    parser.add_argument("--db", default="data/intelligence.db")
    args = parser.parse_args()
    load_seeds(args.file, args.db)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Create `seeds.txt`**

Starter file. The operator replaces these with real handles before the first run; `discover.py` grows the list from there.

```
# username, category
# Replace these placeholders with real handles before the first run.
# ~15 wine, 10 meme, 10 restaurant/hospitality, 10 alcohol brand, 10 lifestyle/food.

# --- wine ---
# examplewineaccount, wine

# --- wine memes ---
# examplewinememes, wine memes

# --- hospitality / restaurants ---
# exampleserverlife, hospitality

# --- alcohol brands ---
# examplebrand, alcohol

# --- lifestyle / food ---
# examplefoodie, food
```

- [ ] **Step 5: Write `.github/workflows/daily.yml`**

```yaml
name: Daily intelligence run

on:
  schedule:
    - cron: '0 11 * * *'   # 11:00 UTC daily
  workflow_dispatch:

permissions:
  contents: write

concurrency:
  group: igtt-db
  cancel-in-progress: false

jobs:
  run:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
          cache: 'pip'
      - run: pip install -r requirements.txt
      - name: Daily run
        env:
          APIFY_TOKEN: ${{ secrets.APIFY_TOKEN }}
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
          SMTP_HOST: ${{ secrets.SMTP_HOST }}
          SMTP_PORT: ${{ secrets.SMTP_PORT }}
          SMTP_USER: ${{ secrets.SMTP_USER }}
          SMTP_PASSWORD: ${{ secrets.SMTP_PASSWORD }}
          SMTP_TO: ${{ secrets.SMTP_TO }}
        run: python app.py
      - name: Upload report
        uses: actions/upload-artifact@v4
        with:
          name: daily-report
          path: reports/latest.html
      - name: Commit database
        uses: stefanzweifel/git-auto-commit-action@8621497c8c39c72f3e2a999a26b4ca1b5058a842  # v5.0.1
        with:
          commit_message: "chore: daily run ${{ github.run_id }}"
          file_pattern: data/intelligence.db
```

- [ ] **Step 6: Write `.github/workflows/discover.yml`**

```yaml
name: Weekly account discovery

on:
  schedule:
    - cron: '0 10 * * 1'   # Mondays 10:00 UTC, before that day's daily run
  workflow_dispatch:

permissions:
  contents: write

concurrency:
  group: igtt-db
  cancel-in-progress: false

jobs:
  discover:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
          cache: 'pip'
      - run: pip install -r requirements.txt
      - name: Discover accounts
        env:
          APIFY_TOKEN: ${{ secrets.APIFY_TOKEN }}
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
        run: python discover.py
      - name: Commit database
        uses: stefanzweifel/git-auto-commit-action@8621497c8c39c72f3e2a999a26b4ca1b5058a842  # v5.0.1
        with:
          commit_message: "chore: weekly discovery ${{ github.run_id }}"
          file_pattern: data/intelligence.db
```

- [ ] **Step 7: Write `README.md`**

```markdown
# igtt — Instagram Content Intelligence

Daily competitive intelligence and content briefs for
[@drinktoiletwine](https://www.instagram.com/drinktoiletwine/).

## What it does

Every morning it collects recent posts from ~75 tracked Instagram accounts, ranks
them numerically for free, sends only the strongest to Claude for strategist
analysis and the top videos to Gemini for a recreation blueprint, clusters recurring
formats across 7/30/90 days, generates ten original content briefs, and writes
`reports/latest.html`.

Published posts are tracked the same way, so the system learns which formats work
for this account specifically.

## Setup

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # fill in your keys
# put real handles in seeds.txt, then:
python seed_accounts.py
```

## Running

| Command | What it does |
|---|---|
| `python app.py` | One full daily run |
| `python discover.py` | Re-evaluate and evolve the account pool |
| `python post.py <idea_id>` | Publish one approved idea |
| `python -m pytest tests/ -v` | Run the test suite (no network) |

## Day-to-day

You edit two files and nothing else:

- `config.yaml` — accounts, limits, scoring weights, models
- `.env` — API keys

To publish, open `reports/latest.html`, pick an idea, add the finished video's URL
to that idea's brief, then run the **Publish approved idea** workflow with its id.

## Scheduling

GitHub Actions runs `daily.yml` at 11:00 UTC and `discover.yml` Mondays at 10:00 UTC.
Both commit `data/intelligence.db` back to the repository — that is how state survives
between runs, since Actions has no persistent disk.

Required repository secrets: `APIFY_TOKEN`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`,
`BLOTATO_API_KEY`, `BLOTATO_INSTAGRAM_ACCOUNT_ID`, and the `SMTP_*` set if email is
enabled.

## Cost ceilings

Enforced in code from `config.yaml`: 75 accounts, 7-day lookback, 40 text analyses
per day, 15 video analyses per day, 10 ideas per day, 1 post per day.

## What it will not do

- Copy competitor content. Formats are abstracted; ideas scored HIGH similarity risk
  are discarded before you ever see them.
- Repost anyone's video without recorded permission and a credit handle.
- Post unattended. `posting.auto` is `false`.
```

- [ ] **Step 8: Run the full suite one last time**

Run: `python -m pytest tests/ -v`
Expected: all pass

- [ ] **Step 9: Commit**

```bash
git add .github/workflows/daily.yml .github/workflows/discover.yml \
        seed_accounts.py seeds.txt README.md tests/test_seed.py
git commit -m "feat: add scheduling workflows, account seeding, and README"
```

---

## Deferred, deliberately

Not in this plan. Each is a separate spec-plan cycle when the loop above is proven.

- **TikTok adapter.** A second function in `src/apify.py` targeting
  `clockworks~tiktok-scraper`, normalizing into the same post shape. Nothing
  downstream changes. Wait until Instagram is producing briefs worth filming.
- **Unattended posting.** `posting.auto: true` plus a scheduled call to
  `post.publish_idea` in `daily.yml`.
- **Repost lane execution.** `repost_candidates` exists and is enforced by
  `post.py`'s risk check, but nothing populates it yet. Add when a permission
  workflow exists.
- **AI video generation.** Briefs first. Generation only if the briefs prove out.
