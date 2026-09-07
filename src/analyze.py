"""AI analysis. Claude handles text; Gemini handles video (see analyze_video)."""

import json
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

PROMPT_DIR = Path(__file__).parent.parent / "prompts"
MAX_ATTEMPTS = 2

TEXT_REQUIRED_KEYS = {
    "hook", "hook_type", "payoff", "emotional_driver", "social_driver",
    "comment_driver", "rewatch_driver", "visual_structure", "caption_role",
    "audience", "timing", "why_it_overperformed", "reusable_pattern",
    "scores", "ai_virality_score",
}

_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def load_prompt(name: str) -> str:
    return (PROMPT_DIR / f"{name}.md").read_text(encoding="utf-8")


def extract_json(text: str):
    """Parse a JSON object out of a model response. None if there isn't one."""
    if not text:
        return None
    candidate = text.strip()
    fenced = _FENCE.search(candidate)
    if fenced:
        candidate = fenced.group(1)
    start, end = candidate.find("{"), candidate.rfind("}")
    if start == -1 or end == -1:
        return None
    try:
        return json.loads(candidate[start:end + 1])
    except json.JSONDecodeError:
        return None


def _call_claude(client, model: str, prompt: str, max_tokens: int = 2000):
    resp = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(block.text for block in resp.content if hasattr(block, "text"))


def analyze_text(client, post: dict, brand: dict, model: str):
    """Tier 1 strategist analysis of one post. None on any failure."""
    payload = {k: post.get(k) for k in (
        "shortcode", "username", "caption", "content_type", "posted_at",
        "duration_sec", "views", "likes", "comments", "owner_followers",
        "performance_score",
    )}
    prompt = load_prompt("analyze_text").format(
        brand_name=brand.get("name", ""),
        brand_voice=brand.get("voice", ""),
        post_json=json.dumps(payload, indent=2, default=str),
    )

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            raw = _call_claude(client, model, prompt)
        except Exception as exc:
            logger.error("claude text analysis failed for %s: %s",
                         post.get("shortcode"), exc)
            return None
        data = extract_json(raw)
        if data and TEXT_REQUIRED_KEYS <= set(data):
            return data
        logger.warning("bad text analysis for %s (attempt %d/%d)",
                       post.get("shortcode"), attempt, MAX_ATTEMPTS)
    return None
