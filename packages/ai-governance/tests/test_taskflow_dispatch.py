"""Dispatch, collect and abort of Orca-run reader rounds.

Hermetic: a fake Orca CLI and a wrapped git (see ``orca_fakes``); no network, no real agent.
"""

# ruff: noqa: F401, F811
from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import threading
from collections.abc import Callable
from pathlib import Path

import pytest
from ai_governance.taskflow import orca
from ai_governance.taskflow import store as store_module
from ai_governance.taskflow.collect import (
    Launch,
    RoundRef,
    abort_round,
    collect_round,
    launch_verified,
    parse_launch,
)
from ai_governance.taskflow.control import DispatchError
from ai_governance.taskflow.guide import GUIDE
from ai_governance.taskflow.models import Task
from ai_governance.taskflow.orca import OrcaError, _run, orca_command
from ai_governance.taskflow.parser import build_parser
from ai_governance.taskflow.prompts import READ_ONLY_LIMIT, VERDICT_INSTRUCTION
from ai_governance.taskflow.store import TaskStore
from orca_fakes import TASK, OrcaWorld, _make_repo, decode_cursor, flag, make_world, world
from orca_real_samples import REAL_LIST, REAL_SHOW_LIVE, REAL_SHOW_RELEASED

WAIT = "orca-fake orchestration check --wait --types worker_done --timeout-ms 600000"
PLANNER = ["round", TASK, "dispatch", "--role", "planner", "--agent", "claude", "--prompt", "p"]


# -- dispatch ----------------------------------------------------------------------------------
def test_dispatch_prints_one_worker_start_line_and_runs_nothing(world: OrcaWorld) -> None:
    made = world.dispatch("planner", "claude")
    assert made.argv[0] == orca_command()
    assert made.argv[1:3] == ["orchestration", "worker-start"]
    assert flag(made.argv, "--agent") == "claude"
    assert flag(made.argv, "--worktree") == "path:" + world.task().repos[0]["path"]
    assert flag(made.argv, "--spec-file") == str(world.run_dir(1) / "spec.md")
    assert len(made.result.out.strip().splitlines()) == 1
    assert not world.orca_log.exists()
    assert world.task().rounds == []
    assert (world.run_dir(1) / "dispatch.json").exists()


def test_spec_has_the_full_prompt(world: OrcaWorld) -> None:
    world.dispatch("planner", "claude")
    world.dispatch("validator", "codex")
    plan = (world.run_dir(1) / "spec.md").read_text(encoding="utf-8")
    review = (world.run_dir(2) / "spec.md").read_text(encoding="utf-8")
    assert plan.startswith(READ_ONLY_LIMIT) and VERDICT_INSTRUCTION not in plan
    assert review.startswith(READ_ONLY_LIMIT) and VERDICT_INSTRUCTION in review
    for text, number in ((plan, 1), (review, 2)):
        assert str(world.run_dir(number) / "answer.txt") in text
        assert str(world.run_dir(number) / "receipt.txt") in text
        assert "Do not modify any file" in text
        assert world.dispatch_json(number)["nonce"] in text
        assert "do it" in text
    assert "Role: validator. Task ONB-1" in review


def test_json_argv_and_hostile_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    world = make_world(tmp_path, monkeypatch, capsys, repo_name="my repo $(x)\nnl")
    model = 'x"; rm -rf /'
    shown = world.run(*PLANNER, "--model", model, "--json")
    argv = json.loads(shown.out)
    assert flag(argv, "--model") == model
    assert flag(argv, "--worktree") == "path:" + world.task().repos[0]["path"]
    assert "$(x)\n" in flag(argv, "--worktree")
    plain = shlex.split(world.run(*PLANNER, "--model", model, "--focus", "two").out.strip())
    assert flag(plain, "--model") == model
    assert flag(plain, "--worktree") == flag(argv, "--worktree")
    assert flag(plain, "--task-title") == "planner round 2 of ONB-1"
    world.assert_hermetic()


def test_duplicate_dispatch_refused_without_burning_a_number(world: OrcaWorld) -> None:
    world.dispatch()
    again = world.run(*PLANNER)
    assert again.code == 1 and "already dispatched" in again.text
    files = sorted(p.name for p in world.store.rounds_dir(TASK).glob("[0-9]*.md"))
    assert len(files) == 1
    assert sorted(p.name for p in (world.store.task_dir(TASK) / "runs").iterdir()) == ["001"]
    assert world.dispatch("planner", "claude", focus="other").n == 2


def test_builder_dispatch_refused_with_work_unmet_reasons(world: OrcaWorld) -> None:
    res = world.run("round", TASK, "dispatch", "--role", "builder")
    assert res.code == 2
    assert "The builder is not dispatched" in res.text
    assert "builders write only in phase 'work'" in res.text
    assert f"round {TASK} record --role builder" in res.text
    assert not (world.store.task_dir(TASK) / "runs").exists()


def test_judge_dispatch_refused_points_to_taskflow_judge(world: OrcaWorld) -> None:
    res = world.run("round", TASK, "dispatch", "--role", "judge", "--prompt", "x")
    assert res.code == 2 and f"`taskflow judge {TASK}`" in res.text
    assert world.task().rounds == []


def test_agent_rules_apply_at_dispatch(world: OrcaWorld) -> None:
    same = world.run(
        "round", TASK, "dispatch", "--role", "validator", "--agent", "claude", "--prompt", "p"
    )
    assert same.code == 1 and "would both use provider 'claude'" in same.text
    human = world.run(
        "round", TASK, "dispatch", "--role", "validator", "--agent", "human", "--prompt", "p"
    )
    assert human.code == 1 and "a human cannot run as a worker" in human.text
    unknown = world.run(
        "round", TASK, "dispatch", "--role", "planner", "--agent", "nope", "--prompt", "p"
    )
    assert unknown.code == 1 and "not allowed here" in unknown.text
    default = world.run("round", TASK, "dispatch", "--role", "validator", "--prompt", "p")
    assert default.code == 0, default.text
    assert flag(shlex.split(default.out.strip()), "--agent") == "codex"
    assert world.task().rounds == []


