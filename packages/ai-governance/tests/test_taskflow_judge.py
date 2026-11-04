"""Judge rounds are readers: the engine runs the checks, an Orca worker reviews the real checkout.

Hermetic (see ``orca_fakes``). The checks themselves are replaced by a recording fake so the
tests can change the code while "the checks run" without any shell.
"""

# ruff: noqa: F401, F811
from __future__ import annotations

import contextlib
import shutil
import subprocess
import types
from collections.abc import Callable
from pathlib import Path

import pytest
from ai_governance.taskflow import cli, gates, judge
from ai_governance.taskflow.cli import main
from ai_governance.taskflow.config import FlowConfig
from ai_governance.taskflow.control import CheckedBaseline, DispatchError
from ai_governance.taskflow.dispatch import DispatchRequest, plan_dispatch
from ai_governance.taskflow.judge_flow import JudgeJob, judge_flow
from ai_governance.taskflow.stamp import head_sha, tree_fingerprint
from orca_fakes import TASK, OrcaWorld, _make_repo, flag, world

HUMAN = ({"focus": "design", "agent": "human"},)
Hook = Callable[[Path], None]


def _git(repo: Path, *args: str) -> str:
    done = subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)
    return done.stdout


class Checks(list):
    """Every (command, cwd) the engine ran; ``exit`` is the code returned, ``hook`` runs inside."""

    exit: int = 0
    hook: Hook | None = None


@pytest.fixture
def checks(monkeypatch: pytest.MonkeyPatch) -> Checks:
    """Replace the shell with a recorder so a test can change the code while "checks run"."""
    calls = Checks()

    def fake(command: str, cwd: Path) -> dict[str, object]:
        calls.append((command, cwd))
        if calls.hook is not None:
            calls.hook(cwd)
        return {"cmd": command, "exit": calls.exit, "tail": "output"}

    monkeypatch.setattr(judge, "_run_check", fake)
    return calls


def _during_checks(checks: Checks, hook: Hook) -> None:
    checks.hook = hook


@pytest.fixture
def ready(world: OrcaWorld) -> OrcaWorld:
    world.ready_for_judge()
    return world


def _gates(world: OrcaWorld) -> tuple[list[str], list[str]]:
    """(checks_unmet, judges_unmet) on the current code."""
    task = world.task()
    config = cli._config(task)
    task, risk = cli._refresh(world.store, task, config)
    return (
        gates.checks_unmet(task, task.stamp_key),
        gates.judges_unmet(task, risk, config, task.stamp_key),
    )


def _check_evidence(world: OrcaWorld) -> list[dict]:
    return [e for e in world.task().evidence if e.get("kind") == "checks"]


def _nothing_published(world: OrcaWorld) -> None:
    assert _check_evidence(world) == []
    assert not list(world.store.evidence_dir(TASK).glob("checks-*"))  # no orphan report either
    assert world.task().rounds == []
    assert not (world.store.task_dir(TASK) / "runs").exists()
    assert world.orca_calls() == []


