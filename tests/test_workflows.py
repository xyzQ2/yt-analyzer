"""Structural checks on the GitHub Actions workflows — no execution, just
parsing, since a broken concurrency guard or a shell-injection pattern here
is a real defect even though nothing in tests/ can run the workflow itself.
"""

from pathlib import Path

import yaml

WORKFLOW_DIR = Path(__file__).parent.parent / ".github" / "workflows"


def _load(name):
    return yaml.safe_load((WORKFLOW_DIR / name).read_text(encoding="utf-8"))


def test_all_workflows_share_the_db_concurrency_group():
    """daily.yml, discover.yml and post.yml all commit data/intelligence.db —
    without a shared concurrency group, an overlapping run silently clobbers it."""
    for name in ("daily.yml", "discover.yml", "post.yml"):
        wf = _load(name)
        concurrency = wf.get("concurrency")
        assert concurrency is not None, f"{name} is missing a concurrency block"
        assert concurrency.get("group") == "igtt-db"
        assert concurrency.get("cancel-in-progress") is False


def test_post_yml_passes_inputs_through_env_not_inline():
    """Dispatch inputs must never be interpolated directly into `run:` —
    that is a shell-injection vector. They must go through env: instead."""
    wf = _load("post.yml")
    steps = wf["jobs"]["publish"]["steps"]
    publish_step = next(s for s in steps if s.get("name") == "Publish")
    run_line = publish_step["run"]
    assert "${{" not in run_line, "dispatch inputs must be passed via env:, not inlined"
    env = publish_step.get("env", {})
    assert "inputs.idea_id" in env.get("IDEA_ID", "")
    assert "IDEA_ID" in run_line


def test_post_yml_has_optional_media_url_input():
    wf = _load("post.yml")
    # PyYAML (YAML 1.1) parses the unquoted `on:` key as the boolean True.
    inputs = wf[True]["workflow_dispatch"]["inputs"]
    assert "media_url" in inputs
    assert inputs["media_url"].get("required") is False
