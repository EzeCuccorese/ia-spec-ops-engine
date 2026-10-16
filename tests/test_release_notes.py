"""Gemini release-notes helper: request shape, response parsing and the no-key fallback."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "release_notes", REPO_ROOT / "scripts" / "release_notes.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


notes = _load()


def test_extract_text_joins_parts() -> None:
    payload = {"candidates": [{"content": {"parts": [{"text": "### Fixes\n"}, {"text": "- x"}]}}]}
    assert notes.extract_text(payload) == "### Fixes\n- x"


def test_extract_text_handles_empty_response() -> None:
    assert notes.extract_text({"candidates": []}) == ""


def test_request_names_language_and_commits() -> None:
    body = notes.build_request("feat: a", "Spanish")
    prompt = body["contents"][0]["parts"][0]["text"]
    assert "in Spanish" in prompt
    assert "feat: a" in prompt


def test_missing_key_falls_back_without_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    commits = tmp_path / "commits.txt"
    commits.write_text("feat: a\x00", encoding="utf-8")
    out = tmp_path / "notes.md"
    assert notes.main(["--commits", str(commits), "--out", str(out)]) == 0
    assert not out.exists()
    assert "commit list" in capsys.readouterr().out


def test_network_failure_falls_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    def boom(*_args: object, **_kwargs: object) -> str:
        raise TimeoutError("slow")

    monkeypatch.setattr(notes, "draft", boom)
    commits = tmp_path / "commits.txt"
    commits.write_text("feat: a\x00", encoding="utf-8")
    out = tmp_path / "notes.md"
    assert notes.main(["--commits", str(commits), "--out", str(out)]) == 0
    assert not out.exists()
    assert "AI notes unavailable" in capsys.readouterr().out
