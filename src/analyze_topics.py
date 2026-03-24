"""Claude API topic/keyword extractor with rake-nltk fallback."""

import json
import re
from collections import defaultdict

import anthropic
from rake_nltk import Rake

# Rough token limit before chunking (chars/4 ≈ tokens; 80k tokens ≈ 320k chars)
TOKEN_CHUNK_SIZE = 320_000
TOP_N_VIDEOS = 50
CLAUDE_MODEL = "claude-sonnet-4-6"

SYSTEM_PROMPT = (
    "You are an expert YouTube content analyst. "
    "Return ONLY valid JSON — no markdown, no explanation."
)

USER_PROMPT_TEMPLATE = """Analyze these YouTube videos and return a JSON object with exactly these keys:
- "per_video": array of {{"video_id": str, "topics": [str], "keywords": [str]}}
- "top_topics": array of {{"topic": str, "total_views": int}} sorted descending by total_views
- "top_keywords": array of {{"keyword": str, "total_views": int}} sorted descending by total_views
- "digest": a ~200-word narrative summary of the channel's highest-performing content patterns

"top_topics" and "top_keywords" must aggregate view counts across all videos that share a topic/keyword.

Videos:
{videos_text}"""


def format_videos_for_prompt(videos: list[dict]) -> str:
    lines = []
    for v in videos:
        lines.append(
            f"ID: {v['id']}\n"
            f"Title: {v['title']}\n"
            f"Views: {v['view_count']}\n"
            f"Published: {v['published_at']}\n"
            f"Description: {v['description'][:300]}\n"
            f"Transcript: {v.get('transcript', '')[:500]}\n"
            "---"
        )
    return "\n".join(lines)


def _call_claude(client, videos: list[dict]) -> dict:
    videos_text = format_videos_for_prompt(videos)
    prompt = USER_PROMPT_TEMPLATE.format(videos_text=videos_text)
    resp = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = resp.content[0].text
    # Strip markdown code fences if present
    raw = re.sub(r"^```(?:json)?\n?", "", raw.strip())
    raw = re.sub(r"\n?```$", "", raw)
    return json.loads(raw)


def _merge_chunks(chunks: list[dict], all_videos: list[dict]) -> dict:
    """Merge per-video results from multiple Claude calls; re-aggregate top lists.

    Digest: taken from the last chunk only (each chunk covers a different set of
    videos; the final chunk's digest is used as a closing summary).
    """
    per_video = []
    topic_views: dict[str, int] = defaultdict(int)
    kw_views: dict[str, int] = defaultdict(int)
    view_by_id = {v["id"]: v["view_count"] for v in all_videos}

    for chunk in chunks:
        per_video.extend(chunk.get("per_video", []))

    for pv in per_video:
        views = view_by_id.get(pv["video_id"], 0)
        for topic in pv.get("topics", []):
            topic_views[topic] += views
        for kw in pv.get("keywords", []):
            kw_views[kw] += views

    top_topics = sorted(
        [{"topic": t, "total_views": v} for t, v in topic_views.items()],
        key=lambda x: x["total_views"],
        reverse=True,
    )
    top_keywords = sorted(
        [{"keyword": k, "total_views": v} for k, v in kw_views.items()],
        key=lambda x: x["total_views"],
        reverse=True,
    )
    # Use last chunk's digest as the overall summary
    digest = chunks[-1].get("digest", "Analysis complete.") if chunks else ""
    return {"per_video": per_video, "top_topics": top_topics, "top_keywords": top_keywords, "digest": digest}


def fallback_analysis(videos: list[dict]) -> dict:
    """rake-nltk keyword extraction when Claude is unavailable."""
    rake = Rake()
    per_video = []
    kw_views: dict[str, int] = defaultdict(int)

    for v in videos:
        text = f"{v['title']} {v['description']} {v.get('transcript', '')}"
        rake.extract_keywords_from_text(text)
        keywords = [kw.lower() for kw in rake.get_ranked_phrases()[:10]]
        for kw in keywords:
            kw_views[kw] += v["view_count"]
        per_video.append({"video_id": v["id"], "topics": keywords[:3], "keywords": keywords})

    top_keywords = sorted(
        [{"keyword": k, "total_views": v} for k, v in kw_views.items()],
        key=lambda x: x["total_views"],
        reverse=True,
    )[:20]
    top_topics = [{"topic": kw["keyword"], "total_views": kw["total_views"]} for kw in top_keywords[:10]]

    return {
        "per_video": per_video,
        "top_topics": top_topics,
        "top_keywords": top_keywords,
        "digest": "AI analysis unavailable — keywords extracted via RAKE algorithm from titles and descriptions.",
        "ai_available": False,
    }


def analyze_videos(videos: list[dict], api_key: str) -> dict:
    """Main entry point. Sends top 50 videos to Claude; falls back to rake-nltk on error."""
    top_videos = sorted(videos, key=lambda v: v["view_count"], reverse=True)[:TOP_N_VIDEOS]

    if not api_key:
        return fallback_analysis(top_videos)

    try:
        client = anthropic.Anthropic(api_key=api_key)
        prompt_text = format_videos_for_prompt(top_videos)

        if len(prompt_text) <= TOKEN_CHUNK_SIZE:
            result = _call_claude(client, top_videos)
            chunks = [result]
        else:
            # Split into variable-size chunks that each fit within TOKEN_CHUNK_SIZE
            chunks = []
            chunk: list[dict] = []
            chunk_size = 0
            for v in top_videos:
                v_text = format_videos_for_prompt([v])
                if chunk and chunk_size + len(v_text) > TOKEN_CHUNK_SIZE:
                    chunks.append(_call_claude(client, chunk))
                    chunk = []
                    chunk_size = 0
                chunk.append(v)
                chunk_size += len(v_text)
            if chunk:
                chunks.append(_call_claude(client, chunk))

        merged = _merge_chunks(chunks, top_videos)
        merged["ai_available"] = True
        return merged

    except Exception:
        return fallback_analysis(top_videos)
