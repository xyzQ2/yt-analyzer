"""Main orchestrator — runs the full pipeline or dry-run from fixture."""

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

from src.fetch_channel import fetch_channel_videos
from src.analyze_topics import analyze_videos
from src.generate_report import generate_report


def main() -> None:
    parser = argparse.ArgumentParser(description="YouTube Channel Analyzer")
    parser.add_argument("--dry-run", action="store_true", help="Load fixture instead of calling APIs")
    parser.add_argument("--output-dir", default="reports", help="Directory to write the HTML report into")
    args = parser.parse_args()

    load_dotenv()

    handle = os.getenv("CHANNEL_HANDLE", "Chase-H-AI")

    if args.dry_run:
        fixture_path = Path("tests/fixtures/sample_channel.json")
        videos = json.loads(fixture_path.read_text())["videos"]
        print(f"[dry-run] Loaded {len(videos)} videos from fixture.")
    else:
        api_key = os.environ.get("YOUTUBE_API_KEY")
        if not api_key:
            print("ERROR: YOUTUBE_API_KEY not set.", file=sys.stderr)
            sys.exit(1)
        print(f"Fetching videos for @{handle}...")
        videos = fetch_channel_videos(api_key, handle)
        print(f"Fetched {len(videos)} videos.")

    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")
    print("Analyzing topics and keywords...")
    analysis = analyze_videos(videos, anthropic_key)

    if analysis.get("ai_available"):
        print("Claude analysis complete.")
    else:
        print("Warning: Claude unavailable — using RAKE fallback.")

    today = date.today().isoformat()
    # Derive filename from channel handle: strip @, lowercase, replace spaces with -
    slug = handle.lstrip("@").lower().replace(" ", "-")
    output_dir = Path(args.output_dir)
    output_dir.mkdir(exist_ok=True)
    output_path = str(output_dir / f"{today}-{slug}.html")
    generate_report(videos, analysis, output_path, channel_handle=handle)
    print(f"Report written to {output_path}")


if __name__ == "__main__":
    main()