def test_missing_orca_cli_leaves_no_residue(
    world: OrcaWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ORCA_CLI_COMMAND", "no-such-orca")
    res = world.run(*PLANNER)
    assert res.code == 1 and "not found on PATH" in res.text
    assert not (world.store.task_dir(TASK) / "runs").exists()
    assert not list(world.store.rounds_dir(TASK).glob("[0-9]*.md"))
    assert not (world.store.root / "seals").exists()


def test_missing_repo_dispatch_message(world: OrcaWorld) -> None:
    path = world.task().repos[0]["path"]
    os.chdir(world.base)
    shutil.rmtree(world.repo)
    res = world.run(*PLANNER)
    assert res.code == 1 and f"bound repo not found: {path}" in res.text
    assert not (world.store.task_dir(TASK) / "runs").exists()
    assert not list(world.store.rounds_dir(TASK).glob("[0-9]*.md"))


def test_concurrent_same_role_dispatch_reserves_one_round(world: OrcaWorld) -> None:
    results = world.race(PLANNER, PLANNER)
    assert sorted(code for code, _ in results) == [0, 1], results
    assert len(list(world.store.task_dir(TASK).glob("runs/*/dispatch.json"))) == 1
    assert len(list(world.store.rounds_dir(TASK).glob("[0-9]*.md"))) == 1


# -- collect: the accepted path ------------------------------------------------------------------
def test_collect_records_the_same_shape(world: OrcaWorld) -> None:
    world.dispatch("validator", "codex")
    world.finish(1, "D1", answer="fine\nVERDICT: concerns\n", agent="codex/gpt-6.1-sol")
    res = world.collect(1, "D1")
    assert res.code == 0, res.text
    record = world.record(1)
    old = {"n", "at", "phase", "role", "focus", "agent", "model", "stamp", "verdict"}
    assert old | {"state", "source", "file", "reason"} <= record.keys()
    assert (record["via"], record["session"], record["provider_verified"]) == ("orca", "D1", True)
    assert (record["verdict"], record["state"], record["source"]) == ("concerns", "valid", "engine")
    text = Path(str(record["file"])).read_text(encoding="utf-8")
    assert "Dispatch: D1" in text and "VERDICT: concerns" in text
    assert "| 001 |" in (world.store.rounds_dir(TASK) / "index.md").read_text(encoding="utf-8")


def test_provider_prefix_only(world: OrcaWorld) -> None:
    assert world.cycle("validator", "codex", worker="codex/another-model").code == 0
    assert world.record(1)["provider_verified"] is True
    assert world.cycle("planner", "claude", focus="x", worker="claude").code == 0
    assert world.record(2)["provider_verified"] is True


def test_released_worker_without_agent_records_provider_unverified(world: OrcaWorld) -> None:
    assert world.cycle("planner", "claude", worker=None).code == 0
    record = world.record(1)
    assert record["provider_verified"] is False and record["state"] == "valid"
    assert "provider not verified" in Path(str(record["file"])).read_text(encoding="utf-8")


def _row(dispatch_id: str, agent: str = "claude") -> dict[str, str]:
    return {"dispatchId": dispatch_id, "state": "succeeded", "liveness": "live", "agent": agent}


def test_worker_list_fallback_pages(world: OrcaWorld) -> None:
    world.dispatch()
    world.finish(1, "D1", register=False)
    world.pages([_row("U1")], [_row("D1")])
    assert world.collect(1, "D1").code == 0
    calls = world.orca_calls()
    assert [call[1] for call in calls] == ["worker-show", "worker-list", "worker-list"]
    assert calls[2][-2] == "--cursor" and decode_cursor(calls[2][-1]) == 1  # Orca's opaque cursor
    assert world.record(1)["provider_verified"] is True  # the list row carried the agent


def _calls(world: OrcaWorld) -> list[str]:
    return [call[1] for call in world.orca_calls()]


def test_show_without_agent_takes_the_provider_from_the_list_row(world: OrcaWorld) -> None:
    world.dispatch()
    world.finish(1, "D1", agent="claude")
    assert world.collect(1, "D1").code == 0
    assert _calls(world) == ["worker-show", "worker-list"]
    assert world.record(1)["provider_verified"] is True


def test_show_with_its_own_agent_needs_no_list(world: OrcaWorld) -> None:
    world.dispatch()
    world.finish(1, "D1", register=False)
    shown = {"ok": True, "result": {**_show_result("D1"), "agent": "claude/some-model"}}
    world.raw_show("D1", {"raw": json.dumps(shown)})
    assert world.collect(1, "D1").code == 0
    assert _calls(world) == ["worker-show"]
    assert world.record(1)["provider_verified"] is True


def _show_result(dispatch_id: str) -> dict[str, str]:
    return {
        "dispatchId": dispatch_id,
        "state": "succeeded",
        "liveness": "live",
        "taskId": "t",
        "runId": "r",
        "stage": "settled",
    }


def test_list_failing_during_enrichment_leaves_the_provider_unverified(world: OrcaWorld) -> None:
    world.dispatch()
    world.finish(1, "D1", agent="claude")
    world.list_fails()
    assert world.collect(1, "D1").code == 0
    assert world.record(1)["provider_verified"] is False
    assert _calls(world) == ["worker-show", "worker-list"]


def test_list_row_with_another_provider_refuses_even_when_show_has_none(world: OrcaWorld) -> None:
    world.dispatch()
    world.finish(1, "D1", agent="codex/gpt-6.1-sol")
    res = world.collect(1, "D1")
    assert res.code == 1 and "not as the dispatched provider 'claude'" in res.text


def test_fake_orca_replays_the_documented_real_envelopes(world: OrcaWorld) -> None:
    world.worker("D1", "succeeded", "codex/gpt-6.1-sol")
    world.worker("D2", "succeeded", None)
    released_row = {"dispatchId": "D2", "state": "succeeded", "liveness": "exited"}
    world.pages([_row("D1", "codex/gpt-6.1-sol")], [released_row])
    listed = _fake("worker-list", "--json")
    shown = _fake("worker-show", "--dispatch", "D1", "--json")
    released = _fake("worker-show", "--dispatch", "D2", "--json")
    assert set(listed) == set(REAL_LIST) == {"ok", "result"} and listed["ok"] is True
    real = REAL_LIST["result"]
    got = listed["result"]
    assert set(got) == set(real)  # workers, scope, nextCursor, warnings
    assert set(got["scope"]) == set(real["scope"])
    assert isinstance(got["nextCursor"], str) and isinstance(got["warnings"][0], str)
    row_keys = set().union(*(set(r) for r in real["workers"]))
    needed = set(real["workers"][1])  # the smallest real row: a released worker
    assert needed <= set(got["workers"][0]) <= row_keys
    last = _fake("worker-list", "--json", "--cursor", got["nextCursor"])["result"]
    assert "nextCursor" not in last and "agent" not in last["workers"][0]
    for answer in (shown, released):
        assert set(answer) == {"ok", "result"} and answer["ok"] is True
        keys = set(answer["result"])
        assert set(REAL_SHOW_LIVE["result"]) - {"autoReleaseAt"} <= keys | {"waitingOnHuman"}
        assert keys <= set(REAL_SHOW_LIVE["result"]) | set(REAL_SHOW_RELEASED["result"])
        assert "agent" not in keys  # worker-show never reports the agent
        assert answer["result"]["dispatchId"] in ("D1", "D2")


def _fake(*args: str) -> dict:
    done = subprocess.run(["orca-fake", "orchestration", *args], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


@pytest.mark.parametrize(
    "answer",
    [
        {"workers": []},  # the old, unwrapped guess
        {"ok": False, "result": {"workers": []}},
        {"ok": True},
        {"ok": True, "result": []},
        {"ok": True, "result": {"workers": "x"}},
        {"ok": True, "result": {"workers": [], "nextCursor": 5}},
        [],
    ],
)
def test_other_list_shapes_fail_closed(answer: object, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(orca, "_run", lambda args: answer)
    with pytest.raises(OrcaError):
        orca._page("")


def test_real_samples_parse_and_unknown_show_shapes_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(orca, "_run", lambda args: REAL_LIST)
    rows, following = orca._page("")
    assert following == REAL_LIST["result"]["nextCursor"] and len(rows) == 2
    assert [orca._row(r).agent for r in rows] == ["codex/gpt-6.1-sol", ""]
    for sample in (REAL_SHOW_LIVE, REAL_SHOW_RELEASED):
        row = orca._row(orca._result(sample, "worker-show"))
        assert row.state == "succeeded" and row.agent == "" and row.running is False
    with pytest.raises(OrcaError):
        orca._result(REAL_SHOW_LIVE["result"], "worker-show")  # a bare row is not an envelope


def test_worker_list_scan_is_bounded_to_five_pages(world: OrcaWorld) -> None:
    world.dispatch()
    world.finish(1, "D1", register=False)
    world.pages(*[[_row(f"U{i}")] for i in range(5)], [_row("D1")])
    res = world.collect(1, "D1")
    assert res.code == 1 and "not in Orca's worker list" in res.text
    assert [call[1] for call in world.orca_calls()].count("worker-list") == 5


# -- collect: refusals change nothing -------------------------------------------------------------
def _ready(w: OrcaWorld, mp: pytest.MonkeyPatch) -> None:
    w.finish(1, "D1", state="ready")


def _orca_absent(w: OrcaWorld, mp: pytest.MonkeyPatch) -> None:
    w.finish(1, "D1")
    mp.setenv("ORCA_CLI_COMMAND", "no-such-orca")


def _show_fails(w: OrcaWorld, mp: pytest.MonkeyPatch) -> None:
    w.finish(1, "D1", register=False)
    w.raw_show("D1", {"exit": 2})


def _not_json(w: OrcaWorld, mp: pytest.MonkeyPatch) -> None:
    w.finish(1, "D1", register=False)
    w.raw_show("D1", {"raw": "not json"})


def _no_liveness(w: OrcaWorld, mp: pytest.MonkeyPatch) -> None:
    w.finish(1, "D1", register=False)
    w.raw_show("D1", {"dispatchId": "D1", "state": "succeeded", "agent": "claude"})


def _other_id(w: OrcaWorld, mp: pytest.MonkeyPatch) -> None:
    w.finish(1, "D1", register=False)
    w.raw_show("D1", _row("X9"))


def _other_provider(w: OrcaWorld, mp: pytest.MonkeyPatch) -> None:
    w.finish(1, "D1", agent="codex/gpt-6.1-sol")


def _stale_answer(w: OrcaWorld, mp: pytest.MonkeyPatch) -> None:
    w.finish(1, "D1")
    os.utime(w.dispatch_json(1)["answer"], (1, 1))


def _blank_answer(w: OrcaWorld, mp: pytest.MonkeyPatch) -> None:
    w.finish(1, "D1", answer="  \n")


def _no_answer(w: OrcaWorld, mp: pytest.MonkeyPatch) -> None:
    w.finish(1, "D1", answer=None)


def _no_receipt(w: OrcaWorld, mp: pytest.MonkeyPatch) -> None:
    w.finish(1, "D1", receipt=None)


def _receipt_of_another_worker(w: OrcaWorld, mp: pytest.MonkeyPatch) -> None:
    w.finish(1, "D1", receipt=f"ROUND {w.dispatch_json(1)['nonce']} DISPATCH D9\n")


REFUSALS: dict[str, tuple[Callable[[OrcaWorld, pytest.MonkeyPatch], None], str]] = {
    "running": (_ready, WAIT),
    "orca-absent": (_orca_absent, "cannot confirm the worker for dispatch D1"),
    "show-fails": (_show_fails, "cannot confirm the worker"),
    "not-json": (_not_json, "did not print JSON"),
    "no-liveness": (_no_liveness, "lacks liveness"),
    "other-dispatch-id": (_other_id, "not D1"),
    "other-provider": (_other_provider, "not as the dispatched provider 'claude'"),
    "stale-answer": (_stale_answer, "no answer at"),
    "blank-answer": (_blank_answer, "no answer at"),
    "no-answer": (_no_answer, "no answer at"),
    "no-receipt": (_no_receipt, "no dispatch receipt"),
    "receipt-of-another-worker": (_receipt_of_another_worker, "is not the worker of round 1"),
}


@pytest.mark.parametrize("name", sorted(REFUSALS))
def test_collect_refusals_leave_state_byte_identical(
    world: OrcaWorld, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    setup, expected = REFUSALS[name]
    world.dispatch("planner", "claude")
    setup(world, monkeypatch)
    before = world.snapshot()
    res = world.collect(1, "D1")
    assert res.code == 1, res.text
    assert expected in res.text
    assert world.snapshot() == before
    assert world.task().rounds == []


def test_collect_needs_a_dispatch_id_and_a_dispatched_round(world: OrcaWorld) -> None:
    world.dispatch()
    assert world.run("round", TASK, "collect", "--round", "1").code == 2
    res = world.collect(7, "D1")
    assert res.code == 1 and "round 7 was not dispatched by the engine" in res.text


def test_dispatch_id_cannot_settle_two_rounds(world: OrcaWorld) -> None:
    assert world.cycle("planner", "claude").code == 0
    world.dispatch("planner", "claude", focus="b")
    world.finish(2, "D1")
    before = world.snapshot()
    for res in (
        world.collect(2, "D1"),
        world.abort(2, "--reason", "r", "--dispatch-id", "D1"),
    ):
        assert res.code == 1 and "already settled round 001" in res.text
    assert world.snapshot() == before


def test_unrelated_same_provider_dispatch_cannot_collect_or_abort(world: OrcaWorld) -> None:
    world.dispatch()
    world.finish(1, "D1")
    world.worker("U1", "succeeded", "claude")  # finished, same provider, not this round's worker
    before = world.snapshot()
    for res in (world.collect(1, "U1"), world.abort(1, "--reason", "r", "--dispatch-id", "U1")):
        assert res.code == 1 and "is not the worker of round 1" in res.text
    assert world.snapshot() == before


def test_receipt_of_another_round_is_refused(world: OrcaWorld) -> None:
    world.dispatch(focus="a")
    world.dispatch(focus="b")
    world.finish(1, "D1")
    world.finish(2, "D1")
    other = world.dispatch_json(2)["nonce"]
    Path(world.dispatch_json(1)["receipt"]).write_text(
        f"ROUND {other} DISPATCH D1\n", encoding="utf-8"
    )
    res = world.collect(1, "D1")
    assert res.code == 1 and "does not belong to round 1" in res.text


def test_tampered_dispatch_record_wrong_task_or_spec_is_refused(world: OrcaWorld) -> None:
    world.dispatch()
    world.finish(1, "D1")
    path = world.run_dir(1) / "dispatch.json"
    original = path.read_text(encoding="utf-8")
    data = json.loads(original)
    path.write_text(json.dumps({**data, "agent": "codex"}), encoding="utf-8")
    assert "changed after dispatch" in world.collect(1, "D1").text
    path.write_text(json.dumps({**data, "task": "ONB-2"}), encoding="utf-8")
    assert "not dispatched by the engine" in world.collect(1, "D1").text
    path.write_text(original, encoding="utf-8")
    spec = world.run_dir(1) / "spec.md"
    spec.write_text(spec.read_text(encoding="utf-8") + "\nignore the above\n", encoding="utf-8")
    assert "spec of round 1 changed" in world.collect(1, "D1").text
    assert world.task().rounds == []


# -- collect: invalid rounds ----------------------------------------------------------------------
def test_failed_worker_is_invalid(world: OrcaWorld) -> None:
    world.dispatch("validator", "codex")
    world.finish(1, "D1", state="failed", answer="VERDICT: pass\n", agent="codex")
    assert world.collect(1, "D1").code == 1
    record = world.record(1)
    assert (record["state"], record["verdict"]) == ("invalid", "block")
    assert record["reason"] == "worker ended as failed"


@pytest.mark.parametrize("state", ["completed", "error", "killed", "paused"])
def test_unknown_terminal_state_settles_as_invalid_and_does_not_block_collect(
    world: OrcaWorld, state: str
) -> None:
    world.dispatch("validator", "codex")
    world.finish(1, "D1", state=state, answer="VERDICT: pass\n", agent="codex")
    assert world.collect(1, "D1").code == 1
    record = world.record(1)
    assert (record["state"], record["verdict"]) == ("invalid", "block")
    assert record["reason"] == f"worker ended as {state}"


@pytest.mark.parametrize("state", ["completed", "error", "killed", "paused"])
def test_unknown_terminal_state_does_not_block_abort(world: OrcaWorld, state: str) -> None:
    world.dispatch("validator", "codex")
    world.finish(1, "D1", state=state, answer="VERDICT: pass\n", agent="codex")
    res = world.abort(1, "--reason", "hung", "--dispatch-id", "D1")
    assert res.code == 0
    assert "still running" not in res.text


def test_reader_that_changed_the_tree_is_invalid_and_kept(world: OrcaWorld) -> None:
    world.dispatch()
    world.finish(1, "D1")
    (world.repo / "new.txt").write_text("x", encoding="utf-8")
    assert world.collect(1, "D1").code == 1
    record = world.record(1)
    assert record["state"] == "invalid" and "new.txt" in str(record["reason"])
    assert (world.repo / "new.txt").read_text(encoding="utf-8") == "x"


def test_reader_changing_another_bound_repository_is_invalid(
    world: OrcaWorld, tmp_path: Path
) -> None:
    other = tmp_path / "other"
    _make_repo(other)
    assert world.run("bind", TASK, "--repo", str(other)).code == 0
    world.dispatch()
    world.finish(1, "D1")
    (other / "second.txt").write_text("x", encoding="utf-8")
    assert world.collect(1, "D1").code == 1
    record = world.record(1)
    assert record["state"] == "invalid" and "second.txt" in str(record["reason"])
    assert str(other) in str(record["reason"])


def test_coordinator_commit_during_a_reader_round_invalidates_it(world: OrcaWorld) -> None:
    world.dispatch()
    world.finish(1, "D1")
    (world.repo / "b.txt").write_text("b", encoding="utf-8")
    for args in (["add", "."], ["commit", "-qm", "more"]):
        subprocess.run(["git", *args], cwd=world.repo, check=True, capture_output=True)
    assert world.collect(1, "D1").code == 1
    assert "HEAD moved" in str(world.record(1)["reason"])


def test_vanished_repo_at_collect_is_invalid_not_a_traceback(world: OrcaWorld) -> None:
    world.dispatch()
    world.finish(1, "D1")
    os.chdir(world.base)
    shutil.rmtree(world.repo)
    res = world.collect(1, "D1")
    assert res.code == 1 and "Traceback" not in res.text
    assert "bound repo not found" in str(world.record(1)["reason"])


# -- collect: idempotence, abort interplay --------------------------------------------------------
def test_collect_is_idempotent(world: OrcaWorld) -> None:
    assert world.cycle().code == 0
    before, record = world.snapshot(), world.record(1)
    res = world.collect(1, "D1")
    assert res.code == 0 and "Round 001 was already collected (verdict info)" in res.text
    assert world.snapshot() == before and world.record(1) == record
    other = world.collect(1, "D2")
    assert other.code == 1 and "already collected with dispatch D1" in other.text


def test_abort_after_collect_is_refused(world: OrcaWorld) -> None:
    assert world.cycle().code == 0
    before = world.snapshot()
    res = world.abort(1, "--reason", "r", "--dispatch-id", "D1")
    assert res.code == 1 and "already collected" in res.text
    assert world.snapshot() == before


def test_collect_after_abort_is_refused(world: OrcaWorld) -> None:
    world.dispatch()
    assert world.abort(1, "--reason", "r", "--never-started").code == 0
    before = world.snapshot()
    res = world.collect(1, "D1")
    assert res.code == 1 and "was aborted" in res.text
    assert world.snapshot() == before


# -- abort ----------------------------------------------------------------------------------------
def test_abort_needs_reason_and_binding(world: OrcaWorld) -> None:
    world.dispatch()
    world.finish(1, "D1")
    assert world.abort(1, "--dispatch-id", "D1").code == 2  # no --reason
    assert world.abort(1, "--reason", "r").code == 2  # no binding
    assert world.abort(1, "--reason", "r", "--dispatch-id", "D1", "--never-started").code == 2
    world.worker("D1", "ready")
    res = world.abort(1, "--reason", "r", "--dispatch-id", "D1")
    assert res.code == 1 and "orca-fake orchestration worker-stop --dispatch D1" in res.text
    assert world.task().rounds == []
    world.worker("D1", "succeeded")
    assert world.abort(1, "--reason", "stale run", "--dispatch-id", "D1").code == 0
    record = world.record(1)
    assert (record["settlement"], record["state"], record["verdict"]) == (
        "aborted",
        "invalid",
        "block",
    )
    assert (record["session"], record["reason"]) == ("D1", "stale run")
    assert "aborted-round ONB-1 001" in world.store.read_log(TASK)
    audit = [e for e in world.task().evidence if e["kind"] == "aborted-round"]
    assert len(audit) == 1 and audit[0]["n"] == 1 and audit[0]["reason"] == "stale run"


def test_never_started_is_an_audited_operator_assertion(
    world: OrcaWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    world.dispatch()
    world.dispatch(focus="b")
    monkeypatch.setenv("ORCA_CLI_COMMAND", "no-such-orca")  # abort needs no Orca for this
    blank = world.abort(2, "--reason", "  ", "--never-started")
    assert blank.code == 1 and "--reason must say why" in blank.text
    res = world.abort(1, "--reason", "wrong prompt", "--never-started")
    assert res.code == 0 and "your assertion that no worker started" in res.text
    record = world.record(1)
    assert (record["operator_assertion"], record["session"]) == ("never-started", "")
    audit = [e for e in world.task().evidence if e["kind"] == "aborted-round"]
    assert audit[0]["assertion"] == "never-started"
    assert "operator asserts" in world.store.read_log(TASK)


def test_abort_crash_windows(world: OrcaWorld, monkeypatch: pytest.MonkeyPatch) -> None:
    world.dispatch()
    world.finish(1, "D1")
    real_write, real_log = TaskStore._write, TaskStore.append_log
    hits: list[str] = []

    def flaky_write(self: TaskStore, directory: Path, task: object) -> object:
        if "write" not in hits:
            hits.append("write")
            raise OSError("disk full")
        return real_write(self, directory, task)  # type: ignore[arg-type]

    def flaky_log(self: TaskStore, task_id: str, entry: str) -> None:
        if "log" not in hits:
            hits.append("log")
            raise OSError("log lost")
        real_log(self, task_id, entry)

    monkeypatch.setattr(TaskStore, "_write", flaky_write)
    monkeypatch.setattr(TaskStore, "append_log", flaky_log)
    tail = ("--reason", "r", "--dispatch-id", "D1")
    assert world.abort(1, *tail).code == 1  # before the state write: nothing recorded
    assert world.task().rounds == [] and world.task().evidence == []
    res = world.abort(1, *tail)  # state written, then the log fails
    assert res.code == 1 and "log lost" in res.text
    assert world.record(1)["settlement"] == "aborted" and len(world.task().evidence) == 1
    assert "aborted-round ONB-1 001" not in world.store.read_log(TASK)
    res = world.abort(1, *tail)  # the retry restores the log projection, once
    assert res.code == 1 and "restored" in res.text
    assert world.abort(1, *tail).code == 1
    assert world.store.read_log(TASK).count("aborted-round ONB-1 001") == 1
    assert len(world.task().evidence) == 1


# -- collect: crash windows and races -------------------------------------------------------------
def _flaky_once(real: Callable[..., object], error: str) -> Callable[..., object]:
    hits: list[int] = []

    def flaky(*args: object) -> object:
        if not hits:
            hits.append(1)
            raise OSError(error)
        return real(*args)

    return flaky


def test_crash_after_markdown_before_record_retry_succeeds_identically(
    world: OrcaWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    world.dispatch("validator", "codex")
    world.finish(1, "D1", answer="ok\nVERDICT: pass\n", agent="codex")
    monkeypatch.setattr(TaskStore, "_write", _flaky_once(TaskStore._write, "disk full"))
    res = world.collect(1, "D1")
    assert res.code == 1 and "disk full" in res.text
    assert world.task().rounds == []
    first = Path(world.dispatch_json(1)["file"]).read_text(encoding="utf-8")
    assert world.collect(1, "D1").code == 0
    record = world.record(1)
    second = Path(str(record["file"])).read_text(encoding="utf-8")
    keep = ("- Verdict", "- Dispatch", "## Answer")
    assert [ln for ln in first.splitlines() if ln.startswith(keep)] == [
        ln for ln in second.splitlines() if ln.startswith(keep)
    ]
    assert record["verdict"] == "pass"


def test_crash_after_record_before_index_collect_reports_already_collected(
    world: OrcaWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    world.dispatch("validator", "codex")
    world.finish(1, "D1", answer="ok\nVERDICT: pass\n", agent="codex")
    monkeypatch.setattr(
        store_module, "render_index", _flaky_once(store_module.render_index, "no index")
    )
    assert world.collect(1, "D1").code == 1
    record = world.record(1)  # state.json was written before the index failed
    text = Path(str(record["file"])).read_text(encoding="utf-8")
    assert record["verdict"] == "pass" and "Verdict: pass" in text
    res = world.collect(1, "D1")
    assert res.code == 0 and "already collected" in res.text


def test_concurrent_collect_and_abort(world: OrcaWorld) -> None:
    world.dispatch()
    world.finish(1, "D1")
    barrier, out = threading.Barrier(2), {}

    def go(name: str, work: Callable[[], object]) -> None:
        barrier.wait()
        try:
            out[name] = work()
        except DispatchError as exc:
            out[name] = exc

    threads = [
        threading.Thread(
            target=go, args=("collect", lambda: collect_round(world.store, RoundRef(TASK, 1), "D1"))
        ),
        threading.Thread(
            target=go,
            args=("abort", lambda: abort_round(world.store, RoundRef(TASK, 1), "r", "D1")),
        ),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(60)
    assert set(out) == {"collect", "abort"}
    winners = [name for name, value in out.items() if not isinstance(value, Exception)]
    assert len(winners) == 1 and len(world.task().rounds) == 1
    record = world.record(1)
    text = Path(str(record["file"])).read_text(encoding="utf-8")
    if winners == ["abort"]:
        assert record["settlement"] == "aborted" and ": aborted" in text.splitlines()[0]
    else:
        assert "settlement" not in record and ": aborted" not in text.splitlines()[0]


def test_two_processes_collect_and_abort_the_same_round(world: OrcaWorld) -> None:
    world.dispatch()
    world.finish(1, "D1")
    results = world.race(
        ["round", TASK, "collect", "--round", "1", "--dispatch-id", "D1"],
        ["round", TASK, "abort", "--round", "1", "--reason", "r", "--dispatch-id", "D1"],
    )
    assert sorted(code for code, _ in results) == [0, 1], results
    record = world.record(1)
    text = Path(str(record["file"])).read_text(encoding="utf-8")
    assert (record.get("settlement") == "aborted") == (": aborted" in text.splitlines()[0])


@pytest.mark.parametrize("verb", ["collect", "abort"])
def test_two_processes_same_dispatch_id_different_rounds(world: OrcaWorld, verb: str) -> None:
    world.dispatch(focus="a")
    world.dispatch(focus="b")
    world.finish(1, "X1")
    world.finish(2, "X1")
    tail = ["--dispatch-id", "X1"] + (["--reason", "r"] if verb == "abort" else [])
    results = world.race(*[["round", TASK, verb, "--round", str(n), *tail] for n in (1, 2)])
    assert sorted(code for code, _ in results) == [0, 1], results
    sessions = [r.get("session") for r in world.task().rounds]
    assert sessions == ["X1"]


# -- control plane --------------------------------------------------------------------------------
def _approval_mutation(w: OrcaWorld, evidence: Path) -> None:
    w.edit_state(lambda d: d["approvals"][0].update(target="other"))


CONTROL_CASES: dict[str, tuple[Callable[[OrcaWorld, Path], None], str]] = {
    "stamp": (
        lambda w, e: w.edit_state(lambda d: d["code_stamp"].update(key="evil")),
        "task.code_stamp",
    ),
    "stamp-nested": (  # same key, a nested field the gates read
        lambda w, e: w.edit_state(lambda d: d["code_stamp"]["repos"][0].update(head="b" * 40)),
        "task.code_stamp",
    ),
    "stamp-obligations": (
        lambda w, e: w.edit_state(lambda d: d["code_stamp"].update(policy_reduced=["judges:x"])),
        "task.code_stamp",
    ),
    "round-record": (
        lambda w, e: w.edit_state(lambda d: d["rounds"][0].update(verdict="block")),
        "round record 1",
    ),
    "approval-changed": (_approval_mutation, "task.approvals #1"),
    "approval-removed": (
        lambda w, e: w.edit_state(lambda d: d["approvals"].clear()),
        "task.approvals: 1 entries removed",
    ),
    "evidence-entry": (
        lambda w, e: w.edit_state(lambda d: d["evidence"][0].update(repo="zz")),
        "evidence #1",
    ),
    "evidence-file": (lambda w, e: e.write_text("changed", encoding="utf-8"), "evidence #1"),
    "round-markdown": (
        lambda w, e: Path(str(w.record(1)["file"])).write_text("edited", encoding="utf-8"),
        "round file",
    ),
}


@pytest.mark.parametrize("case", sorted(CONTROL_CASES))
def test_control_plane_changes_are_detected(world: OrcaWorld, tmp_path: Path, case: str) -> None:
    assert world.cycle().code == 0
    evidence = tmp_path / "checks.txt"
    evidence.write_text("passed", encoding="utf-8")
    approval = {"action": "plan", "target": TASK, "user_reply": "ok", "stamp": "", "at": "x"}
    entry = {"kind": "checks", "repo": "r", "path": str(evidence)}

    def add_records(task: Task) -> None:
        task.approvals.append(approval)
        task.evidence.append(entry)

    world.store.mutate(TASK, add_records)
    world.dispatch("validator", "codex")
    world.finish(2, "D2", answer="ok\nVERDICT: pass\n", agent="codex")
    mutate, expected = CONTROL_CASES[case]
    mutate(world, evidence)
    before = world.snapshot()
    res = world.collect(2, "D2")
    assert res.code == 1 and "control files changed" in res.text and expected in res.text
    assert world.snapshot() == before
    assert len(world.task().rounds) <= 1


def test_modified_dispatch_metadata_is_detected_by_its_seal(world: OrcaWorld) -> None:
    world.dispatch()
    world.finish(1, "D1")
    path = world.run_dir(1) / "dispatch.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["control"]["stamp_key"] = "forged"  # an edit that would hide the tampering
    path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    res = world.collect(1, "D1")
    assert res.code == 1 and "changed after dispatch" in res.text


def test_legitimate_concurrent_engine_writes_do_not_trip_the_control_check(
    world: OrcaWorld,
) -> None:
    world.dispatch(focus="a")
    world.dispatch(focus="b")
    world.finish(1, "D1")
    world.finish(2, "D2")
    assert world.run("fact", TASK, "learned something").code == 0
    assert world.run("note", TASK, "a note").code == 0
    assert world.collect(2, "D2").code == 0
    assert world.collect(1, "D1").code == 0


def test_store_inside_the_repo_but_ignored_by_git(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    world = make_world(tmp_path, monkeypatch, capsys, state_in_repo=True)
    assert world.cycle().code == 0  # receipt and answer under the ignored store keep the tree
    world.dispatch(focus="b")
    world.finish(2, "D2")
    earlier = Path(str(world.record(1)["file"]))
    earlier.write_text(earlier.read_text(encoding="utf-8") + "x", encoding="utf-8")
    res = world.collect(2, "D2")
    assert res.code == 1 and "round file" in res.text
    world.assert_hermetic()


# -- harness and compatibility --------------------------------------------------------------------
def test_fake_orca_receives_only_worker_show_and_worker_list(world: OrcaWorld) -> None:
    assert world.cycle().code == 0
    calls = world.orca_calls()
    assert calls and all(call[1] in ("worker-show", "worker-list") for call in calls)
    with pytest.raises(OrcaError, match="refused"):
        _run(["orchestration", "worker-start", "--spec-file", "x"])
    assert world.orca_calls() == calls  # refused before any process was spawned
    stray = subprocess.run(["orca-fake", "orchestration", "worker-stop"], capture_output=True)
    assert stray.returncode == 3
    world.orca_log.write_text("", encoding="utf-8")  # forget the deliberate probe
    world.assert_hermetic()


def test_manual_record_stays_context_only(world: OrcaWorld, tmp_path: Path) -> None:
    note = tmp_path / "note.md"
    note.write_text("ran elsewhere", encoding="utf-8")
    assert world.run("round", TASK, "record", "--role", "planner", "--file", str(note)).code == 0
    assert world.record(1)["state"] == "context"


def test_parser_needs_no_role_for_collect_and_abort() -> None:
    parser = build_parser()
    args = parser.parse_args(["round", TASK, "collect", "--round", "1", "--dispatch-id", "D"])
    assert args.action == "collect" and not hasattr(args, "role")
    with pytest.raises(SystemExit):
        parser.parse_args(
            ["round", TASK, "collect", "--round", "1", "--dispatch-id", "D", "--role", "x"]
        )
    with pytest.raises(SystemExit):
        parser.parse_args(["round", TASK, "run", "--role", "planner"])


def test_guide_documents_the_new_verbs() -> None:
    for verb in (
        "round <ID> dispatch",
        "round <ID> collect",
        "round <ID> abort",
        "--never-started",
    ):
        assert verb in GUIDE


# -- cross-examination, launch receipt, CHANGE lines and scratch -----------------------------------
def _receipt(dispatch_id: str, agent: str, model: str) -> dict[str, object]:
    """The shape of a real ``worker-start --json`` receipt (Orca 1.4.256, captured)."""
    result = {"dispatchId": dispatch_id, "taskId": "task_1", "runId": "run_1", "state": "ready"}
    result |= {"agent": agent, "model": model, "effort": "medium", "mode": "terminal"}
    return {"ok": True, "result": result}


def _launch(world: OrcaWorld, n: int, agent: str, model: str, dispatch_id: str = "D1") -> None:
    receipt = json.dumps(_receipt(dispatch_id, agent, model))
    Path(world.dispatch_json(n)["launch"]).write_text(receipt, encoding="utf-8")


def test_printed_line_saves_the_launch_receipt(world: OrcaWorld) -> None:
    made = world.dispatch("planner", "claude")
    assert "--json" in made.argv
    launch = str(world.run_dir(1) / "launch.json")
    assert made.argv[-2:] == [">", launch]
    assert world.dispatch_json(1)["launch"] == launch


def test_rebuttal_round_cross_examines_settled_rounds(world: OrcaWorld) -> None:
    assert world.cycle("planner", "claude").code == 0
    first = str(world.record(1)["file"])
    made = world.dispatch("planner", "claude", "cross", "--rebut", "1")
    spec = (world.run_dir(made.n) / "spec.md").read_text(encoding="utf-8")
    assert "Cross-examination" in spec and f"round 001 (claude): {first}" in spec
    assert world.dispatch_json(made.n)["rebuts"] == [1]
    world.finish(made.n, f"D{made.n}")
    assert world.collect(made.n, f"D{made.n}").code == 0
    record = world.record(made.n)
    assert record["rebuts"] == [1]
    assert "Cross-examines rounds: 001" in Path(str(record["file"])).read_text(encoding="utf-8")


def test_rebut_refuses_unknown_and_invalid_rounds(world: OrcaWorld) -> None:
    unknown = world.run(*PLANNER, "--rebut", "7")
    assert unknown.code == 1 and "round 007 is not settled" in unknown.text
    assert not (world.store.task_dir(TASK) / "runs").exists()
    world.dispatch("validator", "codex")
    world.finish(1, "D1", state="failed", agent="codex")
    assert world.collect(1, "D1").code == 1
    invalid = world.run(*PLANNER, "--rebut", "1")
    assert invalid.code == 1 and "is invalid and cannot be cross-examined" in invalid.text


def test_launch_receipt_with_another_model_refuses_collect(world: OrcaWorld) -> None:
    world.dispatch("planner", "claude", "", "--model", "opus")
    world.finish(1, "D1", agent=None)  # released worker: Orca no longer names the agent
    _launch(world, 1, "claude", "sonnet")
    refused = world.collect(1, "D1")
    assert refused.code == 1 and "on model 'sonnet', not on the dispatched 'opus'" in refused.text
    assert world.task().rounds == []
    _launch(world, 1, "codex", "opus")
    assert "not as the dispatched provider 'claude'" in world.collect(1, "D1").text
    _launch(world, 1, "claude", "opus", dispatch_id="OTHER")
    assert "belongs to dispatch OTHER, not D1" in world.collect(1, "D1").text
    assert world.task().rounds == []
    _launch(world, 1, "claude", "opus")
    assert world.collect(1, "D1").code == 0
    assert world.record(1)["launch_verified"] is True


def test_partial_launch_evidence_stays_unverified(world: OrcaWorld) -> None:
    world.dispatch("planner", "claude", "", "--model", "opus")
    world.finish(1, "D1")
    _launch(world, 1, "claude", "")
    assert world.collect(1, "D1").code == 0
    assert world.record(1)["launch_verified"] is False


def test_launch_receipt_parsing_and_legacy_dispatches(tmp_path: Path) -> None:
    real = parse_launch(_receipt("D1", "codex", "gpt-6.1-sol"))
    assert real == Launch("D1", "codex", "gpt-6.1-sol")
    nested = {"ok": True, "result": {"dispatchId": "D2", "launch": {"effective": {"agent": "a"}}}}
    assert parse_launch(nested) == Launch("D2", "a", "")
    partial = _receipt("D3", "codex", "gpt-6.1-sol")
    partial["result"]["launch"] = {"effective": {"model": "gpt-6.1-mini"}}  # type: ignore[index]
    assert parse_launch(partial) == Launch("D3", "codex", "gpt-6.1-mini")
    assert parse_launch({"ok": False, "result": {"dispatchId": "D1"}}) is None
    assert parse_launch(["not", "a", "receipt"]) is None
    legacy = {"n": 1, "provider": "claude", "model": ""}  # dispatched before receipts existed
    assert launch_verified(legacy, "D1") is False
    broken = tmp_path / "launch.json"
    broken.write_text("{not json", encoding="utf-8")
    assert launch_verified({**legacy, "launch": str(broken)}, "D1") is False


def test_no_launch_receipt_is_unverified_not_refused(world: OrcaWorld) -> None:
    assert world.cycle("planner", "claude").code == 0
    record = world.record(1)
    assert record["launch_verified"] is False and record["state"] == "valid"
    assert "launch not verified" in Path(str(record["file"])).read_text(encoding="utf-8")


def test_change_lines_and_scratch_are_recorded(world: OrcaWorld) -> None:
    world.dispatch("validator", "codex")
    scratch = Path(world.dispatch_json(1)["scratch"])
    scratch.mkdir(parents=True)
    (scratch / "probe.py").write_text("print(1)\n", encoding="utf-8")
    answer = "CHANGE: src/a.py:10 - guard None\n- CHANGE: src/b.py:3 - rename\nVERDICT: block\n"
    world.finish(1, "D1", answer=answer, agent="codex")
    assert world.collect(1, "D1").code == 0
    record = world.record(1)
    assert record["changes"] == ["src/a.py:10 - guard None", "src/b.py:3 - rename"]
    assert record["scratch_used"] is True and record["verdict"] == "block"
    text = Path(str(record["file"])).read_text(encoding="utf-8")
    assert "Required changes:" in text and f"Scratch evidence: {scratch}" in text


def test_spec_offers_the_scratch_folder_and_change_format(world: OrcaWorld) -> None:
    world.dispatch("validator", "codex")
    spec = (world.run_dir(1) / "spec.md").read_text(encoding="utf-8")
    assert str(world.run_dir(1) / "scratch") in spec
    assert "CHANGE: <path>:<line> - <what to change>" in spec
