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


def test_publish_idea_creates_container_and_posts(db_path, mocker, monkeypatch):
    monkeypatch.setenv("IG_ACCESS_TOKEN", "tok")
    monkeypatch.setenv("IG_USER_ID", "ig1")
    conn = db.connect(db_path)
    idea_id = db.save_idea(conn, BRIEF, None, "LOW", 90.0)
    conn.close()

    mocker.patch("post.instagram.create_container", return_value="c1")
    # media_publish only ever returns an id — see tests/test_instagram.py.
    mocker.patch("post.instagram.publish_container", return_value={"id": "p1"})

    assert post.publish_idea(idea_id, db_path=db_path) is True

    conn = db.connect(db_path)
    row = db.get_idea(conn, idea_id)
    assert row["status"] == "posted"
    assert row["posted_ref"] == "p1"
    assert row["posted_shortcode"] is None, (
        "the real Instagram shortcode isn't known until Apify collects the post "
        "later — see bind_idea_shortcode"
    )
    conn.close()


def test_publish_idea_refuses_unknown_id(db_path):
    assert post.publish_idea(999, db_path=db_path) is False


def test_publish_idea_refuses_already_posted(db_path, monkeypatch):
    monkeypatch.setenv("IG_ACCESS_TOKEN", "tok")
    conn = db.connect(db_path)
    idea_id = db.save_idea(conn, BRIEF, None, "LOW", 90.0)
    db.mark_idea_posted(conn, idea_id, "ALREADY")
    conn.close()
    assert post.publish_idea(idea_id, db_path=db_path) is False


def test_publish_idea_refuses_high_similarity_risk(db_path, monkeypatch):
    monkeypatch.setenv("IG_ACCESS_TOKEN", "tok")
    conn = db.connect(db_path)
    idea_id = db.save_idea(conn, {**BRIEF, "similarity_risk": "HIGH"}, None,
                           "HIGH", 90.0)
    conn.close()
    assert post.publish_idea(idea_id, db_path=db_path) is False


def test_publish_idea_stops_when_container_fails(db_path, mocker, monkeypatch):
    monkeypatch.setenv("IG_ACCESS_TOKEN", "tok")
    monkeypatch.setenv("IG_USER_ID", "ig1")
    conn = db.connect(db_path)
    idea_id = db.save_idea(conn, BRIEF, None, "LOW", 90.0)
    conn.close()
    mocker.patch("post.instagram.create_container", return_value=None)
    publish = mocker.patch("post.instagram.publish_container")
    assert post.publish_idea(idea_id, db_path=db_path) is False
    publish.assert_not_called()


def test_publish_idea_refuses_unpermitted_repost(db_path, monkeypatch):
    monkeypatch.setenv("IG_ACCESS_TOKEN", "tok")
    monkeypatch.setenv("IG_USER_ID", "ig1")
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
    monkeypatch.setenv("IG_ACCESS_TOKEN", "tok")
    monkeypatch.setenv("IG_USER_ID", "ig1")
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
    mocker.patch("post.instagram.create_container", return_value="c1")
    mocker.patch("post.instagram.publish_container", return_value={"shortcode": "NEW"})
    assert post.publish_idea(idea_id, db_path=db_path) is True


def test_publish_idea_refuses_missing_media_url(db_path, mocker, monkeypatch):
    monkeypatch.setenv("IG_ACCESS_TOKEN", "tok")
    monkeypatch.setenv("IG_USER_ID", "ig1")
    conn = db.connect(db_path)
    idea_id = db.save_idea(conn, {**BRIEF, "media_url": None}, None, "LOW", 90.0)
    conn.close()
    create = mocker.patch("post.instagram.create_container")
    assert post.publish_idea(idea_id, db_path=db_path) is False
    create.assert_not_called()


