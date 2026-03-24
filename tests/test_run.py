import subprocess
import sys
import tempfile
import os
from pathlib import Path


def test_dry_run_produces_html_report(tmp_path):
    """End-to-end: --dry-run should create an HTML report file."""
    result = subprocess.run(
        [sys.executable, "run.py", "--dry-run", "--output-dir", str(tmp_path)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"run.py failed:\n{result.stderr}"

    reports = list(tmp_path.glob("*.html"))
    assert len(reports) == 1, f"Expected 1 HTML file in {tmp_path}, found: {reports}"

    content = reports[0].read_text()
    assert "<!DOCTYPE html>" in content
    assert "Chase-H-AI" in content
    assert "chart.js" in content.lower()
