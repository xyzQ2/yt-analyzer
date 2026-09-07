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


def test_publish_idea_refuses_missing_media_url(db_path, mocker, monkeypatch):
    monkeypatch.setenv("BLOTATO_API_KEY", "k")
    monkeypatch.setenv("BLOTATO_INSTAGRAM_ACCOUNT_ID", "acct1")
    conn = db.connect(db_path)
    idea_id = db.save_idea(conn, {**BRIEF, "media_url": None}, None, "LOW", 90.0)
    conn.close()
    upload = mocker.patch("post.blotato.upload_media")
    assert post.publish_idea(idea_id, db_path=db_path) is False
    upload.assert_not_called()


def test_publish_idea_refuses_missing_credentials(db_path, mocker, monkeypatch):
    monkeypatch.delenv("BLOTATO_API_KEY", raising=False)
    monkeypatch.delenv("BLOTATO_INSTAGRAM_ACCOUNT_ID", raising=False)
    conn = db.connect(db_path)
    idea_id = db.save_idea(conn, BRIEF, None, "LOW", 90.0)
    conn.close()
    upload = mocker.patch("post.blotato.upload_media")
    assert post.publish_idea(idea_id, db_path=db_path) is False
    upload.assert_not_called()


def test_publish_idea_refuses_repost_without_credit_handle(db_path, mocker, monkeypatch):
    monkeypatch.setenv("BLOTATO_API_KEY", "k")
    monkeypatch.setenv("BLOTATO_INSTAGRAM_ACCOUNT_ID", "acct1")
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
    upload = mocker.patch("post.blotato.upload_media")
    assert post.publish_idea(idea_id, db_path=db_path) is False
    upload.assert_not_called()


def test_publish_idea_refuses_repost_with_empty_credit_handle(db_path, mocker, monkeypatch):
    monkeypatch.setenv("BLOTATO_API_KEY", "k")
    monkeypatch.setenv("BLOTATO_INSTAGRAM_ACCOUNT_ID", "acct1")
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
    upload = mocker.patch("post.blotato.upload_media")
    assert post.publish_idea(idea_id, db_path=db_path) is False
    upload.assert_not_called()
