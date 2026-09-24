from __future__ import annotations

import io
import json
import subprocess
from pathlib import Path

import pytest
from ai_governance import hooks
from ai_governance.session.tracker import SessionTracker, TaskState


def _stdin(monkeypatch, payload: dict) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))


class _Proc:
    def __init__(self, stdout: str) -> None:
        self.stdout, self.returncode = stdout, 0


def test_stop_gate_blocks_with_condensed_failures(monkeypatch, capsys, tmp_path) -> None:
    result = {"status": "failed", "text": "E assert 1 == 2", "log_id": "abc123"}
    monkeypatch.setattr(hooks.shutil, "which", lambda name: "/bin/ws")
    monkeypatch.setattr(hooks.subprocess, "run", lambda *a, **k: _Proc(json.dumps(result)))
    _stdin(monkeypatch, {"cwd": str(tmp_path)})
    assert hooks.main(["claude", "stop-gate"]) == 2
    err = capsys.readouterr().err
    assert "E assert 1 == 2" in err and "ws log abc123" in err


@pytest.mark.parametrize(
    ("payload", "result", "which"),
    [
        ({"stop_hook_active": True}, {"status": "failed", "text": "x"}, "/bin/ws"),
        ({}, {"status": "passed", "text": "ok"}, "/bin/ws"),
        ({}, {"status": "skipped", "text": "ok"}, "/bin/ws"),
        ({}, {"status": "failed", "text": "x"}, None),
    ],
)
def test_stop_gate_allows_stopping(monkeypatch, payload, result, which) -> None:
    monkeypatch.setattr(hooks.shutil, "which", lambda name: which)
    monkeypatch.setattr(hooks.subprocess, "run", lambda *a, **k: _Proc(json.dumps(result)))
    _stdin(monkeypatch, payload)
    assert hooks.main(["claude", "stop-gate"]) == 0


def _repo_with_task(monkeypatch, tmp_path: Path) -> Path:
    monkeypatch.setenv("AI_GOVERNANCE_STATE_DIR", str(tmp_path / "state"))
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "feat/x", str(repo)], check=True)
    tracker = SessionTracker()
    tracker.create_task(TaskState(id="T-1", title="Refactor", summary="Split the installer"))
    tracker.add_repository("T-1", repo)
    tracker.add_step("T-1", "write tests")
    return repo


def test_session_start_injects_active_task_digest(monkeypatch, capsys, tmp_path) -> None:
    repo = _repo_with_task(monkeypatch, tmp_path)
    _stdin(monkeypatch, {"cwd": str(repo)})
    assert hooks.main(["claude", "session-start"]) == 0
    out = capsys.readouterr().out
    assert "T-1" in out and "write tests" in out
    assert len(out) <= hooks.SESSION_CONTEXT_CHARS + 1


def test_session_end_logs_deterministic_facts(monkeypatch, tmp_path) -> None:
    repo = _repo_with_task(monkeypatch, tmp_path)
    (repo / "new.txt").write_text("x")
    _stdin(monkeypatch, {"cwd": str(repo)})
    assert hooks.main(["claude", "session-end"]) == 0
    log = SessionTracker().read_log("T-1")
    assert "Session ended on feat/x" in log and "1 uncommitted file(s)" in log


def test_session_hooks_are_silent_without_task(monkeypatch, capsys, tmp_path) -> None:
    monkeypatch.setenv("AI_GOVERNANCE_STATE_DIR", str(tmp_path / "state"))
    _stdin(monkeypatch, {"cwd": str(tmp_path)})
    assert hooks.main(["claude", "session-start"]) == 0
    assert capsys.readouterr().out == ""


def test_unknown_hook_and_internal_errors_fail_open(monkeypatch, capsys) -> None:
    assert hooks.main(["claude", "nope"]) == 0
    monkeypatch.setitem(hooks.HANDLERS, ("claude", "boom"), lambda: 1 / 0)
    assert hooks.main(["claude", "boom"]) == 0
    assert "ZeroDivisionError" in capsys.readouterr().err
