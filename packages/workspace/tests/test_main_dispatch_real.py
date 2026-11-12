"""
End-to-end dispatch tests for `ws <command>`: the real sub-`main` runs so the
arguments `ws` forwards are the ones each command parses.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from workspace_engine.cli.main import main


def _ws(*argv: str) -> int | str | None:
    """Runs `ws <argv>` and returns the exit code (None when the command just returns)."""
    with patch("sys.argv", ["ws", *argv]):
        try:
            main()
        except SystemExit as exc:
            return exc.code
    return None


def _output(capsys: pytest.CaptureFixture[str]) -> str:
    captured = capsys.readouterr()
    return captured.out + captured.err


def test_hooks_help_is_its_own(capsys: pytest.CaptureFixture[str]) -> None:
    assert _ws("hooks", "--help") == 0
    assert "usage: ws hooks" in _output(capsys)


def test_detect_json_emits_stacks(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    assert _ws("detect", "--dir", str(tmp_path), "--json") == 0
    payload = json.loads(_output(capsys))
    assert "python" in payload["stacks"]


def test_config_show_json_emits_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    assert _ws("config", "show", "--json") == 0
    payload = json.loads(_output(capsys))
    assert "gate.scope" in payload
