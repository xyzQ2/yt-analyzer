"""Renders the weekly HTML report from analysis data using Jinja2."""

from datetime import date
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

TEMPLATE_DIR = Path(__file__).parent / "templates"
TOP_VIDEOS_COUNT = 20


def _build_top_videos(videos: list[dict], analysis: dict) -> list[dict]:
    """Join per-video analysis tags onto the top 20 videos by view count."""
    tags_by_id = {pv["video_id"]: pv for pv in analysis.get("per_video", [])}
    sorted_videos = sorted(videos, key=lambda v: v["view_count"], reverse=True)[:TOP_VIDEOS_COUNT]
    result = []
    for v in sorted_videos:
        tags = tags_by_id.get(v["id"], {})
        result.append({
            **v,
            "topics": tags.get("topics", []),
            "keywords": tags.get("keywords", []),
        })
    return result


def generate_report(
    videos: list[dict],
    analysis: dict,
    output_path: str | Path,
    channel_handle: str = "@Chase-H-AI",
) -> None:
    """Render HTML report and write to output_path."""
    env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)))
    template = env.get_template("report.html")

    report_date = date.today().isoformat()

    display_handle = f"@{channel_handle.lstrip('@')}"

    top_videos = _build_top_videos(videos, analysis)

    topics_data = [
        {"label": t["topic"], "value": t["total_views"]}
        for t in analysis.get("top_topics", [])[:10]
    ]
    keywords_data = [
        {"label": k["keyword"], "value": k["total_views"]}
        for k in analysis.get("top_keywords", [])[:20]
    ]
    # x is ISO 8601 date string (YYYY-MM-DD), parsed by chartjs-adapter-date-fns on type:'time' axis
    scatter_data = [
        {
            "x": v["published_at"][:10],
            "y": v["view_count"],
            "title": v["title"],
        }
        for v in videos
    ]

    html = template.render(
        channel_handle=display_handle,
        report_date=report_date,
        total_videos=len(videos),
        ai_available=analysis.get("ai_available", True),
        top_videos=top_videos,
        topics_data=topics_data,
        keywords_data=keywords_data,
        scatter_data=scatter_data,
        digest=analysis.get("digest", ""),
    )

    Path(output_path).write_text(html, encoding="utf-8")
