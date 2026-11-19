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


def test_stop_gate_does_not_duplicate_explicit_budget_flag(monkeypatch, tmp_path) -> None:
    captured_cmd: list[str] = []

    def fake_run(cmd, **_):
        captured_cmd.extend(cmd)
        return _Proc(json.dumps({"status": "passed", "text": "ok"}))

    monkeypatch.setenv("AI_GOVERNANCE_GATE_COMMAND", "ws check --changed --json --budget 500")
    monkeypatch.setattr(hooks.shutil, "which", lambda name: "/bin/ws")
    monkeypatch.setattr(hooks.subprocess, "run", fake_run)
    _stdin(monkeypatch, {"cwd": str(tmp_path)})
    assert hooks.main(["claude", "stop-gate"]) == 0
    assert captured_cmd.count("--budget") == 1
    assert captured_cmd[captured_cmd.index("--budget") + 1] == "500"


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


@pytest.mark.parametrize("agent", ["claude", "codex"])
def test_session_start_injects_active_task_digest(
    agent: str, monkeypatch, capsys, tmp_path
) -> None:
    repo = _repo_with_task(monkeypatch, tmp_path)
    _stdin(monkeypatch, {"cwd": str(repo)})
    assert hooks.main([agent, "session-start"]) == 0
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


def test_removed_hooks_are_absent_and_fail_open(capsys) -> None:
    for agent, event in (
        ("claude", "writer-lease"),
        ("claude", "stop"),
        ("antigravity", "writer-lease"),
    ):
        assert (agent, event) not in hooks.HANDLERS
        assert hooks.main([agent, event]) == 0
        assert "Usage:" in capsys.readouterr().err


def test_claude_pre_tool_use_runs_frugality_without_blocking_edits(
    monkeypatch, capsys, tmp_path
) -> None:
    monkeypatch.setenv("AI_GOVERNANCE_STATE_DIR", str(tmp_path / "state"))
    repo = tmp_path / "repo"
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    _stdin(monkeypatch, {"cwd": str(repo), "tool_input": {"command": "cat package-lock.json"}})
    assert hooks.main(["claude", "pre-tool-use"]) == 0
    out = json.loads(capsys.readouterr().out)["hookSpecificOutput"]
    assert out["hookEventName"] == "PreToolUse"
    assert "permissionDecision" not in out
    assert "additionalContext" in out


def test_claude_post_tool_use_emits_condensed_output_only(monkeypatch, capsys) -> None:
    from ai_governance.frugality import cli as frugal

    monkeypatch.setattr(frugal, "post_bash_output", lambda payload, cfg: {})
    _stdin(monkeypatch, {"tool_input": {"command": "ls"}, "tool_response": {"stdout": "ok"}})
    assert hooks.main(["claude", "post-tool-use"]) == 0
    assert capsys.readouterr().out == ""

    monkeypatch.setattr(
        frugal,
        "post_bash_output",
        lambda payload, cfg: {"updatedToolOutput": {"stdout": "summary"}},
    )
    _stdin(monkeypatch, {"tool_input": {"command": "pytest"}, "tool_response": {"stdout": "big"}})
    assert hooks.main(["claude", "post-tool-use"]) == 0
    out = json.loads(capsys.readouterr().out)["hookSpecificOutput"]
    assert out == {"hookEventName": "PostToolUse", "updatedToolOutput": {"stdout": "summary"}}


def test_antigravity_session_start_uses_inject_steps(monkeypatch, capsys, tmp_path) -> None:
    repo = _repo_with_task(monkeypatch, tmp_path)
    _stdin(monkeypatch, {"workspacePaths": [str(repo)]})
    assert hooks.main(["antigravity", "session-start"]) == 0
    data = json.loads(capsys.readouterr().out)
    msg = data["injectSteps"][0]["systemMessage"]["systemMessage"]
    assert "T-1" in msg


def test_stop_gate_handles_timeout_cleanly_without_traceback(
    monkeypatch, capsys, tmp_path: Path
) -> None:
    seen_timeout: list[float] = []

    def timed_out(*args, **kwargs):
        seen_timeout.append(kwargs["timeout"])
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=kwargs["timeout"])

    monkeypatch.setenv("AI_GOVERNANCE_GATE_TIMEOUT_SECONDS", "12")
    monkeypatch.setattr(hooks.shutil, "which", lambda name: "/bin/ws")
    monkeypatch.setattr(hooks.subprocess, "run", timed_out)
    _stdin(monkeypatch, {"cwd": str(tmp_path)})
    assert hooks.main(["claude", "stop-gate"]) == 0
    assert seen_timeout == [12.0]
    err = capsys.readouterr().err
    assert "timed out" in err and "Traceback" not in err


