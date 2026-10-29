from __future__ import annotations

import io
import json
import subprocess
from pathlib import Path

import pytest
from ai_governance import hooks
from ai_governance.taskflow.models import Task
from ai_governance.taskflow.store import TaskStore


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
    store = TaskStore()
    store.create(Task(id="T-1", title="Refactor", summary="Split the installer"))
    store.mutate(
        "T-1",
        lambda t: (
            t.repos.append({"path": str(repo.resolve())}),
            t.steps.append({"text": "write tests", "done": False}),
        ),
    )
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
    log = TaskStore().read_log("T-1")
    assert "Session ended on feat/x" in log and "1 uncommitted file(s)" in log


def test_session_hooks_are_silent_without_task(monkeypatch, capsys, tmp_path) -> None:
    monkeypatch.setenv("AI_GOVERNANCE_STATE_DIR", str(tmp_path / "state"))
    _stdin(monkeypatch, {"cwd": str(tmp_path)})
    assert hooks.main(["claude", "session-start"]) == 0
    assert capsys.readouterr().out == ""


def test_session_start_in_a_repository_without_task_asks_for_one(
    monkeypatch, capsys, tmp_path
) -> None:
    monkeypatch.setenv("AI_GOVERNANCE_STATE_DIR", str(tmp_path / "state"))
    subprocess.run(["git", "init", "-q", str(tmp_path / "r")], check=True)
    (tmp_path / "r" / "src").mkdir()
    for cwd in (tmp_path / "r", tmp_path / "r" / "src"):  # root and subdirectory
        _stdin(monkeypatch, {"cwd": str(cwd)})
        assert hooks.main(["claude", "session-start"]) == 0
        assert capsys.readouterr().out.strip() == hooks.NO_TASK_HINT


def test_session_start_names_the_candidates_when_several_tasks_are_bound(
    monkeypatch, capsys, tmp_path
) -> None:
    repo = _repo_with_task(monkeypatch, tmp_path)
    TaskStore().create(Task(id="T-2", title="Other", repos=[{"path": str(repo.resolve())}]))
    _stdin(monkeypatch, {"cwd": str(repo)})
    assert hooks.main(["claude", "session-start"]) == 0
    assert "(T-1, T-2)" in capsys.readouterr().out


def test_unknown_hook_and_internal_errors_fail_open(monkeypatch, capsys) -> None:
    assert hooks.main(["claude", "nope"]) == 0
    monkeypatch.setitem(hooks.HANDLERS, ("claude", "boom"), lambda: 1 / 0)
    assert hooks.main(["claude", "boom"]) == 0
    assert "ZeroDivisionError" in capsys.readouterr().err


def _edit(monkeypatch, capsys, payload: dict) -> str:
    """Permission decision of the edit hook for ``payload`` ('' when allowed)."""
    _stdin(monkeypatch, payload)
    assert hooks.main(["claude", "writer-lease"]) == 0
    out = capsys.readouterr().out
    return json.loads(out)["hookSpecificOutput"]["permissionDecision"] if out else ""


def test_edits_need_a_task_bound_to_the_repository_even_in_new_directories(
    monkeypatch, capsys, tmp_path
) -> None:
    repo = _repo_with_task(monkeypatch, tmp_path)
    other = tmp_path / "other"
    subprocess.run(["git", "init", "-q", str(other)], check=True)
    cwd = str(repo)
    assert _edit(monkeypatch, capsys, {"cwd": cwd, "tool_input": {"file_path": "a/b/c.py"}}) == ""
    path = str(other / "new" / "dir" / "x.py")  # parent directories do not exist yet
    assert _edit(monkeypatch, capsys, {"cwd": cwd, "tool_input": {"file_path": path}}) == "deny"
    notebook = {"cwd": str(other), "tool_input": {"notebook_path": "n.ipynb"}}
    assert _edit(monkeypatch, capsys, notebook) == "deny"


def test_edits_follow_a_file_symlink_to_its_real_repository(monkeypatch, capsys, tmp_path) -> None:
    repo = _repo_with_task(monkeypatch, tmp_path)
    other = tmp_path / "other"
    subprocess.run(["git", "init", "-q", str(other)], check=True)
    (other / "real.py").write_text("x")
    (repo / "link.py").symlink_to(other / "real.py")  # bound repo pointing at an unbound one
    (other / "back.py").symlink_to(repo / "app.py")  # unbound repo pointing at a bound one
    (repo / "app.py").write_text("y")
    denied = {"cwd": str(repo), "tool_input": {"file_path": str(repo / "link.py")}}
    assert _edit(monkeypatch, capsys, denied) == "deny"
    allowed = {"cwd": str(other), "tool_input": {"file_path": str(other / "back.py")}}
    assert _edit(monkeypatch, capsys, allowed) == ""


def test_a_branch_name_or_a_closed_task_does_not_authorize_edits(
    monkeypatch, capsys, tmp_path
) -> None:
    repo = _repo_with_task(monkeypatch, tmp_path)
    store = TaskStore()
    other = tmp_path / "other"
    subprocess.run(["git", "init", "-q", "-b", "feat/ONB-9-x", str(other)], check=True)
    store.create(Task(id="ONB-9", title="Elsewhere", repos=[{"path": str(repo.resolve())}]))
    payload = {"cwd": str(other), "tool_input": {"file_path": str(other / "a.py")}}
    assert _edit(monkeypatch, capsys, payload) == "deny"
    store.mutate("T-1", lambda t: setattr(t, "status", "closed"))
    own = {"cwd": str(repo), "tool_input": {"file_path": str(repo / "a.py")}}
    assert _edit(monkeypatch, capsys, own) == ""  # ONB-9 is still bound and open
    store.mutate("ONB-9", lambda t: setattr(t, "status", "closed"))
    assert _edit(monkeypatch, capsys, own) == "deny"


def test_agent_config_and_files_outside_git_are_never_gated(monkeypatch, capsys, tmp_path) -> None:
    monkeypatch.setenv("AI_GOVERNANCE_STATE_DIR", str(tmp_path / "state"))
    home = tmp_path / "home"
    subprocess.run(["git", "init", "-q", str(home)], check=True)  # dotfiles repo
    monkeypatch.setattr(hooks.Path, "home", lambda: home)
    for rel in (".claude/plans/p.md", ".codex/x", ".config/y/z.toml"):
        payload = {"cwd": str(home), "tool_input": {"file_path": str(home / rel)}}
        assert _edit(monkeypatch, capsys, payload) == ""
    assert (
        _edit(monkeypatch, capsys, {"cwd": str(home), "tool_input": {"file_path": str(home / "a")}})
        == "deny"
    )
    loose = {"cwd": str(tmp_path), "tool_input": {"file_path": str(tmp_path / "x.txt")}}
    assert _edit(monkeypatch, capsys, loose) == ""


def test_a_new_repository_without_commits_can_get_a_task_and_edits(
    monkeypatch, capsys, tmp_path
) -> None:
    monkeypatch.setenv("AI_GOVERNANCE_STATE_DIR", str(tmp_path / "state"))
    fresh = tmp_path / "fresh"
    subprocess.run(["git", "init", "-q", str(fresh)], check=True)  # unborn HEAD
    store = TaskStore()
    store.create(Task(id="N-1", title="t", repos=[{"path": str(fresh.resolve())}]))
    payload = {"cwd": str(fresh), "tool_input": {"file_path": str(fresh / "a.py")}}
    assert _edit(monkeypatch, capsys, payload) == ""
    from ai_governance.taskflow.stamp import repo_stamp

    assert repo_stamp(fresh.resolve())["head"] == "UNBORN"