def test_check_reports_have_unique_paths_and_are_written_only_on_publish(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(judge, "_run_check", lambda c, cwd: {"cmd": c, "exit": 0, "tail": "t"})
    copy = types.SimpleNamespace(path=tmp_path, source=tmp_path / "repo", head="abcdef123456")
    first = judge.run_checks(copy, ("x",), tmp_path)  # type: ignore[arg-type]
    retry = judge.run_checks(copy, ("x",), tmp_path)  # type: ignore[arg-type]
    assert first["path"] != retry["path"] and not list(tmp_path.glob("checks-*"))
    judge.CheckRun((), (first,), ()).publish()
    kept = Path(str(first["path"])).read_text(encoding="utf-8")
    judge.CheckRun((), (retry,), ()).publish()  # the retry cannot touch the earlier report
    assert Path(str(first["path"])).read_text(encoding="utf-8") == kept
    assert "exit 0" in kept and len(list(tmp_path.glob("checks-*"))) == 2


# -- the happy path ------------------------------------------------------------------------------
def test_judge_runs_checks_in_a_throwaway_copy_then_prints_one_line_per_focus(
    ready: OrcaWorld, checks: Checks
) -> None:
    repo = ready.repo
    result = ready.judge()
    assert result.code == 0, result.text
    (line,) = ready.worker_lines(result)
    assert line[1:3] == ["orchestration", "worker-start"] and flag(line, "--agent") == "codex"
    assert flag(line, "--worktree") == f"path:{repo}"
    assert flag(line, "--task-title") == f"judge round 1 of {TASK}"
    (command, cwd) = checks[0]
    assert command == "ws check --changed" and cwd != repo and cwd.name.startswith("repo-")
    (entry,) = _check_evidence(ready)
    assert entry["sha"] == head_sha(repo) and entry["passed"] is True
    assert entry["stamp"] == ready.task().stamp_key
    assert _git(repo, "worktree", "list").count("\n") == 1  # the copy is gone
    assert ready.orca_calls() == []  # judging never touches Orca: the coordinator runs the line


def test_dispatch_json_records_head_and_fingerprint_for_every_repo(
    ready: OrcaWorld, checks: Checks, tmp_path: Path
) -> None:
    other = tmp_path / "other"
    _make_repo(other)
    assert ready.run("bind", TASK, "--repo", str(other)).code == 0
    result = ready.judge()
    assert result.code == 0, result.text
    found = ready.dispatch_json(1)
    assert found["role"] == "judge" and found["focus"] == "correctness"
    assert found["repos"] == [
        {"path": str(path), "head": head_sha(path), "fingerprint": tree_fingerprint(path)}
        for path in (ready.repo, other)
    ]
    assert len(_check_evidence(ready)) == 2


def test_judge_spec_makes_the_worker_a_reader_of_the_real_checkout(
    ready: OrcaWorld, checks: Checks
) -> None:
    repo = ready.repo
    before = tree_fingerprint(repo)
    assert ready.judge().code == 0
    spec = (ready.run_dir(1) / "spec.md").read_text()
    assert f"Repository repo at {repo} (commit {head_sha(repo)}, clean tree)" in spec
    assert "copy" not in spec.lower() and "isolated" not in spec.lower()
    assert "Run any test" not in spec and "do not modify any file" in spec.lower()
    assert "Engine-run checks passed" in spec
    assert tree_fingerprint(repo) == before  # the engine itself left the checkout alone


# -- collect settles the verdict -----------------------------------------------------------------
def test_collect_settles_a_passing_judge_and_the_gates_accept_it(
    ready: OrcaWorld, checks: Checks
) -> None:
    (line,) = ready.worker_lines(ready.judge())
    result = ready.settle_judge(line, "pass")
    assert result.code == 0, result.text
    record = ready.record(1)
    assert (record["source"], record["role"], record["verdict"], record["state"]) == (
        "engine",
        "judge",
        "pass",
        "valid",
    )
    assert record["focus"] == "correctness" and record["stamp"] == ready.task().stamp_key
    assert _gates(ready) == ([], [])


@pytest.mark.parametrize("verdict", ["concerns", "block"])
def test_collect_settles_a_judge_that_found_problems(
    ready: OrcaWorld, checks: Checks, verdict: str
) -> None:
    (line,) = ready.worker_lines(ready.judge())
    assert ready.settle_judge(line, verdict).code == 0
    assert ready.record(1)["verdict"] == verdict
    unmet = _gates(ready)[1]
    assert unmet == [f"judge 'correctness': {verdict} in round 001"]


def test_commit_line_in_the_answer_never_decides_anything(ready: OrcaWorld, checks: Checks) -> None:
    (line,) = ready.worker_lines(ready.judge())
    ready.finish(1, "J1", answer="COMMIT: " + "0" * 40 + "\nVERDICT: pass\n", agent="codex")
    assert ready.collect(1, "J1").code == 0
    assert ready.record(1)["verdict"] == "pass" and _gates(ready) == ([], [])
    assert ready.dispatch_json(1)["repos"][0]["head"] == head_sha(ready.repo)


def test_a_judge_from_the_builders_provider_is_refused_at_collect(
    ready: OrcaWorld, checks: Checks
) -> None:
    (line,) = ready.worker_lines(ready.judge())
    result = ready.settle_judge(line, "pass", agent="claude")
    assert result.code == 1 and "dispatched provider 'codex'" in result.text
    assert ready.task().rounds == []


def test_judge_that_edits_the_repo_is_invalid_and_kept(ready: OrcaWorld, checks: Checks) -> None:
    (line,) = ready.worker_lines(ready.judge())
    (ready.repo / "app.py").write_text("x = 99\n")
    assert ready.settle_judge(line, "pass").code == 1
    record = ready.record(1)
    assert record["state"] == "invalid" and "reader changed the tree" in str(record["reason"])
    assert (ready.repo / "app.py").read_text() == "x = 99\n"  # kept, never reverted
    assert _gates(ready)[1]  # stale or invalid: either way the gate stays closed


def test_judge_that_edits_a_secondary_repo_is_invalid(
    ready: OrcaWorld, checks: Checks, tmp_path: Path
) -> None:
    other = tmp_path / "other"
    _make_repo(other)
    assert ready.run("bind", TASK, "--repo", str(other)).code == 0
    (line,) = ready.worker_lines(ready.judge())
    (other / "new.txt").write_text("x\n")
    assert ready.settle_judge(line, "pass").code == 1
    assert str(other) in str(ready.record(1)["reason"])


def test_judge_that_commits_moves_head_and_is_invalid(ready: OrcaWorld, checks: Checks) -> None:
    (line,) = ready.worker_lines(ready.judge())
    _git(ready.repo, "commit", "-q", "--allow-empty", "-m", "by the reader")
    assert ready.settle_judge(line, "pass").code == 1
    assert "HEAD moved" in str(ready.record(1)["reason"])


def test_a_change_after_judging_makes_the_round_stale(ready: OrcaWorld, checks: Checks) -> None:
    (line,) = ready.worker_lines(ready.judge())
    assert ready.settle_judge(line, "pass").code == 0
    _git(ready.repo, "commit", "-q", "--allow-empty", "-m", "later")
    unmet = _gates(ready)
    assert any("not run on the current code" in item for item in unmet[0])
    assert unmet[1] == ["judge 'correctness': stale (code changed after round 001)"]


def test_failing_check_blocks_even_if_the_judge_passes(ready: OrcaWorld, checks: Checks) -> None:
    checks.exit = 1
    result = ready.judge()
    assert result.code == 1 and "checks failed" in result.out
    (line,) = ready.worker_lines(result)  # the reader still reviews it
    assert "Engine-run checks FAILED" in (ready.run_dir(1) / "spec.md").read_text()
    assert ready.settle_judge(line, "pass").code == 0
    unmet_checks, unmet_judges = _gates(ready)
    assert unmet_judges == [] and unmet_checks and "checks failed" in unmet_checks[0]


# -- refusals before anything is published -------------------------------------------------------
def test_a_judge_from_the_builders_provider_is_refused_before_the_checks(
    ready: OrcaWorld, checks: Checks
) -> None:
    ready.store.mutate(
        TASK, lambda t: t.rounds.append({"n": 1, "role": "builder", "agent": "codex"})
    )
    result = ready.judge()
    assert result.code == 1 and "not independent of the builder" in result.err
    assert checks == [] and _check_evidence(ready) == []
    assert not (ready.store.task_dir(TASK) / "runs").exists()


def test_dirty_tree_refused_before_any_dispatch(ready: OrcaWorld, checks: Checks) -> None:
    (ready.repo / "dirty.txt").write_text("uncommitted\n")
    result = ready.judge()
    assert result.code == 1 and "uncommitted changes" in result.err
    assert checks == []
    _nothing_published(ready)
    assert _git(ready.repo, "worktree", "list").count("\n") == 1


def test_unknown_focus_is_refused(ready: OrcaWorld, checks: Checks) -> None:
    result = ready.judge("--focus", "nope")
    assert result.code == 1 and "No judge configured for focus 'nope'" in result.err
    assert checks == []


def test_a_missing_orca_stops_before_the_checks(
    ready: OrcaWorld, checks: Checks, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ORCA_CLI_COMMAND", "orca-nowhere")
    result = ready.judge()
    assert result.code == 1 and "orca-nowhere" in result.err
    assert checks == []


def test_judge_dispatch_with_a_missing_repo_message(
    ready: OrcaWorld, checks: Checks, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    other = tmp_path / "other"
    _make_repo(other)
    assert ready.run("bind", TASK, "--repo", str(other)).code == 0
    shutil.rmtree(other)
    monkeypatch.setattr(cli, "_config", lambda task: FlowConfig())
    result = ready.judge()
    assert result.code == 1 and f"bound repo not found: {other}" in result.err
    assert checks == []
    _nothing_published(ready)


def test_human_judge_needs_no_worker(
    ready: OrcaWorld, checks: Checks, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        cli, "_config", lambda task: FlowConfig(judges=HUMAN, checks=("x",), risk_rules=())
    )
    monkeypatch.setenv("ORCA_CLI_COMMAND", "orca-nowhere")  # not needed: nobody is dispatched
    result = ready.judge()
    assert result.code == 1 and "judge 'design' (human)" in result.out
    assert ready.worker_lines(result) == [] and ready.orca_calls() == []
    (entry,) = _check_evidence(ready)  # the checks still ran by code
    assert entry["passed"] is True and checks and not (ready.store.task_dir(TASK) / "runs").exists()


# -- one baseline for the checks and the reader (drift) ------------------------------------------
def test_a_commit_while_the_checks_run_publishes_nothing(ready: OrcaWorld, checks: Checks) -> None:
    _during_checks(
        checks,
        lambda cwd: _git(ready.repo, "commit", "-q", "--allow-empty", "-m", "B during checks"),
    )
    result = ready.judge()
    assert result.code == 1 and "changed while the checks ran" in result.err
    _nothing_published(ready)
    assert _git(ready.repo, "worktree", "list").count("\n") == 1


def test_a_tracked_edit_while_the_checks_run_publishes_nothing(
    ready: OrcaWorld, checks: Checks
) -> None:
    _during_checks(checks, lambda cwd: (ready.repo / "app.py").write_text("x = 2\n"))
    result = ready.judge()
    assert result.code == 1 and "changed while the checks ran" in result.err
    _nothing_published(ready)


def test_a_change_between_the_per_repo_checks_publishes_nothing(
    ready: OrcaWorld, checks: Checks, tmp_path: Path
) -> None:
    other = tmp_path / "other"
    _make_repo(other)
    assert ready.run("bind", TASK, "--repo", str(other)).code == 0

    def after_first(cwd: Path) -> None:
        if cwd.name.startswith("other-"):  # the first repo was already checked
            (ready.repo / "late.txt").write_text("late\n")

    _during_checks(checks, after_first)
    result = ready.judge()
    assert result.code == 1 and str(ready.repo) in result.err
    _nothing_published(ready)


def test_a_stamp_that_moves_while_the_checks_run_publishes_nothing(
    ready: OrcaWorld, checks: Checks, tmp_path: Path
) -> None:
    other = tmp_path / "other"
    _make_repo(other)
    _during_checks(checks, lambda cwd: main(["bind", TASK, "--repo", str(other)]))
    result = ready.judge()
    assert result.code == 1 and "the code changed while the checks ran" in result.err
    _nothing_published(ready)


def test_dispatch_refuses_a_baseline_that_moved_after_the_checks(
    ready: OrcaWorld, checks: Checks
) -> None:
    task = ready.task()
    config = cli._config(task)
    task, risk = cli._refresh(ready.store, task, config)
    stale = {"path": str(ready.repo), "head": head_sha(ready.repo), "fingerprint": "0" * 64}
    request = DispatchRequest(
        "judge",
        task.phase,
        "correctness",
        "p",
        {"agent": "codex", "model": "m"},
        CheckedBaseline(task.stamp_key, (stale,)),
    )
    with pytest.raises(DispatchError, match="code changed after the checks"):
        plan_dispatch(ready.store, task, config, request)
    other_stamp = DispatchRequest(
        "judge", task.phase, "correctness", "p", {"agent": "codex"}, CheckedBaseline("other", ())
    )
    with pytest.raises(DispatchError, match="code stamp changed"):
        plan_dispatch(ready.store, task, config, other_stamp)
    assert not (ready.store.task_dir(TASK) / "runs").exists() and ready.task().rounds == []


def test_a_judge_cannot_be_dispatched_by_hand(ready: OrcaWorld, checks: Checks) -> None:
    result = ready.run("round", TASK, "dispatch", "--role", "judge", "--prompt", "x")
    assert result.code == 2 and f"`taskflow judge {TASK}`" in result.text


def test_an_exception_mid_checks_leaves_no_worktree_or_scratch(
    ready: OrcaWorld, checks: Checks, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import tempfile

    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(scratch))

    def boom(copies: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(judge, "verify_unchanged", boom)
    with contextlib.suppress(RuntimeError):  # main may let a bug through; the cleanup matters
        ready.run("judge", TASK)
    assert list(scratch.iterdir()) == []
    assert _git(ready.repo, "worktree", "list").count("\n") == 1


# -- fix 2: dispatch and gates agree on frozen human vs engine ---------------------------------
def test_judge_flow_agrees_with_gates_when_frozen_engine_overrides_live_human(
    ready: OrcaWorld, checks: Checks
) -> None:
    task = ready.task()
    config = FlowConfig(
        judges=({"focus": "correctness", "agent": "human"},),
        checks=(),
        risk_rules=(),
    )
    # Frozen risk says correctness is engine-decided (e.g. missing repo / legacy obligations)
    risk = gates.RiskAssessment(
        rules=(),
        judges=("correctness",),
        checks=(),
        restaging=False,
        human=(),
        engine=("correctness",),
    )
    assert not gates.decided_by_human(risk, config, "correctness")
    unmet = gates.judges_unmet(task, risk, config, task.stamp_key)
    assert unmet == ["judge 'correctness': no verdict yet"]

    # judge_flow must agree: does not skip as human, attempts worker dispatch
    job = JudgeJob(
        ready.store, task, gates.GateContext(config, risk, task.stamp_key), judge.JudgeScope()
    )
    with pytest.raises(DispatchError, match="a human cannot run as a worker"):
        list(judge_flow(job, lambda: task.stamp_key))


def test_judge_flow_agrees_with_gates_when_frozen_human_overrides_live_engine(
    ready: OrcaWorld, checks: Checks
) -> None:
    task = ready.task()
    config = FlowConfig(
        judges=({"focus": "correctness", "agent": "codex"},),
        checks=(),
        risk_rules=(),
    )
    # Frozen risk says correctness is human-decided
    risk = gates.RiskAssessment(
        rules=(),
        judges=("correctness",),
        checks=(),
        restaging=False,
        human=("correctness",),
        engine=(),
    )
    assert gates.decided_by_human(risk, config, "correctness")
    unmet = gates.judges_unmet(task, risk, config, task.stamp_key)
    assert unmet == ["judge 'correctness' (human): approve --action review --target correctness"]

    # judge_flow must agree: treats as human, skips worker dispatch entirely
    job = JudgeJob(
        ready.store, task, gates.GateContext(config, risk, task.stamp_key), judge.JudgeScope()
    )
    dispatches = list(judge_flow(job, lambda: task.stamp_key))
    assert dispatches == []


# -- fix 3: latest valid judge round per focus at current stamp for independence ---------------
def test_judge_independence_only_considers_latest_valid_round_at_current_stamp(
    ready: OrcaWorld,
) -> None:
    task = ready.task()
    current_stamp = task.stamp_key
    config = cli._config(task)
    ready.store.mutate(
        TASK,
        lambda t: t.rounds.extend(
            [
                {
                    "n": 1,
                    "role": "judge",
                    "focus": "correctness",
                    "agent": "claude",
                    "state": "valid",
                    "source": "engine",
                    "stamp": "stamp_old",
                },
                {
                    "n": 2,
                    "role": "judge",
                    "focus": "correctness",
                    "agent": "claude",
                    "state": "valid",
                    "source": "engine",
                    "stamp": current_stamp,
                },
                {
                    "n": 3,
                    "role": "judge",
                    "focus": "correctness",
                    "agent": "codex",
                    "state": "valid",
                    "source": "engine",
                    "stamp": current_stamp,
                },
            ]
        ),
    )
    task = ready.task()
    assert gates._independence_unmet(task, config) == []

    ready.store.mutate(
        TASK,
        lambda t: t.rounds.append(
            {
                "n": 4,
                "role": "judge",
                "focus": "correctness",
                "agent": "claude",
                "state": "valid",
                "source": "engine",
                "stamp": current_stamp,
            }
        ),
    )
    task = ready.task()
    unmet = gates._independence_unmet(task, config)
    assert len(unmet) == 1 and "judge and builder both used provider 'claude'" in unmet[0]


# -- fix 8: preflight checks disallowed agent and pending duplicate before checks/evidence -----
def test_disallowed_judge_agent_refused_before_checks_and_evidence(
    ready: OrcaWorld, checks: Checks
) -> None:
    task = ready.task()
    config = FlowConfig(
        judges=({"focus": "correctness", "agent": "disallowed_agent"},),
        checks=("echo check",),
    )
    risk = gates.RiskAssessment(rules=(), judges=("correctness",), checks=(), restaging=False)
    job = JudgeJob(
        ready.store,
        task,
        gates.GateContext(config, risk, task.stamp_key),
        judge.JudgeScope(),
    )
    with pytest.raises(DispatchError, match="judge: 'disallowed_agent' is not allowed here"):
        list(judge_flow(job, lambda: task.stamp_key))
    assert checks == []
    assert _check_evidence(ready) == []


def test_pending_duplicate_judge_refused_before_checks_and_evidence(
    ready: OrcaWorld, checks: Checks
) -> None:
    result1 = ready.judge()
    assert result1.code == 0
    checks_count = len(checks)
    evidence_count = len(_check_evidence(ready))
    assert checks_count > 0 and evidence_count > 0

    result2 = ready.judge()
    assert result2.code == 1
    assert "already dispatched and not settled" in result2.err
    assert len(checks) == checks_count
    assert len(_check_evidence(ready)) == evidence_count
