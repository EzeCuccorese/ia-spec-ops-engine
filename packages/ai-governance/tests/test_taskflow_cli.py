"""Taskflow CLI: tracking, lifecycle, approvals, status, close and reporting."""

# ruff: noqa: F401, F811
from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

import pytest
from ai_governance.taskflow import approvals
from ai_governance.taskflow.cli import main
from ai_governance.taskflow.store import TaskStore
from orca_fakes import attach_orca
from test_taskflow import _git, outside_claude, repo, state  # shared fixtures

Run = Callable[..., int]


@pytest.fixture
def orca_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    base = tmp_path / "orca-world"
    attach_orca(base, monkeypatch)
    return base


@pytest.fixture
def run(state: TaskStore, repo: Path, monkeypatch: pytest.MonkeyPatch) -> Run:
    monkeypatch.chdir(repo)
    assert main(["new", "TASK-1", "--title", "Fix status", "--summary", "goal"]) == 0
    assert main(["bind", "TASK-1", "--repo", str(repo)]) == 0
    return lambda *argv: main(list(argv))


def _out(capsys: pytest.CaptureFixture[str]) -> str:
    return capsys.readouterr().out


def test_tracking_commands_show_up_in_the_full_view(
    run: Run, state: TaskStore, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run("summary", "TASK-1", "new goal") == 0
    assert run("step", "TASK-1", "add", "write test") == 0
    assert run("step", "TASK-1", "add", "drop me") == 0
    assert run("step", "TASK-1", "remove", "2") == 0
    assert run("fact", "TASK-1", "fact one") == 0
    assert run("decide", "TASK-1", "decision one", "--why", "because") == 0
    assert run("link", "TASK-1", "Doc", "https://example.com/doc") == 0
    assert run("reference", "TASK-1", "pr", "#7", "--url", "https://example.com/7") == 0
    assert run("note", "TASK-1", "long log line") == 0
    assert run("friction", "TASK-1", "something") == 0
    capsys.readouterr()
    assert run("show", "TASK-1", "--full") == 0
    text = _out(capsys)
    for needle in ("new goal", "write test", "fact one", "long log line"):
        assert needle in text
    assert "drop me" not in text
    assert [d["text"] for d in state.get("TASK-1").decisions] == ["decision one"]
    assert run("show", "TASK-1", "--json") == 0
    data = json.loads(_out(capsys))
    assert data["links"][0]["url"] == "https://example.com/doc"
    assert data["references"][0]["value"] == "#7"


def test_lifecycle_pause_resume_block_and_close(
    run: Run, state: TaskStore, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run("pause", "TASK-1", "--reason", "waiting") == 0
    assert state.get("TASK-1").status == "paused"
    assert run("resume", "TASK-1") == 0
    assert state.get("TASK-1").status == "active"
    assert run("block", "TASK-1", "--owner", "dba", "--needs", "a ticket") == 0
    assert run("unblock", "TASK-1") == 0
    assert run("close", "TASK-1", "--reason", "finished") == 0
    assert "finished" in state.read_log("TASK-1")
    capsys.readouterr()
    assert run("list") == 0
    assert "TASK-1" not in _out(capsys)
    assert run("list", "--all", "--json") == 0
    assert json.loads(_out(capsys))
    assert run("reopen", "TASK-1") == 0
    assert state.get("TASK-1").status == "active"


@pytest.mark.usefixtures("orca_path")
def test_close_blocks_only_on_unsettled_debate_rounds_unless_forced(
    run: Run, repo: Path, state: TaskStore, capsys: pytest.CaptureFixture[str]
) -> None:
    topic = repo.parent / "topic.md"
    topic.write_text("Pick cache backend.\n", encoding="utf-8")
    assert (
        run("debate", "TASK-1", "open", "--topic-file", str(topic), "--agents", "claude,codex") == 0
    )
    capsys.readouterr()
    assert run("close", "TASK-1") == 1
    assert "unsettled debate round" in capsys.readouterr().err
    assert state.get("TASK-1").status == "active"
    assert run("status", "TASK-1") == 0
    status_out = _out(capsys)
    assert "Debate" in status_out and "unsettled: 001, 002" in status_out
    assert run("close", "TASK-1", "--force", "--reason", "abandoned debate") == 0
    assert state.get("TASK-1").status == "closed"
    assert "abandoned debate" in state.read_log("TASK-1")


def test_close_done_outside_flow(run: Run, state: TaskStore) -> None:
    assert run("close", "TASK-1", "--done-outside") == 0
    assert state.get("TASK-1").status == "closed"
    assert "done outside flow" in state.read_log("TASK-1")

    assert run("reopen", "TASK-1") == 0
    assert state.get("TASK-1").status == "active"
    assert run("close", "TASK-1", "--external", "--reason", "merged manually") == 0
    assert state.get("TASK-1").status == "closed"
    assert "merged manually" in state.read_log("TASK-1")


def test_close_archives_only_when_status_changes(
    run: Run, state: TaskStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ai_governance.taskflow import cli as taskflow_cli

    archived: list[str] = []
    monkeypatch.setattr(
        taskflow_cli, "_archive_closed_task", lambda _store, tid: archived.append(tid)
    )

    assert run("close", "TASK-1", "--reason", "done") == 0
    assert archived == ["TASK-1"]

    assert run("close", "TASK-1", "--reason", "still done") == 0
    assert archived == ["TASK-1"]


def test_unbind_and_reports(
    run: Run, repo: Path, orca_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run("fact", "TASK-1", "token=abc123supersecret") == 0
    assert run("step", "TASK-1", "add", "ship it") == 0
    assert run("decide", "TASK-1", "use sqlite", "--why", "simple") == 0
    assert (
        run("approve", "TASK-1", "--action", "push", "--target", "TASK-1", "--user-reply", "si")
        == 0
    )
    capsys.readouterr()
    assert run("handoff", "TASK-1", "--to", "builder") == 0
    assert "abc123supersecret" not in _out(capsys)
    out = repo / "findings.md"
    assert run("findings", "TASK-1", "--out", str(out)) == 0
    assert "TASK-1" in out.read_text()
    assert run("draft", "TASK-1") == 0
    assert _out(capsys).strip()
    assert run("digest", "--max-chars", "400") == 0
    assert "TASK-1" in _out(capsys)
    assert run("config") == 0
    assert run("rounds", "TASK-1") == 0
    capsys.readouterr()
    assert run("status", "TASK-1", "--json") == 0
    status = json.loads(_out(capsys))
    for key in ("Status", "Repos", "Steps", "Decisions", "Approvals", "Debate"):
        assert key in status
    assert "use sqlite" in status["Decisions"]
    assert "push:TASK-1" in status["Approvals"]
    assert run("unbind", "TASK-1", "--repo", str(repo)) == 0


def test_error_paths_and_removed_commands_return_failure(
    run: Run, capsys: pytest.CaptureFixture[str]
) -> None:
    capsys.readouterr()
    assert run("show", "NOPE-9") != 0
    assert run("fact", "NOPE-9", "x") != 0
    assert run("step", "TASK-1", "done", "99") != 0
    for removed in (
        ("phase", "TASK-1", "work"),
        ("tdd", "TASK-1", "red"),
        ("judge", "TASK-1"),
        ("trust",),
        ("pr", "list"),
    ):
        with pytest.raises(SystemExit) as exc:
            run(*removed)
        assert exc.value.code == 2


def test_subtasks_switch_and_reject_strangers(
    run: Run, state: TaskStore, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run("new", "TASK-1-a", "--title", "Child", "--parent", "TASK-1") == 0
    assert run("switch", "TASK-1", "TASK-1-a") == 0
    assert state.get("TASK-1").active_subtask == "TASK-1-a"
    assert run("switch", "TASK-1", "TASK-9") != 0
    capsys.readouterr()
    assert run("list", "--json") == 0
    assert "TASK-1" in _out(capsys)


def test_stamp_ask_and_status_report_state(run: Run, capsys: pytest.CaptureFixture[str]) -> None:
    capsys.readouterr()
    assert run("stamp", "TASK-1") == 0
    stamp = json.loads(_out(capsys))
    assert "stamp" in stamp and "key" in stamp["stamp"]
    assert run("ask", "TASK-1", "--action", "plan", "--target", "TASK-1") == 0
    assert "taskflow approve TASK-1 --action plan" in _out(capsys)
    assert run("status", "TASK-1") == 0
    assert _out(capsys).strip()


def test_evidence_and_deploy_are_recorded(
    run: Run, state: TaskStore, repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    proof = repo / "proof.txt"
    proof.write_text("12 passed\n")
    assert run("evidence", "TASK-1", "--kind", "review", "--file", str(proof)) == 0
    sha = "a" * 40
    assert (
        run(
            "deploy",
            "TASK-1",
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
    task = state.get("TASK-1")
    assert any(sha in json.dumps(d) for d in task.deployments)
    assert list(state.evidence_dir("TASK-1").iterdir())
    capsys.readouterr()
    assert run("evidence", "TASK-1", "--kind", "review", "--file", str(proof / "missing")) != 0


def test_show_describes_parent_children_and_blockers(
    run: Run, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run("new", "TASK-1-a", "--title", "Child", "--parent", "TASK-1") == 0
    assert run("block", "TASK-1", "--owner", "dba", "--needs", "a ticket") == 0
    capsys.readouterr()
    assert run("show", "TASK-1") == 0
    parent = _out(capsys)
    assert "TASK-1-a" in parent and "dba: a ticket" in parent
    assert run("show", "TASK-1-a") == 0
    assert "TASK-1" in _out(capsys)
    assert run("show", "TASK-1", "--json", "--full") == 0
    assert "log" in json.loads(_out(capsys))


def test_steps_can_be_completed_by_text_and_bad_selectors_fail(run: Run, state: TaskStore) -> None:
    assert run("step", "TASK-1", "add", "write test") == 0
    assert run("step", "TASK-1", "done", "write test") == 0
    assert state.get("TASK-1").steps[0]["done"] is True
    assert run("step", "TASK-1", "done", "no such step") != 0


def test_task_is_resolved_from_the_branch_when_not_bound(
    run: Run, repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run("unbind", "TASK-1", "--repo", str(repo)) == 0
    capsys.readouterr()
    assert run("show") == 0
    assert "TASK-1" in _out(capsys)
    assert run("status", "--json") == 0
    assert "Status" in json.loads(_out(capsys))


def test_unresolvable_directory_asks_for_the_task_id(
    run: Run, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    assert run("show") != 0


def test_rounds_validates_missing_round(run: Run) -> None:
    assert run("rounds", "TASK-1", "--show", "99") != 0


def test_ask_for_a_risky_action_demands_the_consequence(
    run: Run, capsys: pytest.CaptureFixture[str]
) -> None:
    capsys.readouterr()
    assert run("ask", "TASK-1", "--action", "deploy", "--target", "staging") == 0
    text = _out(capsys)
    assert "breaks" in text and "--consequence" in text


def test_no_command_prints_the_help(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 0
    assert "usage" in _out(capsys).lower()


def test_duplicate_tasks_and_corrupt_state_files(run: Run, state: TaskStore) -> None:
    assert run("new", "TASK-1", "--title", "again") != 0
    broken = state.task_dir("BROKEN-1")
    broken.mkdir(parents=True)
    (broken / "state.json").write_text("{not json")
    assert [t.id for t in state.list()] == ["TASK-1"]
    assert state.exists("TASK-1") and not state.exists("BROKEN-1-nope")


def test_invalid_config_is_reported(run: Run, tmp_path: Path) -> None:
    config = tmp_path / "config" / "ai-governance"
    config.mkdir(parents=True)
    (config / "taskflow.toml").write_text('workflow = "unknown-flow"\n')
    assert run("config") != 0


def test_risky_approvals_are_rejected_until_they_name_action_and_target(
    run: Run, monkeypatch: pytest.MonkeyPatch
) -> None:
    base = ("approve", "TASK-1", "--action", "deploy", "--target", "billing")
    assert run(*base, "--user-reply", "ok") != 0
    assert run(*base, "--user-reply", " ", "--consequence", "outage") != 0
    assert run(*base, "--user-reply", "dale", "--consequence", "outage") != 0
    assert run(*base, "--user-reply", "confirmo la migracion", "--consequence", "x") != 0
    assert run(*base, "--user-reply", "confirmo deploy de otra cosa", "--consequence", "x") != 0
    monkeypatch.setattr(
        approvals,
        "datetime",
        type("D", (), {"now": staticmethod(lambda: datetime(2026, 10, 28, 10, 0))}),
    )
    assert (
        run(
            *base,
            "--user-reply",
            "confirmo deploy de billing",
            "--consequence",
            "outage",
        )
        == 0
    )


def test_stamp_tracks_links_renames_and_integration_branch(
    run: Run, repo: Path, state: TaskStore, capsys: pytest.CaptureFixture[str]
) -> None:
    origin = repo.parent / "origin.git"
    _git(repo, "branch", "develop")
    subprocess.run(["git", "clone", "-q", "--bare", str(repo), str(origin)], check=True)
    _git(repo, "remote", "add", "origin", str(origin))
    _git(repo, "fetch", "-q", "origin")
    assert run("bind", "TASK-1", "--repo", str(repo), "--integration-branch", "develop") == 0
    (repo / "link").symlink_to("app.py")
    _git(repo, "mv", "app.py", "moved.py")
    capsys.readouterr()
    assert run("stamp", "TASK-1", "--remote") == 0
    first = json.loads(_out(capsys))["stamp"]
    (repo / "link").unlink()
    (repo / "link").symlink_to("moved.py")
    assert run("stamp", "TASK-1") == 0
    assert json.loads(_out(capsys))["stamp"] != first
    repos = state.get("TASK-1").repos
    assert repos and repos[0]["integration_branch"] == "develop"


def test_stamp_falls_back_to_the_local_integration_branch_without_a_remote(
    run: Run, repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _git(repo, "branch", "develop")
    assert run("bind", "TASK-1", "--repo", str(repo), "--integration-branch", "develop") == 0
    capsys.readouterr()
    assert run("stamp", "TASK-1") == 0
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


def test_unbound_tasks_report_no_repo_and_can_close(
    run: Run, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run("new", "free-1", "--title", "No repo") == 0
    capsys.readouterr()
    assert run("status", "free-1", "--json") == 0
    assert "no repository bound" in _out(capsys)
    assert run("close", "free-1", "--reason", "done") == 0


def test_split_cli_modules_keep_their_public_paths() -> None:
    from ai_governance.taskflow import cli

    assert cli.GUIDE.startswith("Flow") and callable(cli.digest)
    assert cli._parser().prog.endswith("taskflow") or cli._parser().prog


def test_blocked_status_rounds_show_and_findings_with_settled_round(
    run: Run, state: TaskStore, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    round_file = tmp_path / "round.md"
    round_file.write_text("# Round\n## Answer\nUse bounded timeouts.\n", encoding="utf-8")
    state.mutate(
        "TASK-1",
        lambda t: t.rounds.append(
            {
                "n": 1,
                "role": "debater",
                "focus": "arch",
                "state": "settled",
                "file": str(round_file),
            }
        ),
    )
    assert run("block", "TASK-1", "--owner", "sec", "--needs", "review") == 0
    capsys.readouterr()
    assert run("status", "TASK-1", "--json") == 0
    assert json.loads(_out(capsys))["Blocked"] == "sec: review"
    assert run("rounds", "TASK-1", "--show", "1") == 0
    assert "Use bounded timeouts." in _out(capsys)
    assert run("rounds", "TASK-1", "--show", "99") == 1
    out = tmp_path / "findings.md"
    assert run("findings", "TASK-1", "--out", str(out)) == 0
    assert "Use bounded timeouts." in out.read_text(encoding="utf-8")
