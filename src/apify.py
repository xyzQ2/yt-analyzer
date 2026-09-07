"""Apify adapter. The only module in the project that knows scraping exists."""

import logging

import requests

logger = logging.getLogger(__name__)

ACTOR_URL = ("https://api.apify.com/v2/acts/apify~instagram-scraper/"
             "run-sync-get-dataset-items")
TIMEOUT = 600


def normalize_post(raw: dict) -> dict | None:
    """Map one Apify dataset item to the project's post shape.

    Returns None for items with no shortCode. A metric the platform does not
    report stays None; it never becomes 0.
    """
    shortcode = raw.get("shortCode")
    if not shortcode:
        logger.debug("dropping item with no shortCode")
        return None

    views = raw.get("videoPlayCount") or raw.get("videoViewCount")

    return {
        "platform": "instagram",
        "shortcode": shortcode,
        "username": raw.get("ownerUsername"),
        "owner_followers": raw.get("ownerFollowersCount"),
        "url": raw.get("url"),
        "video_url": raw.get("videoUrl"),
        "thumbnail_url": raw.get("displayUrl"),
        "caption": raw.get("caption"),
        "content_type": raw.get("type"),
        "posted_at": raw.get("timestamp"),
        "duration_sec": raw.get("videoDuration"),
        "views": views,
        "likes": raw.get("likesCount"),
        "comments": raw.get("commentsCount"),
        "shares": None,  # Instagram does not expose share counts publicly
    }


def fetch_profile_posts(token: str, usernames: list[str], lookback_days: int,
                        results_limit: int) -> list[dict]:
    """Fetch recent posts for the given usernames. Returns [] on any failure."""
    if not usernames:
        return []

    body = {
        "directUrls": [f"https://www.instagram.com/{u}/" for u in usernames],
        "resultsType": "posts",
        "resultsLimit": results_limit,
        "onlyPostsNewerThan": f"{lookback_days} days",
        "addParentData": False,
    }
    try:
        resp = requests.post(
            ACTOR_URL,
            headers={"Authorization": f"Bearer {token}"},
            json=body,
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        items = resp.json()
    except Exception as exc:
        logger.error("apify fetch failed for %d accounts: %s", len(usernames), exc)
        return []

    posts = [p for p in (normalize_post(i) for i in items) if p]
    logger.info("apify returned %d items, %d usable posts", len(items), len(posts))
    return posts
