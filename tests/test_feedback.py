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


def test_build_our_results_measured_zero_views_is_real_data(conn):
    aid = db.upsert_account(conn, "drinktoiletwine")
    for i, v in enumerate([1000, 2000, 3000]):
        add_post(conn, aid, f"OLD{i}", v, is_ours=1)
    add_post(conn, aid, "FLOP", 0, is_ours=1)
    cfg = {"brand": {"instagram": "drinktoiletwine"}}
    results = app.build_our_results(conn, cfg)
    flop = next(r for r in results if r["shortcode"] == "FLOP")
    assert flop["views"] == 0, "measured zero views is real data, not missing"
    assert flop["vs_baseline"] == 0.0, "zero views vs baseline is 0.0, not None"
