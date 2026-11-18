"""Taskflow: store, stamps, approvals, resolver, context and handoff."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime
from pathlib import Path

import pytest
from ai_governance._config_core import ConfigError
from ai_governance.taskflow import approvals
from ai_governance.taskflow.approvals import (
    ApprovalContext,
    ApprovalError,
    ApprovalRequest,
    build_approval,
)
from ai_governance.taskflow.cli import main
from ai_governance.taskflow.config import FlowConfig
from ai_governance.taskflow.handoff import scrub
from ai_governance.taskflow.models import Task
from ai_governance.taskflow.resolver import TaskResolver
from ai_governance.taskflow.stamp import code_stamp, remote_sha
from ai_governance.taskflow.store import RoundSlot, TaskStore

WEEKDAY_MORNING = datetime(2026, 10, 28, 10, 0)  # Wednesday
FRIDAY_AFTERNOON = datetime(2026, 10, 30, 14, 0)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "repo"
    path.mkdir()
    _git(path, "init", "-q", "-b", "feat/TASK-1-x")
    _git(path, "config", "user.email", "t@example.com")
    _git(path, "config", "user.name", "T")
    (path / "app.py").write_text("x = 1\n")
    _git(path, "add", ".")
    _git(path, "commit", "-qm", "init")
    return path


@pytest.fixture(autouse=True)
def outside_claude(monkeypatch: pytest.MonkeyPatch) -> None:
    """Clear ambient session markers so tests stay isolated."""
    for name in ("CLAUDECODE", "CLAUDE_CODE_SESSION_ID", "AI_GOVERNANCE_LEASE_HOLDER"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TaskStore:
    monkeypatch.setenv("AI_GOVERNANCE_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("AI_GOVERNANCE_AGENT", "1")
    return TaskStore()


# -- store and tracking ----------------------------------------------------------------------
def test_tracking_commands_round_trip_and_resolve_by_branch(
    state: TaskStore, repo: Path, monkeypatch, capsys
) -> None:
    assert main(["new", "TASK-1", "--title", "Fix", "--summary", "goal"]) == 0
    assert main(["bind", "TASK-1", "--repo", str(repo), "--integration-branch", "develop"]) == 0
    assert main(["step", "TASK-1", "add", "write test"]) == 0
    assert main(["step", "TASK-1", "done", "1"]) == 0
    assert main(["fact", "TASK-1", "config lives in .coderabbit.yaml"]) == 0
    assert main(["decide", "TASK-1", "no workflow change", "--why", "minimal scope"]) == 0
    monkeypatch.chdir(repo)
    capsys.readouterr()
    assert main(["here", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["id"] == "TASK-1" and data["steps"][0]["done"] is True
    assert data["phase"] == "work"
    assert data["repos"][0]["integration_branch"] == "develop"
    assert data["decisions"][0]["why"] == "minimal scope"


def test_subtask_links_to_parent_and_becomes_active(state: TaskStore) -> None:
    assert main(["new", "TASK-1", "--title", "Epic"]) == 0
    assert main(["new", "TASK-2", "--title", "Sub", "--parent", "TASK-1"]) == 0
    parent = state.get("TASK-1")
    assert parent.subtasks == ["TASK-2"] and parent.active_subtask == "TASK-2"
    assert state.get("TASK-2").parent == "TASK-1"


def test_legacy_state_json_deserializes_cleanly(state: TaskStore) -> None:
    legacy = {
        "id": "OLD-1",
        "title": "Legacy task",
        "policy": {"judges": ["correctness"]},
        "tdd": {"skip": {"reason": "old"}},
        "prs": [{"repo": "org/repo", "number": 1}],
        "pr_removed": ["org/repo#2"],
    }
    task = Task.from_dict(legacy)
    assert task.id == "OLD-1" and task.phase == "work"
    tdir = state.task_dir("OLD-1")
    tdir.mkdir(parents=True)
    (tdir / "state.json").write_text(json.dumps(legacy), encoding="utf-8")
    loaded = state.get("OLD-1")
    assert loaded.id == "OLD-1" and loaded.title == "Legacy task"


def test_close_honors_reason_without_gates(state: TaskStore, repo: Path) -> None:
    main(["new", "TASK-1", "--title", "Fix"])
    main(["bind", "TASK-1", "--repo", str(repo)])
    assert main(["close", "TASK-1", "--reason", "done cleanly"]) == 0
    assert state.get("TASK-1").status == "closed"
    assert "done cleanly" in state.read_log("TASK-1")


def test_round_numbers_are_unique_and_the_index_is_rebuilt(state: TaskStore) -> None:
    state.create(Task(id="T", title="t"))
    first = state.reserve_round("T", RoundSlot("work", "debater", "agy"))
    second = state.reserve_round("T", RoundSlot("work", "debater", "agy"))
    assert (first[0], second[0]) == (1, 2)
    state.mutate(
        "T",
        lambda t: t.rounds.append({"n": 2, "phase": "work", "role": "debater", "state": "valid"}),
    )
    assert "| 002 |" in (state.rounds_dir("T") / "index.md").read_text()


def test_invalid_task_ids_are_rejected(state: TaskStore) -> None:
    with pytest.raises(ValueError):
        state.task_dir("../escape")


# -- code stamp ----------------------------------------------------------------------------
def test_stamp_changes_with_untracked_staged_and_renamed_files(repo: Path) -> None:
    binding = [{"path": str(repo)}]
    base = code_stamp(binding, "p")["key"]
    (repo / "new.py").write_text("y = 2\n")
    untracked = code_stamp(binding, "p")["key"]
    _git(repo, "add", "new.py")
    (repo / "new.py").write_text("y = 3\n")
    edited = code_stamp(binding, "p")["key"]
    _git(repo, "mv", "app.py", "renamed.py")
    renamed = code_stamp(binding, "p")
    assert len({base, untracked, edited, renamed["key"]}) == 4
    assert renamed["repos"][0]["dirty"] is True


def test_stamp_changes_when_the_integration_base_moves(repo: Path) -> None:
    _git(repo, "branch", "develop")
    binding = [{"path": str(repo), "integration_branch": "develop"}]
    before = code_stamp(binding, "p")
    _git(repo, "checkout", "-q", "develop")
    (repo / "other.py").write_text("z = 1\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "develop moves")
    _git(repo, "checkout", "-q", "feat/TASK-1-x")
    _git(repo, "merge", "-q", "--no-edit", "develop")
    after = code_stamp(binding, "p")
    assert before["repos"][0]["base"] != after["repos"][0]["base"]
    assert before["key"] != after["key"]


def test_stamp_changes_when_the_policy_changes(repo: Path) -> None:
    binding = [{"path": str(repo)}]
    assert code_stamp(binding, "a")["key"] != code_stamp(binding, "b")["key"]


def test_remote_sha_is_unverified_without_remote_and_verified_with_one(
    repo: Path, tmp_path: Path
) -> None:
    assert remote_sha(repo, "develop") == ("", "unverified")
    bare = tmp_path / "origin.git"
    _git(tmp_path, "clone", "-q", "--bare", str(repo), str(bare))
    _git(bare, "branch", "develop", "feat/TASK-1-x")
    _git(repo, "remote", "add", "origin", str(bare))
    sha, status = remote_sha(repo, "develop")
    assert status == "verified" and sha == _git(repo, "rev-parse", "HEAD").strip()


# -- approvals -----------------------------------------------------------------------------
CONSEQUENCE = "if it goes wrong it may wipe the production database"
DEPLOY_REPLY = "confirmo deploy de api a producción"


def _approve(
    base: ApprovalRequest,
    moment: datetime = WEEKDAY_MORNING,
    previous: list | None = None,
) -> dict:
    request = ApprovalRequest(
        base.action,
        base.target,
        base.user_reply,
        base.consequence,
        task_id="T",
        reference=base.reference or "k1",
    )
    return build_approval(request, ApprovalContext("k1", moment, previous))


def test_risky_approval_needs_consequence_named_action_and_target() -> None:
    with pytest.raises(ApprovalError, match="consequence"):
        _approve(ApprovalRequest("deploy", "api", DEPLOY_REPLY))
    with pytest.raises(ApprovalError, match="generic"):
        _approve(ApprovalRequest("deploy", "api", "dale", CONSEQUENCE))
    with pytest.raises(ApprovalError, match="target"):
        _approve(ApprovalRequest("deploy", "billing", DEPLOY_REPLY, CONSEQUENCE))
    record = _approve(ApprovalRequest("deploy", "api", DEPLOY_REPLY, CONSEQUENCE))
    assert record["verified"] == "declared" and record["stamp"] == "k1" and record["risky"] is True


def test_approvals_work_deterministically_across_all_agents_and_manual_tasks(
    state: TaskStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Even with Claude session env vars set, no ~/.claude/projects transcript scan is required.
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "missing-session")
    assert main(["new", "MAN-1", "--title", "Manual", "--workflow", "manual"]) == 0
    assert (
        main(["approve", "MAN-1", "--action", "push", "--target", "MAN-1", "--user-reply", "ok"])
        == 0
    )
    monkeypatch.setattr(
        approvals, "datetime", type("D", (), {"now": staticmethod(lambda: WEEKDAY_MORNING)})
    )
    assert (
        main(
            [
                "approve",
                "MAN-1",
                "--action",
                "deploy",
                "--target",
                "api",
                "--user-reply",
                DEPLOY_REPLY,
                "--consequence",
                CONSEQUENCE,
            ]
        )
        == 0
    )
    stored = state.get("MAN-1").approvals
    assert [a["action"] for a in stored] == ["push", "deploy"]
    assert all(a["verified"] == "declared" for a in stored)


def test_request_tag_formats_task_action_target_and_reference() -> None:
    tag = approvals.request_tag(
        ApprovalRequest("deploy", "api", "", task_id="T-1", reference="stamp1")
    )
    assert tag == "[approval T-1 · deploy · api · stamp1]"


def test_production_actions_are_refused_outside_the_window() -> None:
    with pytest.raises(ApprovalError, match="window"):
        _approve(ApprovalRequest("deploy", "api", DEPLOY_REPLY, CONSEQUENCE), FRIDAY_AFTERNOON)
    assert approvals.outside_production_window(datetime(2026, 10, 28, 16, 0))
    assert not approvals.outside_production_window(datetime(2026, 10, 30, 12, 59))


def test_production_risk_window_defaults() -> None:
    assert approvals.production_window_cutoffs() == (16, 13)
    assert not approvals.outside_production_window(datetime(2026, 10, 28, 15, 59))
    assert approvals.outside_production_window(datetime(2026, 10, 28, 16, 0))
    assert not approvals.outside_production_window(datetime(2026, 10, 30, 12, 59))
    assert approvals.outside_production_window(datetime(2026, 10, 30, 13, 0))
    assert approvals.outside_production_window(datetime(2026, 10, 31, 10, 0))


def test_production_risk_window_configurable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_GOVERNANCE_RISK_WINDOW_CUTOFF_HOUR", "18")
    monkeypatch.setenv("AI_GOVERNANCE_RISK_WINDOW_FRIDAY_CUTOFF_HOUR", "15")
    assert approvals.production_window_cutoffs() == (18, 15)

    wednesday_late = datetime(2026, 10, 28, 16, 30)
    assert not approvals.outside_production_window(wednesday_late)
    assert approvals.outside_production_window(datetime(2026, 10, 28, 18, 0))

    friday_afternoon = datetime(2026, 10, 30, 14, 0)
    assert not approvals.outside_production_window(friday_afternoon)
    assert approvals.outside_production_window(datetime(2026, 10, 30, 15, 0))

    record = _approve(ApprovalRequest("deploy", "api", DEPLOY_REPLY, CONSEQUENCE), friday_afternoon)
    assert record["action"] == "deploy"

    with pytest.raises(ApprovalError, match=r"never after 18:00, nor Friday after 15:00"):
        _approve(
            ApprovalRequest("deploy", "api", DEPLOY_REPLY, CONSEQUENCE),
            datetime(2026, 10, 30, 15, 30),
        )


def test_production_risk_window_invalid_hour_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_GOVERNANCE_RISK_WINDOW_CUTOFF_HOUR", "25")
    with pytest.raises(
        ConfigError, match=r"Invalid value for risk_window\.cutoff_hour: 25.*0 and 23"
    ):
        approvals.production_window_cutoffs()

    with pytest.raises(
        ConfigError, match=r"Invalid value for risk_window\.cutoff_hour: 25.*0 and 23"
    ):
        approvals.outside_production_window(datetime(2026, 10, 28, 12, 0))

    with pytest.raises(ConfigError, match=r"Invalid value for risk_window\.cutoff_hour: 25"):
        _approve(
            ApprovalRequest("deploy", "api", DEPLOY_REPLY, CONSEQUENCE),
            datetime(2026, 10, 28, 12, 0),
        )

    monkeypatch.setenv("AI_GOVERNANCE_RISK_WINDOW_CUTOFF_HOUR", "16")
    monkeypatch.setenv("AI_GOVERNANCE_RISK_WINDOW_FRIDAY_CUTOFF_HOUR", "-1")
    with pytest.raises(ConfigError, match=r"Invalid value for risk_window\.friday_cutoff_hour: -1"):
        approvals.production_window_cutoffs()

    with pytest.raises(ConfigError, match=r"0 and 23"):
        approvals.outside_production_window(datetime(2026, 10, 28, 12, 0), cutoff_hour=24)
    with pytest.raises(ConfigError, match=r"0 and 23"):
        approvals.outside_production_window(
            datetime(2026, 10, 30, 12, 0), cutoff_hour=16, friday_cutoff_hour=24
        )


def test_approvals_are_bound_to_target_and_code() -> None:
    record = {"action": "push", "target": "TASK-1", "stamp": "k1"}
    assert approvals.valid_approval([record], "push", "k1", "TASK-1") is record
    assert approvals.valid_approval([record], "push", "k2", "TASK-1") is None
    assert approvals.valid_approval([record], "push", "k1", "TASK-2") is None


# -- config validation ---------------------------------------------------------------------
def test_invalid_configs_are_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PATH", "/nonexistent")
    monkeypatch.delenv("ORCA_CLI_COMMAND", raising=False)
    errors = FlowConfig(workflow="bogus").validate()
    assert any("workflow" in e for e in errors)
    assert not any("Orca" in e for e in errors)


# -- handoff, resolver, context ------------------------------------------------------------
def test_handoff_scrubs_secrets() -> None:
    assert "ghp_" not in scrub("token ghp_" + "a" * 30)
    assert scrub("password=hunter2 rest") == "[redacted] rest"


def test_resolver_reads_the_jira_key_from_the_branch(repo: Path) -> None:
    _git(repo, "checkout", "-q", "-b", "feat/task-77-thing")
    assert TaskResolver.resolve_from_git(repo) == "TASK-77"
    assert TaskResolver.resolve_from_git(repo.parent / "missing") is None


def test_several_tasks_on_one_repository_narrow_to_one_or_name_the_candidates(
    state: TaskStore, repo: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    monkeypatch.chdir(repo)
    assert main(["new", "P", "--title", "parent"]) == 0
    assert main(["new", "A", "--title", "a", "--parent", "P"]) == 0
    assert main(["new", "B", "--title", "b", "--parent", "P"]) == 0
    for task_id in ("P", "A", "B"):
        assert main(["bind", task_id, "--repo", str(repo)]) == 0
    capsys.readouterr()
    assert main(["here"]) == 0
    assert "B" in capsys.readouterr().out
    assert main(["switch", "P", "A"]) == 0
    capsys.readouterr()
    assert main(["here", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["id"] == "A"
    assert main(["switch", "P", "B"]) == 0
    capsys.readouterr()
    assert main(["here", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["id"] == "B"


def test_several_unrelated_tasks_on_one_repository_still_name_the_candidates(
    state: TaskStore, repo: Path, monkeypatch, capsys
) -> None:
    monkeypatch.chdir(repo)
    for task_id in ("X", "Y"):
        assert main(["new", task_id, "--title", task_id]) == 0
        assert main(["bind", task_id, "--repo", str(repo)]) == 0
    capsys.readouterr()
    assert main(["here"]) != 0
    assert "Several tasks are bound here (X, Y)" in capsys.readouterr().err


def test_the_branch_key_picks_inside_the_narrowed_bound_tasks(state: TaskStore, repo: Path) -> None:
    tasks = [
        Task(id="TASK-1", title="p", repos=[{"path": str(repo)}], active_subtask="SUB"),
        Task(id="SUB", title="c", parent="TASK-1", repos=[{"path": str(repo)}]),
    ]
    assert TaskResolver.resolve_from_context(tasks, repo) == "SUB"
    paused = [
        Task(id="TASK-1", title="p", status="paused", repos=[{"path": str(repo)}]),
        Task(id="OTHER", title="o", repos=[{"path": str(repo)}]),
    ]
    assert TaskResolver.resolve_from_context(paused, repo) == "OTHER"
    assert TaskResolver.resolve_from_context([Task(id="TASK-1", title="u")], repo) == "TASK-1"


def test_bind_from_a_subdirectory_stores_the_repository_top_level(
    state: TaskStore, repo: Path
) -> None:
    (repo / "sub").mkdir()
    assert main(["new", "T", "--title", "t"]) == 0
    assert main(["bind", "T", "--repo", str(repo / "sub")]) == 0
    assert state.get("T").repos[0]["path"] == str(repo.resolve())
    assert TaskResolver.bound_to([state.get("T")], repo / "sub") == ["T"]
    assert main(["unbind", "T", "--repo", str(repo / "sub")]) == 0
    assert state.get("T").repos == []


def test_workflow_approval_is_not_marked_stale_when_code_changes() -> None:
    from ai_governance.taskflow.cli import _approvals_summary

    task = Task(id="T", title="t", code_stamp={"key": "new"})
    task.approvals += [
        {"action": "workflow", "target": "T", "stamp": "old"},
        {"action": "plan", "target": "T", "stamp": "old"},
        {"action": "prod", "target": "T", "stamp": "old"},
    ]
    summary = _approvals_summary(task)
    assert "workflow:T" in summary and "workflow:T (stale)" not in summary
    assert "plan:T (stale)" not in summary
    assert "prod:T (stale)" in summary


def test_round_header_uses_the_highest_engine_plan_capped_and_scrubbed(state: TaskStore) -> None:
    from ai_governance.taskflow.context import FIELD_CHARS, round_header

    token = "ghp_" + "a" * 30
    task = Task(id="T", title="t", summary="s" * 1000)
    task.facts.append({"text": f"password: hunter2 {token}"})
    task.rounds += [
        {
            "n": 2,
            "role": "planner",
            "agent": "agy",
            "state": "valid",
            "source": "engine",
            "file": "r2.md",
        },
        {
            "n": 1,
            "role": "planner",
            "agent": "agy",
            "state": "valid",
            "source": "engine",
            "file": "r1.md",
        },
        {
            "n": 5,
            "role": "planner",
            "agent": "agy",
            "state": "context",
            "source": "manual",
            "file": "r5.md",
        },
        {
            "n": 6,
            "role": "planner",
            "agent": "agy",
            "state": "invalid",
            "source": "engine",
            "file": "r6.md",
        },
    ]
    state.create(task)
    state.mutate("T", lambda t: t.rounds.extend(task.rounds))
    header = round_header(state, "T", "validator")
    assert "Latest plan (read it first): r2.md" in header
    assert "s" * (FIELD_CHARS + 1) not in header
    assert "hunter2" not in header and token not in header


def test_main_reports_a_timeout_as_an_error(monkeypatch) -> None:
    def handler(_args: object) -> int:
        raise subprocess.TimeoutExpired("x", 1)

    parser_args = type("A", (), {"handler": staticmethod(handler)})
    monkeypatch.setattr(
        "ai_governance.taskflow.cli._parser",
        lambda: type("P", (), {"parse_args": lambda self, argv: parser_args})(),
    )
    assert main([]) == 1


def test_status_parsing_skips_a_truncated_rename_entry(monkeypatch, tmp_path: Path) -> None:
    from ai_governance.taskflow import stamp

    monkeypatch.setattr(stamp, "git", lambda *_a, **_k: "R  new.py")
    assert stamp.changed_paths(tmp_path) == ["new.py"]


def test_ticket_draft_and_friction_file_are_in_english(state: TaskStore) -> None:
    from ai_governance.taskflow import handoff
    from ai_governance.taskflow.store import FRICTION_FILE

    assert FRICTION_FILE == "friction.md"
    main(["new", "TASK-1", "--title", "Fix"])
    draft = handoff.ticket_draft(state.get("TASK-1"))
    assert "**Done**" in draft and "Hecho" not in draft and "**PRs**" not in draft
