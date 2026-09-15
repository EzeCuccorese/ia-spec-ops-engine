"""Portable Claude resource acceptance coverage for @s7 and @s8."""

from __future__ import annotations

from importlib.resources import files


def test_claude_progress_resources_are_portable() -> None:
    root = files("ai_governance").joinpath("resources", "claude", "commands")
    expected = {"progress-save.md", "progress-list.md", "progress-resume.md", "progress-close.md"}
    found = {item.name for item in root.iterdir() if item.name.endswith(".md")}
    assert found == expected
    combined = "\n".join(root.joinpath(name).read_text(encoding="utf-8") for name in expected)
    assert "progress-to-md" not in combined
    assert "source ~/.zshrc" not in combined
    assert "@tiendanube" not in combined
    assert "CLAUDE_CODE_SUBAGENT_MODEL" not in combined
