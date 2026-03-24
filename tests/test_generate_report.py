import json
import os
import tempfile
from pathlib import Path
from src.generate_report import generate_report

SAMPLE_VIDEOS = [
    {
        "id": "v1",
        "title": "Build AI Agents",
        "description": "Tutorial",
        "view_count": 200000,
        "published_at": "2024-03-10T09:00:00Z",
        "transcript": "",
    }
]

SAMPLE_ANALYSIS = {
    "ai_available": True,
    "per_video": [{"video_id": "v1", "topics": ["AI Agents"], "keywords": ["agent"]}],
    "top_topics": [{"topic": "AI Agents", "total_views": 200000}],
    "top_keywords": [{"keyword": "agent", "total_views": 200000}],
    "digest": "Test digest text.",
}


def test_generate_report_creates_file():
    with tempfile.TemporaryDirectory() as tmp:
        output_path = os.path.join(tmp, "report.html")
        generate_report(SAMPLE_VIDEOS, SAMPLE_ANALYSIS, output_path)
        assert Path(output_path).exists()


def test_generate_report_html_contains_chart_js():
    with tempfile.TemporaryDirectory() as tmp:
        output_path = os.path.join(tmp, "report.html")
        generate_report(SAMPLE_VIDEOS, SAMPLE_ANALYSIS, output_path)
        content = Path(output_path).read_text()
        assert "chart.js" in content.lower()


def test_generate_report_html_contains_top_topic():
    with tempfile.TemporaryDirectory() as tmp:
        output_path = os.path.join(tmp, "report.html")
        generate_report(SAMPLE_VIDEOS, SAMPLE_ANALYSIS, output_path)
        content = Path(output_path).read_text()
        assert "AI Agents" in content


def test_generate_report_html_contains_video_title():
    with tempfile.TemporaryDirectory() as tmp:
        output_path = os.path.join(tmp, "report.html")
        generate_report(SAMPLE_VIDEOS, SAMPLE_ANALYSIS, output_path)
        content = Path(output_path).read_text()
        assert "Build AI Agents" in content


def test_generate_report_html_contains_digest():
    with tempfile.TemporaryDirectory() as tmp:
        output_path = os.path.join(tmp, "report.html")
        generate_report(SAMPLE_VIDEOS, SAMPLE_ANALYSIS, output_path)
        content = Path(output_path).read_text()
        assert "Test digest text." in content


def test_generate_report_shows_ai_warning_when_unavailable():
    analysis = {**SAMPLE_ANALYSIS, "ai_available": False, "digest": "AI unavailable fallback."}
    with tempfile.TemporaryDirectory() as tmp:
        output_path = os.path.join(tmp, "report.html")
        generate_report(SAMPLE_VIDEOS, analysis, output_path)
        content = Path(output_path).read_text()
        assert "AI analysis unavailable" in content


def test_generate_report_html_is_valid_structure():
    with tempfile.TemporaryDirectory() as tmp:
        output_path = os.path.join(tmp, "report.html")
        generate_report(SAMPLE_VIDEOS, SAMPLE_ANALYSIS, output_path)
        content = Path(output_path).read_text()
        assert content.strip().startswith("<!DOCTYPE html>")
        assert "</html>" in content
