import os
import tempfile
from pathlib import Path
import pytest
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


@pytest.fixture
def report_content(tmp_path):
    output_path = tmp_path / "report.html"
    generate_report(SAMPLE_VIDEOS, SAMPLE_ANALYSIS, output_path)
    return output_path.read_text()


def test_generate_report_creates_file(tmp_path):
    output_path = tmp_path / "report.html"
    generate_report(SAMPLE_VIDEOS, SAMPLE_ANALYSIS, output_path)
    assert output_path.exists()


def test_generate_report_html_contains_chart_js(report_content):
    assert "chart.js" in report_content.lower()


def test_generate_report_html_contains_top_topic(report_content):
    assert "AI Agents" in report_content


def test_generate_report_html_contains_video_title(report_content):
    assert "Build AI Agents" in report_content


def test_generate_report_html_contains_digest(report_content):
    assert "Test digest text." in report_content


def test_generate_report_shows_ai_warning_when_unavailable(tmp_path):
    analysis = {**SAMPLE_ANALYSIS, "ai_available": False, "digest": "AI unavailable fallback."}
    output_path = tmp_path / "report.html"
    generate_report(SAMPLE_VIDEOS, analysis, output_path)
    content = output_path.read_text()
    assert "AI analysis unavailable" in content


def test_generate_report_html_is_valid_structure(report_content):
    assert report_content.strip().startswith("<!DOCTYPE html>")
    assert "</html>" in report_content
