import pytest

from src import instagram


@pytest.fixture(autouse=True)
def no_sleep(mocker):
    """Polling is real-time in production; tests must not wait on it."""
    mocker.patch("src.instagram.time.sleep")


def _resp(mocker, payload):
    r = mocker.Mock()
    r.status_code = 200
    r.json.return_value = payload
    r.raise_for_status.return_value = None
    return r


def test_create_container_sends_reels_body_for_video(mocker):
    post = mocker.patch("src.instagram.requests.post",
                        return_value=_resp(mocker, {"id": "c1"}))
    mocker.patch("src.instagram.requests.get",
                 return_value=_resp(mocker, {"status_code": "FINISHED"}))

    out = instagram.create_container("tok", "ig1", "https://mine/v.mp4", "cap")

    assert out == "c1"
    assert post.call_args[0][0] == f"{instagram.GRAPH}/ig1/media"
    body = post.call_args[1]["data"]
    assert body["media_type"] == "REELS"
    assert body["video_url"] == "https://mine/v.mp4"
    assert "image_url" not in body
    assert body["caption"] == "cap"
    assert body["access_token"] == "tok"


def test_create_container_sends_image_body_for_photo(mocker):
    post = mocker.patch("src.instagram.requests.post",
                        return_value=_resp(mocker, {"id": "c1"}))
    mocker.patch("src.instagram.requests.get",
                 return_value=_resp(mocker, {"status_code": "FINISHED"}))

    instagram.create_container("tok", "ig1", "https://mine/p.jpg?v=2", "cap")

    body = post.call_args[1]["data"]
    assert body["media_type"] == "IMAGE"
    assert body["image_url"] == "https://mine/p.jpg?v=2"
    assert "video_url" not in body


def test_create_container_waits_until_finished(mocker):
    mocker.patch("src.instagram.requests.post",
                 return_value=_resp(mocker, {"id": "c1"}))
    get = mocker.patch("src.instagram.requests.get", side_effect=[
        _resp(mocker, {"status_code": "IN_PROGRESS"}),
        _resp(mocker, {"status_code": "IN_PROGRESS"}),
        _resp(mocker, {"status_code": "FINISHED"}),
    ])

    assert instagram.create_container("tok", "ig1", "https://mine/v.mp4", "c") == "c1"
    assert get.call_count == 3


def test_create_container_returns_none_when_container_errors(mocker):
    mocker.patch("src.instagram.requests.post",
                 return_value=_resp(mocker, {"id": "c1"}))
    mocker.patch("src.instagram.requests.get",
                 return_value=_resp(mocker, {"status_code": "ERROR"}))

    assert instagram.create_container("tok", "ig1", "https://mine/v.mp4", "c") is None


def test_create_container_gives_up_after_poll_attempts(mocker):
    mocker.patch("src.instagram.requests.post",
                 return_value=_resp(mocker, {"id": "c1"}))
    get = mocker.patch("src.instagram.requests.get",
                       return_value=_resp(mocker, {"status_code": "IN_PROGRESS"}))

    assert instagram.create_container("tok", "ig1", "https://mine/v.mp4", "c") is None
    assert get.call_count == instagram.POLL_ATTEMPTS


def test_create_container_returns_none_on_http_failure(mocker):
    mocker.patch("src.instagram.requests.post", side_effect=Exception("500"))
    get = mocker.patch("src.instagram.requests.get")
    assert instagram.create_container("tok", "ig1", "https://mine/v.mp4", "c") is None
    get.assert_not_called()


def test_create_container_returns_none_when_response_has_no_id(mocker):
    mocker.patch("src.instagram.requests.post",
                 return_value=_resp(mocker, {"error": {"message": "bad token"}}))
    get = mocker.patch("src.instagram.requests.get")
    assert instagram.create_container("tok", "ig1", "https://mine/v.mp4", "c") is None
    get.assert_not_called()


def test_publish_container_posts_creation_id(mocker):
    post = mocker.patch("src.instagram.requests.post",
                        return_value=_resp(mocker, {"id": "p1"}))

    assert instagram.publish_container("tok", "ig1", "c1") == {"id": "p1"}
    assert post.call_args[0][0] == f"{instagram.GRAPH}/ig1/media_publish"
    assert post.call_args[1]["data"] == {"creation_id": "c1", "access_token": "tok"}


def test_publish_container_returns_none_on_failure(mocker):
    mocker.patch("src.instagram.requests.post", side_effect=Exception("timeout"))
    assert instagram.publish_container("tok", "ig1", "c1") is None