def test_antigravity_pre_tool_use_denies_noisy_commands_never_edits(monkeypatch, capsys) -> None:
    monkeypatch.setattr(hooks.shutil, "which", lambda name: "/bin/ws")
    monkeypatch.delenv("FRUGAL", raising=False)
    _stdin(
        monkeypatch,
        {"toolCall": {"name": "run_command", "args": {"CommandLine": "pytest -q"}}},
    )
    assert hooks.main(["antigravity", "pre-tool-use"]) == 0
    denied = json.loads(capsys.readouterr().out)
    assert denied["decision"] == "deny" and "ws run -- pytest -q" in denied["reason"]

    _stdin(
        monkeypatch,
        {"toolCall": {"name": "run_command", "args": {"CommandLine": "cd sub && pytest -q"}}},
    )
    assert hooks.main(["antigravity", "pre-tool-use"]) == 0
    compound = json.loads(capsys.readouterr().out)
    assert (
        compound["decision"] == "deny"
        and "ws run -- sh -c 'cd sub && pytest -q'" in compound["reason"]
    )

    for payload in (
        {"toolCall": {"name": "run_command", "args": {"CommandLine": "ws run -- pytest -q"}}},
        {"toolCall": {"name": "run_command", "args": {"CommandLine": "pytest --help"}}},
        {"toolCall": {"name": "run_command", "args": {"CommandLine": "which pytest ruff"}}},
        {
            "toolCall": {
                "name": "run_command",
                "args": {"CommandLine": 'git commit -m "fix pytest failure"'},
            }
        },
        {"toolCall": {"name": "write_to_file", "args": {"TargetFile": "a.py"}}},
    ):
        _stdin(monkeypatch, payload)
        assert hooks.main(["antigravity", "pre-tool-use"]) == 0
        assert capsys.readouterr().out == ""


def test_antigravity_pre_tool_use_allows_when_ws_missing_or_frugal_disabled(
    monkeypatch, capsys
) -> None:
    payload = {"toolCall": {"name": "run_command", "args": {"CommandLine": "pytest -q"}}}
    monkeypatch.setattr(hooks.shutil, "which", lambda name: None)
    _stdin(monkeypatch, payload)
    assert hooks.main(["antigravity", "pre-tool-use"]) == 0
    assert capsys.readouterr().out == ""

    monkeypatch.setattr(hooks.shutil, "which", lambda name: "/bin/ws")
    monkeypatch.setenv("FRUGAL", "0")
    _stdin(monkeypatch, payload)
    assert hooks.main(["antigravity", "pre-tool-use"]) == 0
    assert capsys.readouterr().out == ""


def test_codex_post_tool_use_blocks_with_condensed_reason(monkeypatch, capsys) -> None:
    from ai_governance.frugality import cli as frugal

    monkeypatch.setattr(frugal, "condensed_output", lambda payload, cfg: ("short summary", "short"))
    _stdin(monkeypatch, {"tool_input": {"command": "pytest"}, "tool_output": "x" * 5000})
    assert hooks.main(["codex", "post-tool-use"]) == 0
    assert json.loads(capsys.readouterr().out) == {"decision": "block", "reason": "short summary"}


def test_codex_post_tool_use_silent_when_nothing_condensed(monkeypatch, capsys) -> None:
    from ai_governance.frugality import cli as frugal

    monkeypatch.setattr(frugal, "condensed_output", lambda payload, cfg: None)
    _stdin(monkeypatch, {"tool_input": {"command": "echo ok"}, "tool_output": "ok"})
    assert hooks.main(["codex", "post-tool-use"]) == 0
    assert capsys.readouterr().out == ""


