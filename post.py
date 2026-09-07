"""Publish one approved idea. Invoked by hand or by the post.yml workflow."""

import argparse
import json
import logging
import os
import sys

from src import blotato, db
from src.config import load_config

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                    stream=sys.stdout)
logger = logging.getLogger("post")


def publish_idea(idea_id: int, config_path: str = "config.yaml",
                 db_path: str = "data/intelligence.db") -> bool:
    load_config(config_path)
    conn = db.connect(db_path)

    idea = db.get_idea(conn, idea_id)
    if idea is None:
        logger.error("no idea with id %s", idea_id)
        return False
    if idea["status"] == "posted":
        logger.error("idea %s was already posted as %s", idea_id,
                     idea["posted_shortcode"])
        return False
    if str(idea["similarity_risk"]).upper() == "HIGH":
        logger.error("refusing to publish idea %s: HIGH similarity risk", idea_id)
        return False

    brief = json.loads(idea["brief_json"])

    repost_of = brief.get("repost_of_shortcode")
    if repost_of:
        permission = db.repost_permission(conn, repost_of)
        if not permission or not permission["permission_granted"] \
                or not permission["credit_handle"]:
            logger.error("refusing to repost %s: no recorded permission and credit "
                         "handle", repost_of)
            return False

    media_url = brief.get("media_url")
    if not media_url:
        logger.error("idea %s has no media_url — add the finished video's URL to the "
                     "brief before publishing", idea_id)
        return False

    api_key = os.environ.get("BLOTATO_API_KEY", "")
    account_id = os.environ.get("BLOTATO_INSTAGRAM_ACCOUNT_ID", "")
    if not api_key or not account_id:
        logger.error("BLOTATO_API_KEY and BLOTATO_INSTAGRAM_ACCOUNT_ID must be set")
        return False

    hosted = blotato.upload_media(api_key, media_url)
    if not hosted:
        return False

    result = blotato.publish_instagram(api_key, account_id,
                                       brief.get("caption", ""), hosted)
    if not result:
        return False

    shortcode = result.get("shortcode") or result.get("id") or "unknown"
    db.mark_idea_posted(conn, idea_id, shortcode)
    logger.info("published idea %s as %s", idea_id, shortcode)
    conn.close()
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Publish one approved igtt idea")
    parser.add_argument("idea_id", type=int)
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--db", default="data/intelligence.db")
    args = parser.parse_args()
    if not publish_idea(args.idea_id, args.config, args.db):
        sys.exit(1)


if __name__ == "__main__":
    main()
