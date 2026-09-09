"""Instagram Graph API publishing.

Replaces Blotato: free, official, no third-party vendor holding the credentials.
Publishing is a two-step dance — create a media container, wait for Instagram to
finish fetching and transcoding it, then publish that container.

The container step needs a publicly reachable HTTPS `media_url`; Instagram pulls
the file itself. There is no upload endpoint to hand bytes to.
"""

import logging
import time

import requests

logger = logging.getLogger(__name__)

GRAPH = "https://graph.instagram.com/v23.0"
TIMEOUT = 120

# Meta recommends polling a container once per minute for no more than 5 minutes.
POLL_INTERVAL = 20
POLL_ATTEMPTS = 15

VIDEO_EXTENSIONS = (".mp4", ".mov")


def _media_type(media_url: str) -> str:
    """REELS for video, IMAGE otherwise.

    ponytail: extension sniffing. Add an explicit brief field if a URL without a
    file extension ever shows up.
    """
    path = media_url.split("?", 1)[0].lower()
    return "REELS" if path.endswith(VIDEO_EXTENSIONS) else "IMAGE"


def _log_failure(what: str, exc: Exception, resp) -> None:
    """Graph API errors are opaque without the body, so log it when we have one."""
    body = getattr(resp, "text", None)
    logger.error("instagram %s failed: %s%s", what, exc,
                 f" — {body}" if body else "")


def create_container(access_token: str, ig_user_id: str, media_url: str,
                     caption: str):
    """Create a media container and wait for it to finish. Container id, or None."""
    media_type = _media_type(media_url)
    params = {
        "caption": caption,
        "media_type": media_type,
        "access_token": access_token,
    }
    params["video_url" if media_type == "REELS" else "image_url"] = media_url

    resp = None
    try:
        resp = requests.post(f"{GRAPH}/{ig_user_id}/media", data=params,
                             timeout=TIMEOUT)
        resp.raise_for_status()
        container_id = resp.json().get("id")
    except Exception as exc:
        _log_failure("container creation", exc, resp)
        return None

    if not container_id:
        logger.error("instagram container creation returned no id")
        return None

    if not _wait_for_container(access_token, container_id):
        return None
    return container_id


def _wait_for_container(access_token: str, container_id: str) -> bool:
    """Poll until FINISHED. False on ERROR, EXPIRED, or running out of attempts."""
    for attempt in range(POLL_ATTEMPTS):
        resp = None
        try:
            resp = requests.get(
                f"{GRAPH}/{container_id}",
                params={"fields": "status_code", "access_token": access_token},
                timeout=TIMEOUT)
            resp.raise_for_status()
            status = resp.json().get("status_code")
        except Exception as exc:
            _log_failure("container status check", exc, resp)
            return False

        if status == "FINISHED":
            return True
        if status in ("ERROR", "EXPIRED"):
            logger.error("instagram container %s is %s", container_id, status)
            return False

        if attempt < POLL_ATTEMPTS - 1:
            time.sleep(POLL_INTERVAL)

    logger.error("instagram container %s still not FINISHED after %d checks",
                 container_id, POLL_ATTEMPTS)
    return False


def publish_container(access_token: str, ig_user_id: str, container_id: str):
    """Publish a finished container. The response dict, or None on failure."""
    resp = None
    try:
        resp = requests.post(f"{GRAPH}/{ig_user_id}/media_publish",
                             data={"creation_id": container_id,
                                   "access_token": access_token},
                             timeout=TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        _log_failure("publish", exc, resp)
        return None
