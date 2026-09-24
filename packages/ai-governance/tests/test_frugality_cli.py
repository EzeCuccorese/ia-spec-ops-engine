from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from ai_governance.frugality import cli


@pytest.fixture(autouse=True)
def _config_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AI_GOVERNANCE_CONFIG_DIR", str(tmp_path))


def test_load_config_merges_existing_file(tmp_path: Path) -> None:
    (tmp_path / "frugal.json").write_text(json.dumps({"threshold_chars": 999}))
    cfg = cli.load_config()
    assert cfg["threshold_chars"] == 999
    assert cfg["budget_chars"] == cli.DEFAULT_CONFIG["budget_chars"]


def test_load_config_ignores_malformed_file(tmp_path: Path) -> None:
    (tmp_path / "frugal.json").write_text("not json")
    assert cli.load_config() == cli.DEFAULT_CONFIG


class _Proc:
    def __init__(self, stdout: str, returncode: int = 0) -> None:
        self.stdout, self.returncode = stdout, returncode


@pytest.mark.parametrize(
    ("which", "run", "expected"),
    [
        (None, None, None),
        ("/bin/ws", _Proc("not json"), None),
        ("/bin/ws", _Proc(json.dumps({"schema_version": 1}), returncode=2), None),
        ("/bin/ws", _Proc(json.dumps({"schema_version": 9})), None),
        ("/bin/ws", subprocess.TimeoutExpired("ws", 30), None),
        (
            "/bin/ws",
            _Proc(json.dumps({"schema_version": 1, "text": "ok"})),
            {"schema_version": 1, "text": "ok"},
        ),
    ],
)
def test_condense_with_ws_contract(monkeypatch, which, run, expected) -> None:
    def fake_run(*args, **kwargs):
        if isinstance(run, Exception):
            raise run
        return run

    monkeypatch.setattr(cli.shutil, "which", lambda name: which)
    monkeypatch.setattr(cli.subprocess, "run", fake_run)
    assert cli.condense_with_ws("text", "pytest", 100) == expected


def test_condensed_output_handles_string_responses(monkeypatch) -> None:
    result = {"schema_version": 1, "text": "short", "truncated": True, "log_id": None}
    monkeypatch.setattr(cli, "condense_with_ws", lambda text, command, budget: result)
    payload = {"tool_input": {"command": "pytest"}, "tool_output": "x" * 5000}
    assert cli.condensed_output(payload, dict(cli.DEFAULT_CONFIG)) == ("short", "short")
