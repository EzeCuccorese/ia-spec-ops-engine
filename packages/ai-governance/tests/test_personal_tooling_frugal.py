"""Frugality acceptance coverage for @s5."""

from __future__ import annotations

from pathlib import Path

from ai_governance.frugality.pre_check import PreCheck


def test_warning_session_identifier_is_hashed_and_confined(tmp_path: Path) -> None:
    assert PreCheck.check_command("git log", "../../../outside", tmp_path)
    files = list((tmp_path / "sessions").glob("*.json"))
    assert len(files) == 1
    assert files[0].parent == tmp_path / "sessions"
    assert ".." not in files[0].name
