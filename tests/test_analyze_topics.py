import json
import pytest
from unittest.mock import MagicMock, patch
from src.analyze_topics import (
    format_videos_for_prompt,
    fallback_analysis,
    analyze_videos,
)

SAMPLE_VIDEOS = [
    {
        "id": "v1",
        "title": "Build AI Agents with LangChain",
        "description": "Tutorial on AI agents",
        "view_count": 200000,
        "published_at": "2024-01-01T00:00:00Z",
        "transcript": "Building AI agents with LangChain tools and memory.",
    },
    {
        "id": "v2",
        "title": "Prompt Engineering Guide",
        "description": "Prompt techniques for GPT-4",
        "view_count": 100000,
        "published_at": "2024-02-01T00:00:00Z",
        "transcript": "Prompt engineering is critical for language model performance.",
    },
]

MOCK_CLAUDE_RESPONSE = {
    "per_video": [
        {"video_id": "v1", "topics": ["AI Agents", "LangChain"], "keywords": ["agent", "langchain", "tools"]},
        {"video_id": "v2", "topics": ["Prompt Engineering"], "keywords": ["prompt", "gpt-4", "language model"]},
    ],
    "top_topics": [
        {"topic": "AI Agents", "total_views": 200000},
        {"topic": "Prompt Engineering", "total_views": 100000},
    ],
    "top_keywords": [
        {"keyword": "agent", "total_views": 200000},
        {"keyword": "prompt", "total_views": 100000},
    ],
    "digest": "The channel's highest-performing content centers on AI agents and prompt engineering.",
}


# --- format_videos_for_prompt ---

def test_format_videos_for_prompt_includes_title_and_views():
    text = format_videos_for_prompt(SAMPLE_VIDEOS)
    assert "Build AI Agents with LangChain" in text
    assert "200000" in text


def test_format_videos_for_prompt_includes_transcript():
    text = format_videos_for_prompt(SAMPLE_VIDEOS)
    assert "LangChain tools and memory" in text


# --- fallback_analysis ---

def test_fallback_analysis_returns_required_keys():
    result = fallback_analysis(SAMPLE_VIDEOS)
    assert "per_video" in result
    assert "top_topics" in result
    assert "top_keywords" in result
    assert "digest" in result
    assert result["ai_available"] is False


def test_fallback_analysis_top_keywords_sorted_by_views():
    result = fallback_analysis(SAMPLE_VIDEOS)
    views = [kw["total_views"] for kw in result["top_keywords"]]
    assert views == sorted(views, reverse=True)


def test_fallback_analysis_per_video_has_all_ids():
    result = fallback_analysis(SAMPLE_VIDEOS)
    ids = {v["video_id"] for v in result["per_video"]}
    assert ids == {"v1", "v2"}


# --- analyze_videos ---

def test_analyze_videos_returns_claude_result_when_available():
    mock_client = MagicMock()
    mock_client.messages.create.return_value.content = [
        MagicMock(text=json.dumps(MOCK_CLAUDE_RESPONSE))
    ]
    with patch("src.analyze_topics.anthropic.Anthropic", return_value=mock_client):
        result = analyze_videos(SAMPLE_VIDEOS, api_key="fake-key")
    assert result["ai_available"] is True
    assert result["top_topics"][0]["topic"] == "AI Agents"


def test_analyze_videos_falls_back_when_claude_raises():
    mock_client = MagicMock()
    mock_client.messages.create.side_effect = Exception("API error")
    with patch("src.analyze_topics.anthropic.Anthropic", return_value=mock_client):
        result = analyze_videos(SAMPLE_VIDEOS, api_key="fake-key")
    assert result["ai_available"] is False


def test_analyze_videos_falls_back_when_no_api_key():
    result = analyze_videos(SAMPLE_VIDEOS, api_key="")
    assert result["ai_available"] is False


def test_analyze_videos_chunks_large_payloads():
    """With TOKEN_CHUNK_SIZE set low, large payloads should still return merged result."""
    videos = [
        {
            "id": f"v{i}",
            "title": f"Video {i}",
            "description": "desc",
            "view_count": 1000 * i,
            "published_at": "2024-01-01T00:00:00Z",
            "transcript": "x" * 100,
        }
        for i in range(10)
    ]
    mock_client = MagicMock()
    mock_client.messages.create.return_value.content = [
        MagicMock(text=json.dumps({
            "per_video": [],
            "top_topics": [{"topic": "T", "total_views": 1000}],
            "top_keywords": [{"keyword": "k", "total_views": 1000}],
            "digest": "summary",
        }))
    ]
    with patch("src.analyze_topics.anthropic.Anthropic", return_value=mock_client), \
         patch("src.analyze_topics.TOKEN_CHUNK_SIZE", 10):
        result = analyze_videos(videos, api_key="fake-key")
    assert result["ai_available"] is True
    assert mock_client.messages.create.call_count > 1
