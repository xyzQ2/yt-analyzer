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
