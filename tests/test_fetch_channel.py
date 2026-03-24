import pytest
from unittest.mock import MagicMock, patch
from src.fetch_channel import get_channel_id, get_all_videos, fetch_transcripts, fetch_channel_videos


# --- get_channel_id ---

def make_channels_mock(items):
    yt = MagicMock()
    yt.channels.return_value.list.return_value.execute.return_value = {"items": items}
    return yt


def test_get_channel_id_success():
    yt = make_channels_mock([{"id": "UCabc123"}])
    assert get_channel_id(yt, "Chase-H-AI") == "UCabc123"


def test_get_channel_id_strips_at_prefix():
    """Handle passed with @ should work the same as without."""
    yt = make_channels_mock([{"id": "UCabc123"}])
    assert get_channel_id(yt, "@Chase-H-AI") == "UCabc123"


def test_get_channel_id_not_found_raises():
    yt = make_channels_mock([])
    with pytest.raises(ValueError, match="Channel not found"):
        get_channel_id(yt, "no-such-handle")


# --- get_all_videos ---

def make_playlist_mock(pages):
    """pages: list of lists of items. Each page after the last has no nextPageToken."""
    yt = MagicMock()
    yt.channels.return_value.list.return_value.execute.return_value = {
        "items": [{"contentDetails": {"relatedPlaylists": {"uploads": "PLabc"}}}]
    }
    responses = []
    for i, page_items in enumerate(pages):
        resp = {"items": page_items}
        if i < len(pages) - 1:
            resp["nextPageToken"] = f"token{i}"
        responses.append(resp)
    yt.playlistItems.return_value.list.return_value.execute.side_effect = responses

    def videos_list(**kwargs):
        mock = MagicMock()
        ids = kwargs.get("id", "").split(",")
        mock.execute.return_value = {
            "items": [
                {
                    "id": vid_id,
                    "snippet": {"title": f"Title {vid_id}", "description": f"Desc {vid_id}", "publishedAt": "2024-01-01T00:00:00Z"},
                    "statistics": {"viewCount": "1000"},
                }
                for vid_id in ids
            ]
        }
        return mock

    yt.videos.return_value.list.side_effect = videos_list
    return yt


def test_get_all_videos_single_page():
    yt = make_playlist_mock([[{"snippet": {"resourceId": {"videoId": "v1"}}}]])
    videos = get_all_videos(yt, "UCabc")
    assert len(videos) == 1
    assert videos[0]["id"] == "v1"
    assert videos[0]["view_count"] == 1000


def test_get_all_videos_multi_page():
    pages = [
        [{"snippet": {"resourceId": {"videoId": f"v{i}"}}} for i in range(3)],
        [{"snippet": {"resourceId": {"videoId": f"v{i}"}}} for i in range(3, 5)],
    ]
    yt = make_playlist_mock(pages)
    assert len(get_all_videos(yt, "UCabc")) == 5


def test_get_all_videos_includes_required_fields():
    yt = make_playlist_mock([[{"snippet": {"resourceId": {"videoId": "v1"}}}]])
    v = get_all_videos(yt, "UCabc")[0]
    for field in ("id", "title", "description", "view_count", "published_at"):
        assert field in v, f"Missing field: {field}"


# --- fetch_transcripts ---

def test_fetch_transcripts_adds_transcript_to_top_n_by_view_count():
    """Only the top N videos by view_count should get transcripts."""
    videos = [
        {"id": f"v{i}", "view_count": 100 - i, "title": f"T{i}", "description": "", "published_at": "2024-01-01T00:00:00Z"}
        for i in range(5)
    ]
    with patch("src.fetch_channel.YouTubeTranscriptApi.get_transcript") as mock_t:
        mock_t.return_value = [{"text": "hello world", "start": 0.0, "duration": 1.0}]
        result = fetch_transcripts(videos, top_n=3)

    top3_ids = {v["id"] for v in sorted(videos, key=lambda v: v["view_count"], reverse=True)[:3]}
    for v in result:
        if v["id"] in top3_ids:
            assert v["transcript"] == "hello world"
        else:
            assert v["transcript"] == ""


def test_fetch_transcripts_skips_transcripts_disabled():
    from youtube_transcript_api import TranscriptsDisabled
    videos = [{"id": "v1", "view_count": 999, "title": "T", "description": "", "published_at": "2024-01-01T00:00:00Z"}]
    with patch("src.fetch_channel.YouTubeTranscriptApi.get_transcript", side_effect=TranscriptsDisabled("v1")):
        result = fetch_transcripts(videos, top_n=1)
    assert result[0]["transcript"] == ""


def test_fetch_transcripts_skips_no_transcript_found():
    from youtube_transcript_api import NoTranscriptFound
    videos = [{"id": "v1", "view_count": 999, "title": "T", "description": "", "published_at": "2024-01-01T00:00:00Z"}]
    with patch("src.fetch_channel.YouTubeTranscriptApi.get_transcript", side_effect=NoTranscriptFound("v1", [], [])):
        result = fetch_transcripts(videos, top_n=1)
    assert result[0]["transcript"] == ""


def test_fetch_transcripts_skips_generic_exception():
    videos = [{"id": "v1", "view_count": 999, "title": "T", "description": "", "published_at": "2024-01-01T00:00:00Z"}]
    with patch("src.fetch_channel.YouTubeTranscriptApi.get_transcript", side_effect=Exception("network error")):
        result = fetch_transcripts(videos, top_n=1)
    assert result[0]["transcript"] == ""


# --- fetch_channel_videos integration ---

def test_fetch_channel_videos_returns_list_with_transcripts():
    with patch("src.fetch_channel.build") as mock_build, \
         patch("src.fetch_channel.YouTubeTranscriptApi.get_transcript") as mock_t:

        yt = MagicMock()
        mock_build.return_value = yt

        yt.channels.return_value.list.return_value.execute.side_effect = [
            {"items": [{"id": "UCtest"}]},
            {"items": [{"contentDetails": {"relatedPlaylists": {"uploads": "PL"}}}]},
        ]
        yt.playlistItems.return_value.list.return_value.execute.return_value = {
            "items": [{"snippet": {"resourceId": {"videoId": "v1"}}}]
        }
        yt.videos.return_value.list.return_value.execute.return_value = {
            "items": [{"id": "v1", "snippet": {"title": "T", "description": "D", "publishedAt": "2024-01-01T00:00:00Z"}, "statistics": {"viewCount": "500"}}]
        }
        mock_t.return_value = [{"text": "transcript text", "start": 0.0, "duration": 1.0}]

        videos = fetch_channel_videos("fake-key", "Chase-H-AI")

    assert len(videos) == 1
    assert videos[0]["view_count"] == 500
    assert "transcript" in videos[0]