def test_antigravity_session_start_silent_outside_git_repo(monkeypatch, capsys, tmp_path) -> None:
    monkeypatch.setenv("AI_GOVERNANCE_STATE_DIR", str(tmp_path / "state"))
    _stdin(monkeypatch, {"workspacePaths": [str(tmp_path)]})
    assert hooks.main(["antigravity", "session-start"]) == 0
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize(
    ("command", "expect_deny"),
    [
        ("FOO=1 uv run pytest -q", True),
        ("npx jest", True),
        ("python3 -m pytest", True),
        ("npm run test", True),
        ("pnpm build", True),
        ("cargo test", True),
        ("npm install", False),
        ("FOO=1", False),
        ("pytest 'unclosed", False),
        ("echo ok ;; ls &&", False),
    ],
    ids=[
        "env-uv-pytest",
        "npx-jest",
        "python3-m-pytest",
        "npm-run-test",
        "pnpm-build",
        "cargo-test",
        "npm-install-allowed",
        "env-only-allowed",
        "unclosed-quote-allowed",
        "empty-segments-allowed",
    ],
)
def test_antigravity_pre_tool_use_wrappers_js_runners_and_edge_syntax(
    monkeypatch, capsys, command: str, expect_deny: bool
) -> None:
    monkeypatch.setattr(hooks.shutil, "which", lambda name: "/bin/ws")
    monkeypatch.delenv("FRUGAL", raising=False)
    _stdin(monkeypatch, {"toolCall": {"name": "run_command", "args": {"CommandLine": command}}})
    assert hooks.main(["antigravity", "pre-tool-use"]) == 0
    out = capsys.readouterr().out
    if expect_deny:
        assert json.loads(out)["decision"] == "deny"
    else:
        assert out == ""


def test_session_start_adds_compact_brain_line_within_budget(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    from ai_governance.brain.store import BrainStore, NoteDraft

    monkeypatch.setenv("AI_GOVERNANCE_BRAIN_DIR", str(tmp_path / "brain"))
    repo = _repo_with_task(monkeypatch, tmp_path)
    store = BrainStore(tmp_path / "brain")
    store.add(NoteDraft(body="Use Node 20", repos=(repo.name,)))

    _stdin(monkeypatch, {"cwd": str(repo)})
    assert hooks.main(["claude", "session-start"]) == 0
    out = capsys.readouterr().out.strip()
    assert f"BRAIN: 1 note for {repo.name}" in out
    assert "ai-governance brain search" in out
    assert len(out) <= hooks.SESSION_CONTEXT_CHARS

    # Still fits within 400 chars even with a very long task summary and multiple notes.
    store.add(NoteDraft(body="Second gotcha", repos=(repo.name,)))
    TaskStore().mutate("T-1", lambda t: setattr(t, "summary", "S" * 380))
    _stdin(monkeypatch, {"cwd": str(repo)})
    assert hooks.main(["claude", "session-start"]) == 0
    long_out = capsys.readouterr().out.strip()
    assert f"BRAIN: 2 notes for {repo.name}" in long_out
    assert len(long_out) <= hooks.SESSION_CONTEXT_CHARS


def test_session_start_brain_hint_works_without_task_and_fails_open(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    from ai_governance.brain.store import BrainStore, NoteDraft

    monkeypatch.setenv("AI_GOVERNANCE_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("AI_GOVERNANCE_BRAIN_DIR", str(tmp_path / "brain"))
    repo = tmp_path / "demo-repo"
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    BrainStore(tmp_path / "brain").add(NoteDraft(body="Gotcha", repos=("demo-repo",)))

    _stdin(monkeypatch, {"cwd": str(repo)})
    assert hooks.main(["claude", "session-start"]) == 0
    out = capsys.readouterr().out.strip()
    assert hooks.NO_TASK_HINT in out
    assert "BRAIN: 1 note for demo-repo" in out
    assert len(out) <= hooks.SESSION_CONTEXT_CHARS

    monkeypatch.setattr(
        BrainStore, "count_for_repo", lambda self, r: (_ for _ in ()).throw(OSError("io"))
    )
    _stdin(monkeypatch, {"cwd": str(repo)})
    assert hooks.main(["claude", "session-start"]) == 0
    assert capsys.readouterr().out.strip() == hooks.NO_TASK_HINT


def test_combine_session_message_respects_budget_extremes() -> None:
    assert hooks._combine_session_message("", "BRAIN: 1 note", 40) == "BRAIN: 1 note"
    assert hooks._combine_session_message("a" * 50, "BRAIN: 1 note", 25).endswith("\nBRAIN: 1 note")
    assert len(hooks._combine_session_message("a" * 50, "BRAIN: 1 note", 25)) <= 25
    oversized = hooks._combine_session_message("base", "BRAIN: " + "x" * 50, 20)
    assert len(oversized) == 20 and oversized.endswith("…")
