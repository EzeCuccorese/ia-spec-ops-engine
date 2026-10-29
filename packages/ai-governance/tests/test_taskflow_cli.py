"""Taskflow CLI: tracking, lifecycle, reporting and error paths, asserted on output and state."""

# ruff: noqa: F401, F811
from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest
from ai_governance.taskflow.cli import main
from ai_governance.taskflow.store import TaskStore
from test_taskflow import (
    _git,
    _plan_and_approve,
    _red_green_commit,
    cli_run,
    fake_agents,
    outside_claude,
    repo,
    state,
)  # shared fixtures

Run = Callable[..., int]


@pytest.fixture
def run(state: TaskStore, repo: Path, monkeypatch: pytest.MonkeyPatch) -> Run:
    monkeypatch.chdir(repo)
    assert main(["new", "ONB-1", "--title", "Fix status", "--summary", "goal"]) == 0
    assert main(["bind", "ONB-1", "--repo", str(repo)]) == 0
    return lambda *argv: main(list(argv))


def _out(capsys: pytest.CaptureFixture[str]) -> str:
    return capsys.readouterr().out


def test_tracking_commands_show_up_in_the_full_view(
    run: Run, state: TaskStore, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run("summary", "ONB-1", "new goal") == 0
    assert run("step", "ONB-1", "add", "write test") == 0
    assert run("step", "ONB-1", "add", "drop me") == 0
    assert run("step", "ONB-1", "remove", "2") == 0
    assert run("fact", "ONB-1", "fact one") == 0
    assert run("decide", "ONB-1", "decision one", "--why", "because") == 0
    assert run("link", "ONB-1", "Doc", "https://example.com/doc") == 0
    assert run("reference", "ONB-1", "pr", "#7", "--url", "https://example.com/7") == 0
    assert run("note", "ONB-1", "long log line") == 0
    assert run("friction", "ONB-1", "gate was confusing") == 0
    capsys.readouterr()
    assert run("show", "ONB-1", "--full") == 0
    text = _out(capsys)
    for needle in ("new goal", "write test", "fact one", "long log line"):
        assert needle in text
    assert "drop me" not in text
    assert [d["text"] for d in state.get("ONB-1").decisions] == ["decision one"]
    assert run("show", "ONB-1", "--json") == 0
    data = json.loads(_out(capsys))
    assert data["links"][0]["url"] == "https://example.com/doc"
    assert data["references"][0]["value"] == "#7"


def test_lifecycle_pause_resume_block_and_close(
    run: Run, state: TaskStore, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run("pause", "ONB-1", "--reason", "waiting") == 0
    assert state.get("ONB-1").status == "paused"
    assert run("resume", "ONB-1") == 0
    assert state.get("ONB-1").status == "active"
    assert run("block", "ONB-1", "--owner", "dba", "--needs", "a ticket") == 0
    assert run("unblock", "ONB-1") == 0
    assert run("close", "ONB-1", "--abandon", "--reason", "dropped") == 0
    capsys.readouterr()
    assert run("list") == 0
    assert "ONB-1" not in _out(capsys)
    assert run("list", "--all", "--json") == 0
    assert json.loads(_out(capsys))
    assert run("reopen", "ONB-1") == 0
    assert state.get("ONB-1").status == "active"


def test_unbind_and_reports(
    run: Run, repo: Path, fake_agents: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run("fact", "ONB-1", "token=abc123supersecret") == 0
    capsys.readouterr()
    assert run("handoff", "ONB-1", "--to", "builder") == 0
    assert "abc123supersecret" not in _out(capsys)
    out = repo / "findings.md"
    assert run("findings", "ONB-1", "--out", str(out)) == 0
    assert "ONB-1" in out.read_text()
    assert run("draft", "ONB-1") == 0
    assert _out(capsys).strip()
    assert run("digest", "--max-chars", "400") == 0
    assert "ONB-1" in _out(capsys)
    assert run("config") == 0
    assert run("rounds", "ONB-1") == 0
    assert run("status", "ONB-1", "--json") == 0
    assert "phase" in _out(capsys)
    assert run("unbind", "ONB-1", "--repo", str(repo)) == 0


def test_error_paths_return_failure(run: Run, capsys: pytest.CaptureFixture[str]) -> None:
    capsys.readouterr()
    assert run("show", "NOPE-9") != 0
    assert run("fact", "NOPE-9", "x") != 0
    assert run("phase", "ONB-1", "judge") != 0
    assert run("step", "ONB-1", "done", "99") != 0
    assert run("close", "ONB-1") != 0


def test_subtasks_switch_and_reject_strangers(
    run: Run, state: TaskStore, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run("new", "ONB-1-a", "--title", "Child", "--parent", "ONB-1") == 0
    assert run("switch", "ONB-1", "ONB-1-a") == 0
    assert state.get("ONB-1").active_subtask == "ONB-1-a"
    assert run("switch", "ONB-1", "ONB-9") != 0
    capsys.readouterr()
    assert run("list", "--json") == 0
    assert "ONB-1" in _out(capsys)


def test_stamp_ask_and_status_report_the_gate_state(
    run: Run, capsys: pytest.CaptureFixture[str]
) -> None:
    capsys.readouterr()
    assert run("stamp", "ONB-1") == 0
    stamp = json.loads(_out(capsys))
    assert {"stamp", "risk", "judges"} <= stamp.keys()
    assert run("ask", "ONB-1", "--action", "plan", "--target", "ONB-1") == 0
    assert "taskflow approve ONB-1 --action plan" in _out(capsys)
    assert run("status", "ONB-1") == 0
    assert _out(capsys).strip()


def test_manual_rounds_are_context_only(
    run: Run, repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    body = repo / "round.md"
    body.write_text("looks fine, password=hunter2hunter2\n")
    assert run("round", "ONB-1", "record", "--role", "planner", "--file", str(body)) == 0
    capsys.readouterr()
    assert run("rounds", "ONB-1") == 0
    assert "planner" in _out(capsys)
    assert run("rounds", "ONB-1", "--show", "1") == 0
    shown = _out(capsys)
    assert "looks fine" in shown and "hunter2hunter2" not in shown


def test_evidence_and_deploy_are_recorded(
    run: Run, state: TaskStore, repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    proof = repo / "proof.txt"
    proof.write_text("12 passed\n")
    assert run("evidence", "ONB-1", "--kind", "review", "--file", str(proof)) == 0
    sha = "a" * 40
    assert (
        run(
            "deploy",
            "ONB-1",
            "--env",
            "staging",
            "--repo",
            "app",
            "--sha",
            sha,
            "--provenance",
            "manual",
        )
        == 0
    )
    task = state.get("ONB-1")
    assert any(sha in json.dumps(d) for d in task.deployments)
    assert list(state.evidence_dir("ONB-1").iterdir())
    capsys.readouterr()
    assert run("evidence", "ONB-1", "--kind", "review", "--file", str(proof / "missing")) != 0


def test_tdd_skip_needs_a_reason_and_unknown_phase_is_rejected(run: Run) -> None:
    assert run("tdd", "ONB-1", "skip") != 0
    assert run("phase", "ONB-1", "done") != 0


def test_show_describes_parent_children_and_blockers(
    run: Run, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run("new", "ONB-1-a", "--title", "Child", "--parent", "ONB-1") == 0
    assert run("block", "ONB-1", "--owner", "dba", "--needs", "a ticket") == 0
    capsys.readouterr()
    assert run("show", "ONB-1") == 0
    parent = _out(capsys)
    assert "ONB-1-a" in parent and "dba: a ticket" in parent
    assert run("show", "ONB-1-a") == 0
    assert "ONB-1" in _out(capsys)
    assert run("show", "ONB-1", "--json", "--full") == 0
    assert "log" in json.loads(_out(capsys))


def test_steps_can_be_completed_by_text_and_bad_selectors_fail(run: Run, state: TaskStore) -> None:
    assert run("step", "ONB-1", "add", "write test") == 0
    assert run("step", "ONB-1", "done", "write test") == 0
    assert state.get("ONB-1").steps[0]["done"] is True
    assert run("step", "ONB-1", "done", "no such step") != 0


def test_task_is_resolved_from_the_branch_when_not_bound(
    run: Run, repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run("unbind", "ONB-1", "--repo", str(repo)) == 0
    capsys.readouterr()
    assert run("show") == 0
    assert "ONB-1" in _out(capsys)
    assert run("status", "--json") == 0
    assert "Phase" in json.loads(_out(capsys))


def test_unresolvable_directory_asks_for_the_task_id(
    run: Run, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    assert run("show") != 0


def test_round_run_validates_its_inputs(run: Run, repo: Path) -> None:
    assert run("round", "ONB-1", "run", "--role", "planner") != 0
    assert run("round", "ONB-1", "run", "--role", "judge", "--prompt", "x") != 0
    assert run("round", "ONB-1", "run", "--role", "builder", "--prompt", "x") != 0
    assert run("round", "ONB-1", "record", "--role", "planner", "--file", str(repo / "gone")) != 0
    assert run("rounds", "ONB-1", "--show", "99") != 0


def test_tdd_and_judge_refuse_when_not_ready(run: Run, state: TaskStore) -> None:
    assert run("tdd", "ONB-1", "red") != 0
    assert run("tdd", "ONB-1", "skip", "--reason", " ") != 0
    assert run("judge", "ONB-1") != 0
    assert run("new", "man-1", "--title", "M", "--workflow", "manual") == 0
    assert run("judge", "man-1") != 0
    assert state.get("man-1").workflow == "manual"


def test_ask_for_a_risky_action_demands_the_consequence(
    run: Run, capsys: pytest.CaptureFixture[str]
) -> None:
    capsys.readouterr()
    assert run("ask", "ONB-1", "--action", "deploy", "--target", "staging") == 0
    text = _out(capsys)
    assert "breaks" in text and "--consequence" in text


def test_no_command_prints_the_help(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 0
    assert "usage" in _out(capsys).lower()


def test_duplicate_tasks_and_corrupt_state_files(run: Run, state: TaskStore) -> None:
    assert run("new", "ONB-1", "--title", "again") != 0
    broken = state.task_dir("BROKEN-1")
    broken.mkdir(parents=True)
    (broken / "state.json").write_text("{not json")
    assert [t.id for t in state.list()] == ["ONB-1"]
    assert state.exists("ONB-1") and not state.exists("BROKEN-1-nope")


def test_blocked_tasks_cannot_start_builder_rounds(run: Run) -> None:
    assert run("block", "ONB-1", "--owner", "dba", "--needs", "a ticket") == 0
    assert run("round", "ONB-1", "run", "--role", "builder", "--prompt", "x") != 0
    assert run("unblock", "ONB-1") == 0


def test_round_run_reads_prompt_files_and_rejects_unknown_agents(
    run: Run, repo: Path, fake_agents: Path
) -> None:
    prompt = repo / "prompt.md"
    prompt.write_text("plan it\n")
    args = ("round", "ONB-1", "run", "--role", "planner")
    assert run(*args, "--prompt-file", str(prompt), "--model", "m1") == 0
    assert run(*args, "--prompt", "x", "--agent", "nope") != 0


def test_tdd_green_needs_a_red_run_and_a_passing_command(run: Run, repo: Path) -> None:
    failing = "sh -c 'echo FAILED: boom; exit 1'"
    assert run("tdd", "ONB-1", "green", "--cmd", "true") != 0
    assert run("tdd", "ONB-1", "red", "--cmd", failing) == 0
    assert run("tdd", "ONB-1", "green", "--cmd", failing) != 0


def test_invalid_config_is_reported(
    run: Run, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = tmp_path / "config" / "ai-governance"
    config.mkdir(parents=True)
    (config / "taskflow.toml").write_text(
        '[roles.builder]\nagent = "claude"\n[[roles.judges]]\nfocus = "correctness"\nagent = "claude"\n'
    )
    assert run("config") != 0


def test_risky_approvals_are_rejected_until_they_name_action_and_target(run: Run) -> None:
    base = ("approve", "ONB-1", "--action", "deploy", "--target", "billing")
    assert run(*base, "--user-reply", "ok") != 0  # no consequence shown
    assert run(*base, "--user-reply", " ", "--consequence", "outage") != 0
    assert run(*base, "--user-reply", "dale", "--consequence", "outage") != 0
    assert run(*base, "--user-reply", "confirmo la migracion", "--consequence", "x") != 0
    assert run(*base, "--user-reply", "confirmo deploy de otra cosa", "--consequence", "x") != 0


def test_stamp_tracks_links_renames_and_integration_branch(
    run: Run, repo: Path, state: TaskStore, capsys: pytest.CaptureFixture[str]
) -> None:
    origin = repo.parent / "origin.git"
    _git(repo, "branch", "develop")
    subprocess.run(["git", "clone", "-q", "--bare", str(repo), str(origin)], check=True)
    _git(repo, "remote", "add", "origin", str(origin))
    _git(repo, "fetch", "-q", "origin")
    assert run("bind", "ONB-1", "--repo", str(repo), "--integration-branch", "develop") == 0
    (repo / "link").symlink_to("app.py")
    _git(repo, "mv", "app.py", "moved.py")
    capsys.readouterr()
    assert run("stamp", "ONB-1", "--remote") == 0
    first = json.loads(_out(capsys))["stamp"]
    (repo / "link").unlink()
    (repo / "link").symlink_to("moved.py")
    assert run("stamp", "ONB-1") == 0
    assert json.loads(_out(capsys))["stamp"] != first
    repos = state.get("ONB-1").repos
    assert repos and repos[0]["integration_branch"] == "develop"


def test_stamp_falls_back_to_the_local_integration_branch_without_a_remote(
    run: Run, repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _git(repo, "branch", "develop")
    assert run("bind", "ONB-1", "--repo", str(repo), "--integration-branch", "develop") == 0
    capsys.readouterr()
    assert run("stamp", "ONB-1") == 0
    stamp = json.loads(_out(capsys))["stamp"]
    assert stamp["repos"][0]["base"] == _git(repo, "rev-parse", "develop").strip()


def test_store_refuses_escaping_paths_and_corrupt_state(state: TaskStore) -> None:
    with pytest.raises(ValueError):
        state.task_dir("../outside")
    broken = state.task_dir("BAD-1")
    broken.mkdir(parents=True)
    (broken / "state.json").write_text("[1]")
    with pytest.raises(ValueError):
        state.get("BAD-1")


def test_manual_and_unbound_tasks_report_what_is_missing(
    run: Run, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run("new", "man-1", "--title", "M", "--workflow", "manual") == 0
    assert run("round", "man-1", "run", "--role", "planner", "--prompt", "x") != 0
    assert run("new", "free-1", "--title", "No repo") == 0
    capsys.readouterr()
    assert run("status", "free-1", "--json") == 0
    assert "no repository bound" in _out(capsys)
    assert run("phase", "free-1", "judge") != 0
    assert run("close", "free-1", "--abandon") == 0
    assert run("phase", "free-1", "work") != 0


def test_reports_after_a_judged_flow_include_the_judge_answer(
    state: TaskStore, cli_run: Run, repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _plan_and_approve(cli_run)
    _red_green_commit(cli_run, repo)
    assert cli_run("phase", "ONB-1", "judge") == 0
    assert cli_run("judge", "ONB-1") == 0
    out = repo.parent / "findings.md"
    capsys.readouterr()
    assert cli_run("findings", "ONB-1", "--out", str(out)) == 0
    assert "ONB-1" in out.read_text()
    capsys.readouterr()
    assert cli_run("draft", "ONB-1") == 0
    assert "Restore status" in _out(capsys)
    assert cli_run("handoff", "ONB-1", "--to", "judge") == 0
    assert "Handoff to judge" in _out(capsys)
    assert cli_run("stamp", "ONB-1") == 0
    assert cli_run("rounds", "ONB-1") == 0


def test_judge_refuses_a_dirty_tree_and_keeps_edits_out(
    state: TaskStore, cli_run: Run, repo: Path
) -> None:
    _plan_and_approve(cli_run)
    _red_green_commit(cli_run, repo)
    assert cli_run("phase", "ONB-1", "judge") == 0
    (repo / "dirty.txt").write_text("uncommitted\n")
    assert cli_run("judge", "ONB-1") != 0
    assert cli_run("judge", "ONB-1", "--focus", "nope") != 0