def test_publish_idea_refuses_missing_credentials(db_path, mocker, monkeypatch):
    monkeypatch.delenv("IG_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("IG_USER_ID", raising=False)
    conn = db.connect(db_path)
    idea_id = db.save_idea(conn, BRIEF, None, "LOW", 90.0)
    conn.close()
    create = mocker.patch("post.instagram.create_container")
    assert post.publish_idea(idea_id, db_path=db_path) is False
    create.assert_not_called()


def test_publish_idea_refuses_repost_without_credit_handle(db_path, mocker, monkeypatch):
    monkeypatch.setenv("IG_ACCESS_TOKEN", "tok")
    monkeypatch.setenv("IG_USER_ID", "ig1")
    conn = db.connect(db_path)
    account_id = db.upsert_account(conn, "wineexample")
    post_id = db.upsert_post(conn, {"shortcode": "THEIRS", "account_id": account_id,
                                    "posted_at": "2026-09-05T10:00:00+00:00"})
    # permission_granted=1 but credit_handle is NULL
    conn.execute(
        "INSERT INTO repost_candidates (post_id, permission_granted, credit_handle) "
        "VALUES (?, 1, NULL)", (post_id,))
    conn.commit()
    idea_id = db.save_idea(conn, {**BRIEF, "repost_of_shortcode": "THEIRS"},
                           None, "LOW", 90.0)
    conn.close()
    create = mocker.patch("post.instagram.create_container")
    assert post.publish_idea(idea_id, db_path=db_path) is False
    create.assert_not_called()


def test_publish_idea_refuses_when_max_per_day_reached(db_path, mocker, monkeypatch):
    """config.yaml's posting.max_per_day: 1 must actually be enforced."""
    monkeypatch.setenv("IG_ACCESS_TOKEN", "tok")
    monkeypatch.setenv("IG_USER_ID", "ig1")
    conn = db.connect(db_path)
    already_posted_id = db.save_idea(conn, BRIEF, None, "LOW", 90.0)
    db.mark_idea_posted(conn, already_posted_id, "p0")
    second_id = db.save_idea(conn, BRIEF, None, "LOW", 90.0)
    conn.close()

    create = mocker.patch("post.instagram.create_container")
    assert post.publish_idea(second_id, db_path=db_path) is False
    create.assert_not_called()


def test_publish_idea_media_url_override_supplies_missing_media_url(
        db_path, mocker, monkeypatch):
    monkeypatch.setenv("IG_ACCESS_TOKEN", "tok")
    monkeypatch.setenv("IG_USER_ID", "ig1")
    conn = db.connect(db_path)
    idea_id = db.save_idea(conn, {**BRIEF, "media_url": None}, None, "LOW", 90.0)
    conn.close()

    create = mocker.patch("post.instagram.create_container", return_value="c1")
    mocker.patch("post.instagram.publish_container", return_value={"id": "p1"})

    assert post.publish_idea(
        idea_id, db_path=db_path,
        media_url_override="https://mine/override.mp4",
    ) is True
    create.assert_called_once_with("tok", "ig1", "https://mine/override.mp4",
                                   "the caption")


def test_publish_idea_refuses_repost_with_empty_credit_handle(db_path, mocker, monkeypatch):
    monkeypatch.setenv("IG_ACCESS_TOKEN", "tok")
    monkeypatch.setenv("IG_USER_ID", "ig1")
    conn = db.connect(db_path)
    account_id = db.upsert_account(conn, "wineexample")
    post_id = db.upsert_post(conn, {"shortcode": "THEIRS", "account_id": account_id,
                                    "posted_at": "2026-09-05T10:00:00+00:00"})
    # permission_granted=1 but credit_handle is empty string
    conn.execute(
        "INSERT INTO repost_candidates (post_id, permission_granted, credit_handle) "
        "VALUES (?, 1, '')", (post_id,))
    conn.commit()
    idea_id = db.save_idea(conn, {**BRIEF, "repost_of_shortcode": "THEIRS"},
                           None, "LOW", 90.0)
    conn.close()
    create = mocker.patch("post.instagram.create_container")
    assert post.publish_idea(idea_id, db_path=db_path) is False
    create.assert_not_called()
