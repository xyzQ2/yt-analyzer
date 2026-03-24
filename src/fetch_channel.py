"""YouTube Data API v3 client for channel video and transcript fetching."""

from googleapiclient.discovery import build
from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled, NoTranscriptFound

TRANSCRIPT_TOP_N = 30
PLAYLIST_PAGE_SIZE = 50
VIDEOS_BATCH_SIZE = 50


def get_channel_id(youtube, handle: str) -> str:
    """Resolve a channel handle to a channel ID. Strips leading @ if present."""
    clean_handle = handle.lstrip("@")
    resp = youtube.channels().list(part="id", forHandle=clean_handle).execute()
    items = resp.get("items", [])
    if not items:
        raise ValueError(f"Channel not found for handle: @{clean_handle}")
    return items[0]["id"]


def get_all_videos(youtube, channel_id: str) -> list[dict]:
    """Fetch all public videos from a channel's uploads playlist."""
    ch_resp = youtube.channels().list(part="contentDetails", id=channel_id).execute()
    uploads_id = ch_resp["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]

    video_ids = []
    page_token = None
    while True:
        kwargs = dict(part="snippet", playlistId=uploads_id, maxResults=PLAYLIST_PAGE_SIZE)
        if page_token:
            kwargs["pageToken"] = page_token
        resp = youtube.playlistItems().list(**kwargs).execute()
        for item in resp.get("items", []):
            video_ids.append(item["snippet"]["resourceId"]["videoId"])
        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    videos = []
    for i in range(0, len(video_ids), VIDEOS_BATCH_SIZE):
        batch = video_ids[i : i + VIDEOS_BATCH_SIZE]
        resp = youtube.videos().list(part="snippet,statistics", id=",".join(batch)).execute()
        for item in resp.get("items", []):
            videos.append({
                "id": item["id"],
                "title": item["snippet"]["title"],
                "description": item["snippet"].get("description", ""),
                "view_count": int(item["statistics"].get("viewCount", 0)),
                "published_at": item["snippet"]["publishedAt"],
            })
    return videos


def fetch_transcripts(videos: list[dict], top_n: int = TRANSCRIPT_TOP_N) -> list[dict]:
    """Add 'transcript' key to each video; fetch only for top N by view_count."""
    ranked_ids = {
        v["id"]
        for v in sorted(videos, key=lambda x: x["view_count"], reverse=True)[:top_n]
    }
    for video in videos:
        if video["id"] in ranked_ids:
            try:
                segments = YouTubeTranscriptApi.get_transcript(video["id"])
                video["transcript"] = " ".join(s["text"] for s in segments)
            except (TranscriptsDisabled, NoTranscriptFound, Exception):
                video["transcript"] = ""
        else:
            video["transcript"] = ""
    return videos


def fetch_channel_videos(api_key: str, channel_handle: str) -> list[dict]:
    """Main entry point: fetch all videos + transcripts for a channel handle."""
    youtube = build("youtube", "v3", developerKey=api_key)
    channel_id = get_channel_id(youtube, channel_handle)
    videos = get_all_videos(youtube, channel_id)
    videos = fetch_transcripts(videos)
    return videos
