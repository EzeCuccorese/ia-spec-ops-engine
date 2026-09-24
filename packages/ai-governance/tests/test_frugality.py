from __future__ import annotations

import io
import json

import pytest
from ai_governance.frugality import cli
from ai_governance.frugality.pre_check import PreCheck


def test_pre_check_wasteful_commands() -> None:
    assert PreCheck.check_command("cat package-lock.json") is not None
    assert PreCheck.check_command("curl https://api.example.com/huge") is not None
    assert PreCheck.check_command("curl https://api.example.com/huge | jq .") is None
    assert PreCheck.check_command("git log") is not None
    assert PreCheck.check_command("git log -n 10") is None
    assert PreCheck.check_command("git log --oneline -5") is None
    assert PreCheck.check_command("cat package-lock.json #nofrugal") is None


def test_run_pre_bash_no_permission_decision(monkeypatch, capsys, tmp_path) -> None:
    from io import StringIO

    from ai_governance.frugality import cli

    monkeypatch.setattr(cli, "get_runtime_dir", lambda: tmp_path)
    input_payload = {
        "tool_input": {"command": "cat package-lock.json"},
        "session_id": "test-isolated-session",
    }
    monkeypatch.setattr("sys.stdin", StringIO(json.dumps(input_payload)))

    cli.run_pre_bash({})
    out = capsys.readouterr().out
    assert out.strip() != ""
    data = json.loads(out)
    hook_out = data["hookSpecificOutput"]
    assert hook_out["hookEventName"] == "PreToolUse"
    assert "additionalContext" in hook_out
    assert "permissionDecision" not in hook_out


def test_get_runtime_dir_under_state_dir(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("AI_GOVERNANCE_STATE_DIR", str(tmp_path))
    assert cli.get_runtime_dir() == tmp_path / "frugal"


def _post(monkeypatch, capsys, payload: dict, fake_result: dict | None) -> str:
    calls: list[tuple[str, str]] = []

    def fake_condense(text: str, command: str, budget: int):
        calls.append((command, text))
        return fake_result

    monkeypatch.setattr(cli, "condense_with_ws", fake_condense)
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    cli.run_post_bash(dict(cli.DEFAULT_CONFIG))
    return capsys.readouterr().out


BIG = "x\n" * 5000


def test_post_bash_replaces_large_output_with_ws_summary(monkeypatch, capsys) -> None:
    payload = {
        "tool_input": {"command": "pytest"},
        "tool_response": {"stdout": BIG, "stderr": "warn", "interrupted": False},
    }
    result = {"schema_version": 1, "text": "E assert 1 == 2", "truncated": True, "log_id": "abc123"}
    out = json.loads(_post(monkeypatch, capsys, payload, result))
    updated = out["hookSpecificOutput"]["updatedToolOutput"]
    assert updated["stdout"].startswith("E assert 1 == 2")
    assert "ws log abc123" in updated["stdout"]
    assert updated["stderr"] == "" and updated["interrupted"] is False


@pytest.mark.parametrize(
    ("command", "stdout", "result"),
    [
        ("pytest", "short", {"schema_version": 1, "text": "t", "truncated": True}),
        ("git diff HEAD~1", BIG, {"schema_version": 1, "text": "t", "truncated": True}),
        ("cat big.log", BIG, {"schema_version": 1, "text": "t", "truncated": True}),
        ("pytest #nofrugal", BIG, {"schema_version": 1, "text": "t", "truncated": True}),
        ("pytest", BIG, None),  # ws missing -> original output kept
    ],
)
def test_post_bash_keeps_output(monkeypatch, capsys, command, stdout, result) -> None:
    payload = {"tool_input": {"command": command}, "tool_response": {"stdout": stdout}}
    assert _post(monkeypatch, capsys, payload, result) == ""


def test_hooks_never_grant_permission(monkeypatch, capsys, tmp_path) -> None:
    monkeypatch.setattr(cli, "get_runtime_dir", lambda: tmp_path)
    for payload in ({"tool_input": {"command": "git log"}}, {"malformed": True}):
        monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
        cli.run_pre_bash({})
        _post(monkeypatch, capsys, payload, None)
        assert "allow" not in capsys.readouterr().out.lower()
