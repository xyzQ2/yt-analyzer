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
