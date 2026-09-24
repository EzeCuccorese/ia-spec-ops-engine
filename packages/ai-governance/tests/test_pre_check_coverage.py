"""Coverage tests for ai_governance.frugality.pre_check edge cases."""

from __future__ import annotations

from pathlib import Path

import pytest
from ai_governance.frugality import pre_check
from ai_governance.frugality.pre_check import PreCheck, replacement_patterns


def test_replacement_patterns_skip_entries_whose_matcher_is_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When `_build_matcher` cannot compile an entry, that entry is skipped."""
    monkeypatch.setattr(pre_check, "_build_matcher", lambda entry: None)
    assert replacement_patterns() == ()


def test_check_command_ignores_corrupted_warnings_file(tmp_path: Path) -> None:
    """A malformed warnings file is treated as empty rather than raising."""
    session_dir = tmp_path / "sessions"
    session_dir.mkdir(parents=True)
    import hashlib

    safe_session = hashlib.sha256(b"sid").hexdigest()[:24]
    (session_dir / f"{safe_session}.json").write_text("not valid json", encoding="utf-8")

    advice = PreCheck.check_command("cat package-lock.json", session_id="sid", runtime_dir=tmp_path)
    assert advice is not None


def test_check_command_cleans_up_temp_file_when_replace_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """If `Path.replace` fails after the temp file is written, it is cleaned up."""

    def boom(self: Path, _dest: Path) -> None:
        raise OSError("simulated replace failure")

    monkeypatch.setattr(Path, "replace", boom)
    advice = PreCheck.check_command("cat package-lock.json", session_id="sid", runtime_dir=tmp_path)
    assert advice is not None
    leftovers = list((tmp_path / "sessions").glob("tmp*"))
    assert leftovers == []


def test_check_command_swallows_oserror_when_persisting_warning(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """If writing the warnings file fails, the advice is still returned."""

    def boom(self: Path, *_args: object, **_kwargs: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(Path, "mkdir", boom)
    advice = PreCheck.check_command("cat package-lock.json", session_id="sid", runtime_dir=tmp_path)
    assert advice is not None
