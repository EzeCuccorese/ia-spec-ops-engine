"""Frugality acceptance coverage for @s5."""

from __future__ import annotations

import io
import json
from pathlib import Path

from ai_governance.frugality import cli
from ai_governance.frugality.pre_check import PreCheck


def test_trim_without_host_persistence_creates_confined_copy_and_audit(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    monkeypatch.setattr(cli, "get_runtime_dir", lambda: tmp_path)
    payload = {
        "tool_use_id": "../../escape",
        "tool_input": {"command": "pytest"},
        "tool_output": "pytest starts\n" + "PASS\n" * 100 + "100 passed",
    }
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    cli.run_post_bash({"test_umbral_chars": 20, "test_head_lineas": 1, "test_tail_lineas": 1})
    output = json.loads(capsys.readouterr().out)
    trimmed = output["hookSpecificOutput"]["updatedToolOutput"]
    assert "full output:" in trimmed
    outputs = list((tmp_path / "outputs").glob("*.txt"))
    assert len(outputs) == 1
    assert outputs[0].resolve().is_relative_to(tmp_path.resolve())
    assert not (tmp_path.parent / "escape.txt").exists()
    audit = [json.loads(line) for line in (tmp_path / "trim-audit.jsonl").read_text().splitlines()]
    assert audit[0]["original_chars"] > audit[0]["trimmed_chars"]


def test_warning_session_identifier_is_hashed_and_confined(tmp_path: Path) -> None:
    assert PreCheck.check_command("git log", "../../../outside", tmp_path)
    files = list((tmp_path / "sessions").glob("*.json"))
    assert len(files) == 1
    assert files[0].parent == tmp_path / "sessions"
    assert ".." not in files[0].name
