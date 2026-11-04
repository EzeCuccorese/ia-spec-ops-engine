"""A bound repository that vanished from disk never blocks a command or weakens a gate.

Repositories are real temporary git repos that the tests delete; the policy a repository
defines is modelled by a config function that stops returning it once that repo is gone.
"""

# ruff: noqa: F401, F811
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple

import pytest
from ai_governance import hooks
from ai_governance.taskflow import cli, gates, judge, repos, rounds, stamp, tdd
from ai_governance.taskflow.cli import main
from ai_governance.taskflow.config import FlowConfig, RiskRule
from ai_governance.taskflow.judge import JudgeScope
from ai_governance.taskflow.judge_flow import JudgeJob, judge_flow
from ai_governance.taskflow.models import Task
from ai_governance.taskflow.risk import assess, merge
from ai_governance.taskflow.store import TaskStore
from orca_fakes import attach_orca
from test_taskflow import _git, outside_claude, repo, state  # shared fixtures

WARNING = "bound repo not found, skipped: {}"
GONE = "no bound repo exists on disk"
TASK = "ONB-1"

ConfigFor = Callable[[Task], FlowConfig]


def _new_repo(root: Path, name: str, files: dict[str, str] | None = None) -> Path:
    path = (root / name).resolve()
    path.mkdir()
    _git(path, "init", "-q", "-b", "main")
    _git(path, "config", "user.email", "t@example.com")
    _git(path, "config", "user.name", "T")
    (path / "app.py").write_text("x = 1\n")
    _git(path, "add", ".")
    _git(path, "commit", "-qm", "init")
    if files:
        _git(path, "checkout", "-q", "-b", "feat")
        for rel, text in files.items():
            (path / rel).parent.mkdir(parents=True, exist_ok=True)
            (path / rel).write_text(text)
        _git(path, "add", ".")
        _git(path, "commit", "-qm", "work")
    return path


def _flat(*, judges: tuple[dict, ...] = (), rules: tuple[RiskRule, ...] = ()) -> FlowConfig:
    return FlowConfig(judges=judges, checks=(), risk_rules=rules)


def _bind(*paths: Path, integration: str = "") -> None:
    assert main(["new", TASK, "--title", "t", "--summary", "s"]) == 0
    for path in paths:
        extra = ["--integration-branch", integration] if integration else []
        assert main(["bind", TASK, "--repo", str(path), *extra]) == 0


@pytest.fixture(autouse=True)
def _orca_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """`judge` needs the Orca CLI on PATH; CI has none, so the fake one goes in front."""
    attach_orca(tmp_path / "orca-world", monkeypatch)
    return tmp_path / "orca-world"


def _use(monkeypatch: pytest.MonkeyPatch, config_for: ConfigFor) -> None:
    monkeypatch.setattr(cli, "_config", config_for)


def _finish(
    state: TaskStore, *, passed: tuple[str, ...] = (), reviewed: tuple[str, ...] = ()
) -> str:
    """Stamp the task, then record everything a closable task at that key has."""
    assert main(["stamp", TASK]) == 0
    key = state.get(TASK).stamp_key

    def done(task: Task) -> None:
        task.phase = "done"
        task.tdd = {"skip": {"reason": "user"}}
        for entry in task.code_stamp["repos"]:
            task.evidence.append(
                {"kind": "checks", "repo": entry["repo"], "stamp": key, "passed": True}
            )
        for focus in passed:
            task.rounds.append(
                {
                    "n": len(task.rounds) + 1,
                    "role": "judge",
                    "focus": focus,
                    "verdict": "pass",
                    "stamp": key,
                    "state": "valid",
                    "source": "engine",
                }
            )
        for focus in reviewed:
            task.approvals.append({"action": "review", "target": focus, "stamp": key})
        task.approvals.append({"action": "prod", "target": task.id, "stamp": key})

    state.mutate(TASK, done)
    return key


def _warnings(capsys: pytest.CaptureFixture[str], path: Path | str) -> int:
    return capsys.readouterr().err.splitlines().count(WARNING.format(path))


def _sec_rule() -> RiskRule:
    return RiskRule("sec", ("zz/*",), judges=("security",), checks=("extra",), restaging=True)


def _stamp_json(capsys: pytest.CaptureFixture[str]) -> dict:
    assert main(["stamp", TASK]) == 0
    return json.loads(capsys.readouterr().out)["stamp"]


