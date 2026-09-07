"""Blotato publishing. Chosen over the Instagram Graph API to skip Meta app review."""

import logging

import requests

logger = logging.getLogger(__name__)

MEDIA_URL = "https://backend.blotato.com/v2/media"
POSTS_URL = "https://backend.blotato.com/v2/posts"
TIMEOUT = 120


def _headers(api_key: str) -> dict:
    return {"blotato-api-key": api_key, "Content-Type": "application/json"}


def upload_media(api_key: str, url: str):
    """Hand Blotato a source URL, get back a hosted one. None on failure."""
    try:
        resp = requests.post(MEDIA_URL, headers=_headers(api_key),
                             json={"url": url}, timeout=TIMEOUT)
        resp.raise_for_status()
        return resp.json().get("url")
    except Exception as exc:
        logger.error("blotato media upload failed for %s: %s", url, exc)
        return None


def publish_instagram(api_key: str, account_id: str, text: str, media_url: str):
    """Publish one Instagram post. None on failure."""
    body = {
        "post": {
            "target": {"targetType": "instagram"},
            "content": {"text": text, "platform": "instagram",
                        "mediaUrls": [media_url]},
            "accountId": account_id,
        }
    }
    try:
        resp = requests.post(POSTS_URL, headers=_headers(api_key), json=body,
                             timeout=TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        logger.error("blotato publish failed: %s", exc)
        return None
