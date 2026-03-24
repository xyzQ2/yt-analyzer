"""YouTube Data API v3 client — stub."""

def get_channel_id(youtube, handle: str) -> str:
    raise NotImplementedError

def get_all_videos(youtube, channel_id: str) -> list:
    raise NotImplementedError

def fetch_transcripts(videos: list, top_n: int = 30) -> list:
    raise NotImplementedError

def fetch_channel_videos(api_key: str, channel_handle: str) -> list:
    raise NotImplementedError