# -- the bug and every command that went through the same code ---------------------------------
def test_close_succeeds_when_a_bound_repo_is_gone(
    state: TaskStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    path = _new_repo(tmp_path, "a")
    _bind(path)
    _use(monkeypatch, lambda task: _flat())
    _finish(state)
    shutil.rmtree(path)
    capsys.readouterr()
    assert main(["close", TASK]) == 0
    captured = capsys.readouterr()
    assert state.get(TASK).status == "closed"
    assert captured.err.splitlines() == [WARNING.format(path)]


ARGV = {
    "status": ["status", TASK],
    "stamp": ["stamp", TASK],
    "phase": ["phase", TASK, "judge"],
    "approve": ["approve", TASK, "--action", "review", "--target", "x", "--user-reply", "ok"],
    "ask": ["ask", TASK, "--action", "review", "--target", "x"],
    "round-record": ["round", TASK, "record", "--role", "planner", "--file", "{note}"],
}
REFUSED = {
    "tdd": ["tdd", TASK, "red", "--cmd", "true"],
    "judge": ["judge", TASK],
}


@pytest.fixture
def gone(state: TaskStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> Path:
    path = _new_repo(tmp_path, "a")
    _bind(path)
    _use(monkeypatch, lambda task: _flat(judges=HUMAN))
    _finish(state, reviewed=("design",))
    shutil.rmtree(path)
    (tmp_path / "note.md").write_text("context\n")
    capsys.readouterr()
    return path


@pytest.mark.parametrize("name", sorted(ARGV))
def test_command_survives_a_missing_repo(name: str, gone: Path, tmp_path: Path, capsys) -> None:
    argv = [str(tmp_path / "note.md") if a == "{note}" else a for a in ARGV[name]]
    assert main(argv) == 0
    assert capsys.readouterr().err.splitlines().count(WARNING.format(gone)) == 1


@pytest.mark.parametrize("name", sorted(REFUSED))
def test_commands_that_need_a_working_tree_say_so(name: str, gone: Path, capsys) -> None:
    assert main(REFUSED[name]) == 1
    err = capsys.readouterr().err
    assert GONE in err and "Errno 2" not in err and "Traceback" not in err


def test_show_and_digest_do_not_crash(gone: Path, capsys) -> None:
    assert main(["show", TASK]) == 0 and main(["digest", "--id", TASK]) == 0
    captured = capsys.readouterr()
    assert str(gone) in captured.out and "bound repo not found" not in captured.err


def test_session_end_hook_survives_a_vanished_cwd(
    state: TaskStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert main(["new", TASK, "--title", "t", "--summary", "s"]) == 0
    missing = tmp_path / "vanished"
    monkeypatch.setattr(hooks, "_cwd", lambda payload: missing)
    monkeypatch.setattr(hooks, "_payload", lambda: {})
    monkeypatch.setattr(hooks, "_active_task", lambda cwd: (state, TASK))
    assert hooks._claude_session_end() == 0
    log = state.read_log(TASK)
    assert "Session ended on ?" in log and "unknown number of uncommitted" in log


def test_existing_repo_is_unaffected(
    state: TaskStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    path = _new_repo(tmp_path, "a")
    _bind(path)
    _use(monkeypatch, lambda task: _flat())
    _finish(state)
    capsys.readouterr()
    assert main(["status", TASK]) == 0 and main(["close", TASK]) == 0
    assert "bound repo not found" not in capsys.readouterr().err
    assert not any(e.get("missing") for e in state.get(TASK).code_stamp["repos"])


def test_two_repos_one_deleted_warns_once_for_the_deleted_one(
    state: TaskStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    first, second = _new_repo(tmp_path, "a"), _new_repo(tmp_path, "b")
    _bind(first, second)
    _use(monkeypatch, lambda task: _flat())
    _finish(state)
    shutil.rmtree(second)
    capsys.readouterr()
    assert main(["close", TASK]) == 0
    err = capsys.readouterr().err.splitlines()
    assert err == [WARNING.format(second)]


def test_two_missing_paths_give_two_lines_and_each_invocation_warns_again(
    state: TaskStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    first, second = _new_repo(tmp_path, "a"), _new_repo(tmp_path, "b")
    _bind(first, second)
    _use(monkeypatch, lambda task: _flat())
    shutil.rmtree(first)
    shutil.rmtree(second)
    capsys.readouterr()
    assert main(["status", TASK]) == 0
    assert sorted(capsys.readouterr().err.splitlines()) == sorted(
        [WARNING.format(first), WARNING.format(second)]
    )
    assert main(["status", TASK]) == 0
    assert len(capsys.readouterr().err.splitlines()) == 2


def test_repo_deleted_between_listing_and_git_is_reported_once(
    state: TaskStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    path = _new_repo(tmp_path, "a")
    _bind(path)
    _use(monkeypatch, lambda task: _flat())

    def vanishing(repo_dir: Path, **kwargs: object) -> dict:
        shutil.rmtree(repo_dir)
        raise stamp.GitError("git branch --show-current: [Errno 2]") from FileNotFoundError(
            2, "No such file or directory", str(repo_dir)
        )

    monkeypatch.setattr(stamp, "repo_stamp", vanishing)
    capsys.readouterr()
    assert main(["status", TASK]) == 0
    assert capsys.readouterr().err.splitlines() == [WARNING.format(path)]


def test_a_failing_repo_that_still_exists_still_raises(
    state: TaskStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    path = _new_repo(tmp_path, "a")
    _bind(path)
    _use(monkeypatch, lambda task: _flat())

    def broken(repo_dir: Path, **kwargs: object) -> dict:
        raise stamp.GitError("git: boom")

    monkeypatch.setattr(stamp, "repo_stamp", broken)
    assert main(["status", TASK]) == 1
    assert "boom" in capsys.readouterr().err


# -- eligibility survives the deletion ---------------------------------------------------------
def _holder(path: Path, judges: tuple[dict, ...], rules: tuple[RiskRule, ...] = ()) -> ConfigFor:
    """The policy lives in ``path``'s config file: it disappears with that repository."""
    return lambda task: _flat(judges=judges, rules=rules) if path.exists() else _flat()


ENGINE = ({"focus": "sec", "agent": "codex", "model": "m"},)
HUMAN = ({"focus": "design", "agent": "human"},)


def test_two_repos_policy_repo_gone_keeps_eligibility_and_control_blocks(
    state: TaskStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    first, second = _new_repo(tmp_path, "a"), _new_repo(tmp_path, "b")
    _bind(first, second)
    _use(monkeypatch, _holder(second, ENGINE))
    _finish(state, passed=("sec",))
    shutil.rmtree(second)
    assert main(["close", TASK]) == 0


def test_close_is_still_blocked_without_the_judge_round(
    state: TaskStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    first, second = _new_repo(tmp_path, "a"), _new_repo(tmp_path, "b")
    _bind(first, second)
    _use(monkeypatch, _holder(second, ENGINE))
    _finish(state)
    shutil.rmtree(second)
    capsys.readouterr()
    assert main(["close", TASK]) == 1
    assert "judge 'sec'" in capsys.readouterr().err


def test_vanished_human_only_focus_closes_with_its_review_approval(
    state: TaskStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    first, second = _new_repo(tmp_path, "a"), _new_repo(tmp_path, "b")
    _bind(first, second)
    _use(monkeypatch, _holder(second, HUMAN))
    _finish(state, reviewed=("design",))
    shutil.rmtree(second)
    assert main(["status", TASK]) == 0 and main(["close", TASK]) == 0


def test_vanished_human_focus_without_its_approval_stays_blocked(
    state: TaskStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    first, second = _new_repo(tmp_path, "a"), _new_repo(tmp_path, "b")
    _bind(first, second)
    _use(monkeypatch, _holder(second, HUMAN))
    _finish(state)
    shutil.rmtree(second)
    capsys.readouterr()
    assert main(["close", TASK]) == 1
    assert "judge 'design' (human)" in capsys.readouterr().err


def test_obligations_come_from_all_paths_not_a_truncated_list(
    state: TaskStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    files = {f"a/{n:04d}.txt": "x" for n in range(600)} | {"zz/last.txt": "x"}
    first = _new_repo(tmp_path, "a")
    second = _new_repo(tmp_path, "b", files)
    _bind(first)
    assert main(["bind", TASK, "--repo", str(second), "--integration-branch", "main"]) == 0
    _use(monkeypatch, _holder(second, (), (_sec_rule(),)))
    _finish(state)
    shutil.rmtree(second)
    capsys.readouterr()
    assert main(["close", TASK]) == 1
    assert "judge 'security'" in capsys.readouterr().err
    task = state.get(TASK)
    _, risk = cli._refresh(state, task, cli._config(task))
    assert risk.restaging and "extra" in risk.checks and "security" in risk.judges


def test_old_state_without_frozen_obligations_is_reconstructed_conservatively(
    state: TaskStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    first, second = _new_repo(tmp_path, "a"), _new_repo(tmp_path, "b")
    _bind(first, second)
    _use(monkeypatch, _holder(second, (), (_sec_rule(),)))
    _finish(state)  # no path matches the rule: only the stored policy remembers it
    state.mutate(TASK, lambda t: t.code_stamp.pop("obligations", None))
    shutil.rmtree(second)
    capsys.readouterr()
    assert main(["close", TASK]) == 1
    assert "judge 'security'" in capsys.readouterr().err


def test_a_new_check_in_the_live_config_does_not_change_frozen_obligations(
    state: TaskStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first, second = _new_repo(tmp_path, "a"), _new_repo(tmp_path, "b")
    _bind(first, second)
    _use(monkeypatch, lambda task: _flat())
    _finish(state)
    shutil.rmtree(second)
    task = state.get(TASK)
    grown = FlowConfig(judges=(), checks=("newly-added",), risk_rules=())
    _, risk = cli._refresh(state, task, grown)
    assert "newly-added" not in risk.checks


# -- the stamp is frozen, whatever command sees the deletion first ------------------------------
def test_delete_then_status_then_stamp_then_approve_then_close(
    state: TaskStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    first, second = _new_repo(tmp_path, "a"), _new_repo(tmp_path, "b")
    _bind(first, second)
    _use(monkeypatch, _holder(second, ENGINE))
    key = _finish(state, passed=("sec",))
    shutil.rmtree(second)
    capsys.readouterr()
    assert main(["status", TASK]) == 0
    out = capsys.readouterr().out
    assert "repo gone (stamp frozen)" in out and str(second) in out
    assert state.get(TASK).stamp_key == key
    assert _stamp_json(capsys)["key"] == key
    approve = ["approve", TASK, "--action", "review", "--target", "x", "--user-reply", "ok"]
    assert main(approve) == 0 and state.get(TASK).stamp_key == key
    carried = [e for e in state.get(TASK).code_stamp["repos"] if e["repo"] == str(second)]
    assert carried and carried[0]["missing"] is True
    assert main(["close", TASK]) == 0


def test_delete_status_close_equals_delete_close(
    state: TaskStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    first, second = _new_repo(tmp_path, "a"), _new_repo(tmp_path, "b")
    _bind(first, second)
    _use(monkeypatch, _holder(second, ENGINE))
    key = _finish(state, passed=("sec",))
    shutil.rmtree(first)
    shutil.rmtree(second)
    assert main(["status", TASK]) == 0 and main(["close", TASK]) == 0
    assert state.get(TASK).stamp_key == key


def test_all_repos_gone_and_no_stored_stamp_does_not_crash(
    state: TaskStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    path = _new_repo(tmp_path, "a")
    _bind(path)
    _use(monkeypatch, lambda task: _flat())
    shutil.rmtree(path)
    assert main(["status", TASK]) == 0 and main(["stamp", TASK]) == 0
    assert main(["close", TASK]) == 1  # not finished: refused for its phase, not for a crash
    assert "Errno 2" not in capsys.readouterr().err


def test_stamp_with_a_live_repo_has_no_missing_flag(
    state: TaskStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    path = _new_repo(tmp_path, "a")
    _bind(path)
    _use(monkeypatch, lambda task: _flat())
    capsys.readouterr()
    assert all("missing" not in entry for entry in _stamp_json(capsys)["repos"])


def test_close_abandon_still_works(
    state: TaskStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _new_repo(tmp_path, "a")
    _bind(path)
    shutil.rmtree(path)
    assert main(["close", TASK, "--abandon", "--reason", "gone"]) == 0


def test_tdd_uses_the_first_live_repo(
    state: TaskStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first, second = _new_repo(tmp_path, "a"), _new_repo(tmp_path, "b")
    _bind(first, second)
    _use(monkeypatch, lambda task: _flat())
    shutil.rmtree(first)
    seen: list[Path] = []

    def spy_tdd(command: str, cwd: Path) -> tuple[int, str]:
        seen.append(cwd)
        raise ValueError("captured")

    monkeypatch.setattr(tdd, "run_test", spy_tdd)
    assert main(["tdd", TASK, "red", "--cmd", "true"]) == 1
    assert seen == [second]


# -- units ---------------------------------------------------------------------------------------
def test_partition_keeps_order_counts_symlinked_dirs_live_and_files_missing(tmp_path: Path) -> None:
    live, link, afile = tmp_path / "live", tmp_path / "link", tmp_path / "file"
    live.mkdir()
    link.symlink_to(live, target_is_directory=True)
    afile.write_text("x")
    bindings = [{"path": str(p)} for p in (afile, live, tmp_path / "none", link)]
    found = repos.partition(bindings)
    assert [b["path"] for b in found.live] == [str(live), str(link)]
    assert [b["path"] for b in found.missing] == [str(afile), str(tmp_path / "none")]


def test_guard_reraises_when_the_path_still_exists(tmp_path: Path) -> None:
    def boom(path: Path) -> str:
        raise stamp.GitError("boom")

    with pytest.raises(stamp.GitError):
        repos.guard({"path": str(tmp_path)}, boom)
    gone = tmp_path / "gone"
    with pytest.raises(stamp.GitError):  # not a missing-file error: not blamed on the path
        repos.guard({"path": str(gone)}, boom)

    def denied(path: Path) -> str:
        raise PermissionError(13, "denied", str(tmp_path / "store"))

    with pytest.raises(PermissionError):
        repos.guard({"path": str(gone)}, denied)

    def enoent(path: Path) -> str:
        raise stamp.GitError("git x") from FileNotFoundError(2, "no", str(gone))

    assert repos.guard({"path": str(gone)}, enoent) is None


def test_judge_flow_without_any_live_repo_is_refused(
    state: TaskStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _new_repo(tmp_path, "a")
    _bind(path)
    shutil.rmtree(path)
    task = state.get(TASK)
    from ai_governance.taskflow.gates import GateContext

    config = _flat()
    with pytest.raises(ValueError, match=GONE):
        ctx = GateContext(config, assess(config, []), "k")
        list(judge_flow(JudgeJob(state, task, ctx, JudgeScope()), lambda: "k"))


def test_merge_only_adds_obligations() -> None:
    rule = _sec_rule()
    base = assess(_flat(rules=(rule,)), ["zz/a"])
    merged = merge(assess(_flat(), []), base)
    assert merged.judges == ("security",) and merged.restaging and merged.checks == ("extra",)
    assert merge(base, assess(_flat(), [])).judges == ("security",)


def test_code_stamp_with_carried_entry_keeps_the_key(tmp_path: Path) -> None:
    path = _new_repo(tmp_path, "a")
    binding = {"path": str(path)}
    before = stamp.code_stamp([binding], "digest")
    shutil.rmtree(path)
    after = stamp.code_stamp([binding], "digest", carried=before["repos"])
    assert after["key"] == before["key"] and after["repos"][0]["missing"] is True
    assert stamp.code_stamp([binding], "digest")["repos"] == []


# -- review follow-up: frozen judge types, legacy collisions, races -------------------------------
def _swapped(path: Path, while_present: tuple[dict, ...], after: tuple[dict, ...]) -> ConfigFor:
    """The focus is typed one way by ``path``'s config and the other way without it."""
    return lambda task: _flat(judges=while_present if path.exists() else after)


def _two_repos(tmp_path: Path) -> tuple[Path, Path]:
    first, second = _new_repo(tmp_path, "a"), _new_repo(tmp_path, "b")
    _bind(first, second)
    return first, second


def test_frozen_human_focus_is_not_turned_into_an_engine_one_by_a_live_namesake(
    state: TaskStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, second = _two_repos(tmp_path)
    live_engine = ({"focus": "design", "agent": "codex", "model": "m"},)
    _use(monkeypatch, _swapped(second, HUMAN, live_engine))
    _finish(state, reviewed=("design",))
    shutil.rmtree(second)
    assert main(["status", TASK]) == 0 and main(["close", TASK]) == 0


def test_frozen_engine_focus_is_not_weakened_to_human_by_a_live_namesake(
    state: TaskStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    _, second = _two_repos(tmp_path)
    live_human = ({"focus": "sec", "agent": "human"},)
    _use(monkeypatch, _swapped(second, ENGINE, live_human))
    _finish(state, reviewed=("sec",))  # a review approval but no engine verdict
    shutil.rmtree(second)
    assert main(["status", TASK]) == 0 and main(["stamp", TASK]) == 0
    capsys.readouterr()
    assert main(["close", TASK]) == 1
    assert "judge 'sec': no verdict yet" in capsys.readouterr().err


def test_legacy_rule_with_a_live_namesake_keeps_every_accepted_control(
    state: TaskStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    _, second = _two_repos(tmp_path)
    old = RiskRule(
        "sec", ("zz/*",), judges=("old-required",), checks=("old-check",), restaging=True
    )
    bare = RiskRule("sec", ("zz/*",))
    _use(monkeypatch, lambda t: _flat(rules=(old,)) if second.exists() else _flat(rules=(bare,)))
    _finish(state)
    state.mutate(TASK, lambda t: t.code_stamp.pop("obligations", None))
    shutil.rmtree(second)
    task = state.get(TASK)
    _, risk = cli._refresh(state, task, cli._config(task))
    assert "old-required" in risk.judges and "old-check" in risk.checks and risk.restaging
    capsys.readouterr()
    assert main(["close", TASK]) == 1
    assert "judge 'old-required'" in capsys.readouterr().err


def _rule_in_second(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    first = _new_repo(tmp_path, "a")
    second = _new_repo(tmp_path, "b", {"zz/x.txt": "x"})
    _bind(first)
    assert main(["bind", TASK, "--repo", str(second), "--integration-branch", "main"]) == 0
    _use(monkeypatch, _holder(second, (), (_sec_rule(),)))
    return first, second


def test_frozen_restaging_still_forbids_skipping_staging_after_deletion(
    state: TaskStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, second = _rule_in_second(tmp_path, monkeypatch)
    _finish(state, passed=("security",))
    state.mutate(TASK, lambda t: setattr(t, "phase", "judge"))
    shutil.rmtree(second)
    task = state.get(TASK)
    config = cli._config(task)
    task, risk = cli._refresh(state, task, config)
    missing = gates.check_transition(
        task, "review", gates.GateContext(config, risk, task.stamp_key)
    )
    assert any("one phase at a time" in item for item in missing)
    assert "extra" in risk.checks


def test_changed_live_code_merges_frozen_obligations_and_needs_fresh_evidence(
    state: TaskStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    first, second = _rule_in_second(tmp_path, monkeypatch)
    key = _finish(state, passed=("security",))
    shutil.rmtree(second)
    (first / "new.py").write_text("y = 2\n")
    _git(first, "add", ".")
    _git(first, "commit", "-qm", "more")
    task = state.get(TASK)
    task, risk = cli._refresh(state, task, cli._config(task))
    assert task.stamp_key != key and "security" in risk.judges and "extra" in risk.checks
    capsys.readouterr()
    assert main(["close", TASK]) == 1
    err = capsys.readouterr().err
    assert "stale" in err or "not run on the current code" in err


def _vanish_after(monkeypatch: pytest.MonkeyPatch, target: str) -> None:
    real = getattr(cli, target)

    def wrapper(arg: object) -> object:
        found = real(arg)
        for binding in arg:  # type: ignore[attr-defined]
            shutil.rmtree(binding["path"])
        return found

    monkeypatch.setattr(cli, target, wrapper)


@pytest.mark.usefixtures("state")
@pytest.mark.parametrize("name", ["tdd"])
def test_repo_vanishing_after_selection_is_reported_not_a_traceback(
    name: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    path = _new_repo(tmp_path, "a")
    _bind(path)
    _use(monkeypatch, lambda task: _flat(judges=HUMAN))
    _vanish_after(monkeypatch, "first_live")
    capsys.readouterr()
    assert main(REFUSED[name]) == 1
    err = capsys.readouterr().err
    assert GONE in err and "Errno 2" not in err
    assert err.splitlines().count(WARNING.format(path)) == 1


def test_repo_vanishing_while_the_judge_copies_it_is_reported(
    state: TaskStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    path = _new_repo(tmp_path, "a")
    _bind(path)
    _use(monkeypatch, lambda task: _flat(judges=HUMAN))
    _finish(state, reviewed=("design",))

    def vanishing(binding: dict, scratch: Path) -> None:
        shutil.rmtree(binding["path"])
        raise stamp.GitError("git status: [Errno 2] No such file") from FileNotFoundError(
            2, "No such file or directory", str(binding["path"])
        )

    monkeypatch.setattr(judge, "make_copy", vanishing)
    capsys.readouterr()
    assert main(["judge", TASK]) == 1
    err = capsys.readouterr().err
    assert GONE in err and "Errno 2" not in err
    assert err.splitlines().count(WARNING.format(path)) == 1


# -- second review: legacy typing, failure attribution, judge cleanup, round reservation ------------
def _legacy(state: TaskStore) -> None:
    state.mutate(TASK, lambda t: t.code_stamp.pop("obligations", None))


class _LegacyCase(NamedTuple):
    reviewed: bool
    passed: bool
    closes: bool
    live: tuple[dict, ...] = ()


@pytest.mark.parametrize(
    "case",
    [
        _LegacyCase(True, False, False, ({"focus": "sec", "agent": "human"},)),  # engine -> human
        _LegacyCase(True, True, True, ({"focus": "sec", "agent": "human"},)),
        _LegacyCase(False, False, False),
        _LegacyCase(False, True, True),
    ],
)
def test_legacy_engine_focus_is_never_taken_as_the_live_type(
    case: _LegacyCase, state: TaskStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, second = _two_repos(tmp_path)
    _use(monkeypatch, _swapped(second, ENGINE, case.live))
    _finish(
        state,
        passed=("sec",) if case.passed else (),
        reviewed=("sec",) if case.reviewed else (),
    )
    _legacy(state)
    shutil.rmtree(second)
    assert (main(["close", TASK]) == 0) is case.closes


@pytest.mark.parametrize("case", [_LegacyCase(True, False, False), _LegacyCase(True, True, True)])
def test_legacy_human_only_focus_needs_the_engine_verdict_until_recovered(
    case: _LegacyCase, state: TaskStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, second = _two_repos(tmp_path)
    _use(monkeypatch, _holder(second, HUMAN))
    _finish(state, passed=("design",) if case.passed else (), reviewed=("design",))
    _legacy(state)
    shutil.rmtree(second)
    assert (main(["close", TASK]) == 0) is case.closes


def test_legacy_state_tells_the_operator_how_to_recover(
    state: TaskStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    _, second = _two_repos(tmp_path)
    _use(monkeypatch, _holder(second, HUMAN))
    _finish(state, reviewed=("design",))
    _legacy(state)
    shutil.rmtree(second)
    capsys.readouterr()
    assert main(["status", TASK]) == 0
    out = capsys.readouterr().out
    assert "legacy" in out and f"unbind {TASK} --repo {second}" in out and f"stamp {TASK}" in out
    assert main(["close", TASK]) == 1
    assert f"unbind {TASK} --repo {second}" in capsys.readouterr().err
    assert main(["unbind", TASK, "--repo", str(second)]) == 0
    capsys.readouterr()
    assert main(["status", TASK]) == 0
    assert "legacy" not in capsys.readouterr().out


def test_on_live_only_translates_failures_caused_by_the_vanished_path(tmp_path: Path) -> None:
    gone, alive = tmp_path / "gone", tmp_path / "alive"
    alive.mkdir()

    def denied() -> None:
        raise PermissionError(13, "denied", str(tmp_path / "store"))

    with pytest.raises(PermissionError):
        repos.on_live([gone], denied)

    def broken() -> None:
        raise RuntimeError("lease store failure")

    with pytest.raises(RuntimeError, match="lease store"):
        repos.on_live([gone, alive], broken)

    def interrupted() -> None:
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        repos.on_live([gone], interrupted)

    def missing_cwd() -> None:
        raise stamp.GitError("git x") from FileNotFoundError(2, "no", str(gone))

    with pytest.raises(ValueError, match=GONE):
        repos.on_live([gone], missing_cwd)
    with pytest.raises(ValueError, match="vanished during the command") as survivor:
        repos.on_live([gone, alive], missing_cwd)
    assert GONE not in str(survivor.value)


def _scratch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(scratch))
    return scratch


def test_failure_on_the_second_copy_leaves_no_registration_or_temp_dir(
    state: TaskStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    first, second = _two_repos(tmp_path)
    _use(monkeypatch, lambda task: _flat(judges=HUMAN))
    _finish(state, reviewed=("design",))
    scratch = _scratch(tmp_path, monkeypatch)
    real = judge.make_copy

    def second_fails(binding: dict, target: Path) -> object:
        if binding["path"] == str(second):
            raise judge.JudgeError("boom on the second repository")
        return real(binding, target)

    monkeypatch.setattr(judge, "make_copy", second_fails)
    assert main(["judge", TASK]) == 1
    assert "boom" in capsys.readouterr().err
    assert list(scratch.iterdir()) == []
    assert _git(first, "worktree", "list", "--porcelain").count("worktree ") == 1


def test_partial_copy_of_a_vanished_linked_source_leaves_no_registration(
    state: TaskStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    main_repo = _new_repo(tmp_path, "main-repo")
    linked = tmp_path / "linked"
    _git(main_repo, "worktree", "add", "-q", "-b", "side", str(linked))
    _bind(linked.resolve())
    _use(monkeypatch, lambda task: _flat(judges=HUMAN))
    _finish(state, reviewed=("design",))
    scratch = _scratch(tmp_path, monkeypatch)

    def vanishing(path: Path) -> str:
        shutil.rmtree(linked)
        raise stamp.GitError("git status: [Errno 2]") from FileNotFoundError(2, "no", str(linked))

    monkeypatch.setattr(judge, "tree_fingerprint", vanishing)
    assert main(["judge", TASK]) == 1
    assert GONE in capsys.readouterr().err
    assert list(scratch.iterdir()) == []
    listing = _git(main_repo, "worktree", "list", "--porcelain")
    assert "taskflow-judge" not in listing


# -- third review: hook failure during worktree add, prune errors, frozen check execution ------------
def test_failing_post_checkout_hook_leaves_no_judge_registration(
    state: TaskStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    path = _new_repo(tmp_path, "a")
    _bind(path)
    _use(monkeypatch, lambda task: _flat(judges=HUMAN))
    _finish(state, reviewed=("design",))
    hook = path / ".git" / "hooks" / "post-checkout"
    hook.write_text("#!/bin/sh\nexit 1\n")
    hook.chmod(0o755)
    scratch = _scratch(tmp_path, monkeypatch)
    assert main(["judge", TASK]) == 1
    assert list(scratch.iterdir()) == []
    assert "taskflow-judge" not in _git(path, "worktree", "list", "--porcelain")


def test_prune_failure_with_a_surviving_git_dir_is_reported_not_hidden(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    common = tmp_path / "common"
    common.mkdir()

    def locked(directory: Path, *args: str) -> str:
        raise stamp.GitError("git worktree prune: lock held")

    monkeypatch.setattr(judge, "git", locked)
    judge._forget_worktree(common, tmp_path / "target")
    assert "could not prune" in capsys.readouterr().err
    judge._forget_worktree(tmp_path / "vanished", tmp_path / "target")
    assert capsys.readouterr().err == ""


def test_frozen_extra_check_still_runs_and_gates_the_close_after_the_repo_vanishes(
    state: TaskStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    first = _new_repo(tmp_path, "a")
    second = _new_repo(tmp_path, "b", {"zz/x.txt": "x"})
    _bind(first)
    assert main(["bind", TASK, "--repo", str(second), "--integration-branch", "main"]) == 0
    rule = RiskRule("sec", ("zz/*",), checks=("echo frozen-check-ran >&2; exit 1",))
    _use(
        monkeypatch,
        lambda t: _flat(judges=HUMAN, rules=(rule,) if second.exists() else ()),
    )
    _finish(state, reviewed=("design",))
    shutil.rmtree(second)
    capsys.readouterr()
    assert main(["judge", TASK]) == 1  # the frozen command ran in the surviving repo and failed
    assert main(["close", TASK]) == 1
    assert "checks failed" in capsys.readouterr().err
    latest = [e for e in state.get(TASK).evidence if e.get("kind") == "checks"][-1]
    assert latest["passed"] is False
