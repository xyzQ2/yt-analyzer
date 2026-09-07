"""One-time (re-runnable) loader for the starting account list."""

import argparse
import logging
import sys
from pathlib import Path

from src import db

logging.basicConfig(level=logging.INFO, stream=sys.stdout)
logger = logging.getLogger("seed")


def load_seeds(path: str, db_path: str = "data/intelligence.db") -> int:
    """Load `username, category` lines. Blank lines and # comments ignored."""
    conn = db.connect(db_path)
    db.init_schema(conn)
    count = 0
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        username, _, category = line.partition(",")
        # active=None: COALESCE preserves an existing account's activation
        # state (discover.py may have deactivated it since); new rows still
        # default to active via upsert_account's own insert_active fallback.
        db.upsert_account(conn, username.strip().lstrip("@"),
                          category=category.strip() or None, active=None)
        count += 1
    conn.close()
    logger.info("seeded %d accounts", count)
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed the igtt account list")
    parser.add_argument("--file", default="seeds.txt")
    parser.add_argument("--db", default="data/intelligence.db")
    args = parser.parse_args()
    load_seeds(args.file, args.db)


if __name__ == "__main__":
    main()
