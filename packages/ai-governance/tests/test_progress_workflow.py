"""Portable neutral progress workflow resource coverage."""

from __future__ import annotations

from importlib.resources import files


def test_progress_workflow_resource_is_portable() -> None:
    workflow_file = files("ai_governance").joinpath("resources", "workflows", "progress.md")
    assert workflow_file.is_file(), "resources/workflows/progress.md must exist and be packaged"

    content = workflow_file.read_text(encoding="utf-8")
    assert "Save Progress" in content
    assert "List Tasks" in content
    assert "Resume Task" in content
    assert "Close Task" in content

    # Vendor-neutral invariants
    assert "$ARGUMENTS" not in content
    assert ".claude" not in content
    assert "progress-to-md" not in content
    assert "source ~/.zshrc" not in content
    assert "@tiendanube" not in content
    assert "CLAUDE_CODE_SUBAGENT_MODEL" not in content
