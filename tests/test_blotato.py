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
