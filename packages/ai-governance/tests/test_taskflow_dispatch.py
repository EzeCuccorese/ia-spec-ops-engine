"""Dispatch, collect and abort of Orca-run reader rounds.

Hermetic: a fake Orca CLI and a wrapped git (see ``orca_fakes``); no network, no real agent.
"""

# ruff: noqa: F401, F811
from __future__ import annotations

import json
import os
import shlex
import subprocess
import threading
from collections.abc import Callable
from pathlib import Path
from typing import TypedDict, Unpack

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
from ai_governance.taskflow.config import load_config
from ai_governance.taskflow.control import DispatchError, UsageRefusal
from ai_governance.taskflow.dispatch import Dispatched, DispatchRequest, plan_dispatch
from ai_governance.taskflow.guide import GUIDE
from ai_governance.taskflow.models import Task
from ai_governance.taskflow.orca import OrcaError, _run, orca_command
from ai_governance.taskflow.parser import build_parser
from ai_governance.taskflow.prompts import (
    READ_ONLY_LIMIT,
    WEB_INSTRUCTION,
    artifact_instruction,
)
from ai_governance.taskflow.refresh import refresh
from ai_governance.taskflow.store import TaskStore
from orca_fakes import TASK, OrcaWorld, Result, _make_repo, decode_cursor, flag, make_world, world
from orca_real_samples import REAL_LIST, REAL_SHOW_LIVE, REAL_SHOW_RELEASED

WAIT = "orca-fake orchestration check --wait --types worker_done --timeout-ms 600000"
_SENTINEL = "__DEFAULT__"


class _DispatchOpts(TypedDict, total=False):
    role: str
    prompt: str
    model: str
    rebuts: tuple[int, ...]
    web: bool
    artifacts: tuple[str, ...]
    effort: str


def _dispatch(
    world: OrcaWorld,
    agent: str = "claude",
    focus: str = "",
    **opts: Unpack[_DispatchOpts],
) -> Dispatched:
    role = opts.get("role", "debater")
    cfg = load_config([world.repo])
    task = world.task()
    if role == "debater":
        task = refresh(world.store, task, cfg)
    return plan_dispatch(
        world.store,
        task,
        cfg,
        DispatchRequest(
            role=role,
            phase="work",
            focus=focus,
            prompt=opts.get("prompt", "do it"),
            agent={"agent": agent, "model": opts.get("model", "")},
            rebuts=opts.get("rebuts", ()),
            web=opts.get("web", False),
            artifacts=opts.get("artifacts", ()),
            effort=opts.get("effort", ""),
        ),
    )


def _cycle(
    world: OrcaWorld,
    agent: str = "claude",
    focus: str = "",
    **opts: object,
) -> Result:
    worker = opts.get("worker", _SENTINEL)
    answer = str(opts.get("answer", "Checked store.\nPOSITION: Keep rounds flat.\n"))
    made = _dispatch(world, agent=agent, focus=focus)
    worker_agent = agent if worker is _SENTINEL else worker
    world.finish(made.n, f"D{made.n}", answer=answer, agent=worker_agent)  # type: ignore[arg-type]
    return world.collect(made.n, f"D{made.n}")


# -- dispatch ----------------------------------------------------------------------------------
def test_dispatch_prints_one_worker_start_line_and_runs_nothing(world: OrcaWorld) -> None:
    made = _dispatch(world, "claude")
    assert made.argv[0] == orca_command()
    assert made.argv[1:3] == ["orchestration", "worker-start"]
    assert flag(made.argv, "--agent") == "claude"
    assert flag(made.argv, "--worktree") == "path:" + world.task().repos[0]["path"]
    assert flag(made.argv, "--spec-file") == str(world.run_dir(1) / "spec.md")
    assert len(made.line().splitlines()) == 1
    assert not world.orca_log.exists()
    assert world.task().rounds == []
    assert (world.run_dir(1) / "dispatch.json").exists()


def test_spec_has_the_full_prompt(world: OrcaWorld) -> None:
    _dispatch(world, "claude", focus="seat-1")
    spec = (world.run_dir(1) / "spec.md").read_text(encoding="utf-8")
    assert spec.startswith(READ_ONLY_LIMIT)
    assert str(world.run_dir(1) / "answer.txt") in spec
    assert str(world.run_dir(1) / "receipt.txt") in spec
    assert "Do not modify any file" in spec
    assert world.dispatch_json(1)["nonce"] in spec
    assert "do it" in spec
    assert "Role: debater. Task TASK-1" in spec


def test_json_argv_and_hostile_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    world = make_world(tmp_path, monkeypatch, capsys, repo_name="my repo $(x)\nnl")
    model = 'x"; rm -rf /'
    first = _dispatch(world, "claude", model=model)
    assert flag(first.argv, "--model") == model
    assert flag(first.argv, "--worktree") == "path:" + world.task().repos[0]["path"]
    assert "$(x)\n" in flag(first.argv, "--worktree")
    second = _dispatch(world, "claude", focus="two", model=model)
    plain = shlex.split(second.line())
    assert flag(plain, "--model") == model
    assert flag(plain, "--worktree") == flag(first.argv, "--worktree")
    assert flag(plain, "--task-title") == "debater round 2 of TASK-1"
    world.assert_hermetic()


def test_duplicate_dispatch_refused_without_burning_a_number(world: OrcaWorld) -> None:
    _dispatch(world)
    with pytest.raises(DispatchError, match="already dispatched"):
        _dispatch(world)
    files = sorted(p.name for p in world.store.rounds_dir(TASK).glob("[0-9]*.md"))
    assert len(files) == 1
    assert sorted(p.name for p in (world.store.task_dir(TASK) / "runs").iterdir()) == ["001"]
    assert _dispatch(world, "claude", focus="other").n == 2


def test_builder_and_judge_roles_are_refused(world: OrcaWorld) -> None:
    with pytest.raises(UsageRefusal, match="builder is not dispatched"):
        _dispatch(world, "claude", role="builder")
    with pytest.raises(UsageRefusal, match="Judges are not dispatched"):
        _dispatch(world, "codex", role="judge")
    assert not (world.store.task_dir(TASK) / "runs").exists()


def test_agent_rules_apply_at_dispatch(world: OrcaWorld) -> None:
    with pytest.raises(DispatchError, match="a human cannot run as a worker"):
        _dispatch(world, "human")
    with pytest.raises(DispatchError, match="not allowed here"):
        _dispatch(world, "nope")
    made = _dispatch(world, "codex")
    assert flag(made.argv, "--agent") == "codex"
    assert world.task().rounds == []


def test_missing_orca_cli_leaves_no_residue(
    world: OrcaWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ORCA_CLI_COMMAND", "no-such-orca")
    with pytest.raises(OrcaError, match="not found on PATH"):
        _dispatch(world, "claude")
    assert not (world.store.task_dir(TASK) / "runs").exists()
    assert not list(world.store.rounds_dir(TASK).glob("[0-9]*.md"))
    assert not (world.store.root / "seals").exists()


def test_missing_repo_dispatch_message(world: OrcaWorld) -> None:
    path = world.task().repos[0]["path"]
    os.chdir(world.base)
    import shutil

    shutil.rmtree(world.repo)
    with pytest.raises(DispatchError, match=f"bound repo not found: {path}"):
        _dispatch(world, "claude")
    assert not (world.store.task_dir(TASK) / "runs").exists()
    assert not list(world.store.rounds_dir(TASK).glob("[0-9]*.md"))


def test_concurrent_same_role_dispatch_reserves_one_round(world: OrcaWorld) -> None:
    barrier = threading.Barrier(2)
    results: list[int | str] = []

    def go() -> None:
        barrier.wait()
        try:
            _dispatch(world, "claude")
            results.append(0)
        except DispatchError:
            results.append(1)

    threads = [threading.Thread(target=go), threading.Thread(target=go)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30)
    assert sorted(results) == [0, 1]  # type: ignore[type-var]
    assert len(list(world.store.task_dir(TASK).glob("runs/*/dispatch.json"))) == 1
    assert len(list(world.store.rounds_dir(TASK).glob("[0-9]*.md"))) == 1


# -- collect: the accepted path ------------------------------------------------------------------
def test_collect_records_the_same_shape(world: OrcaWorld) -> None:
    _dispatch(world, "codex")
    world.finish(1, "D1", answer="fine\nPOSITION: Use Redis.\n", agent="codex/gpt-6.1-sol")
    res = world.collect(1, "D1")
    assert res.code == 0, res.text
    record = world.record(1)
    old = {"n", "at", "phase", "role", "focus", "agent", "model", "stamp", "verdict"}
    assert old | {"state", "source", "file", "reason"} <= record.keys()
    assert (record["via"], record["session"], record["provider_verified"]) == ("orca", "D1", True)
    assert (record["verdict"], record["state"], record["source"]) == ("info", "valid", "engine")
    assert record["position"] == "Use Redis."
    text = Path(str(record["file"])).read_text(encoding="utf-8")
    assert "Dispatch: D1" in text and "Use Redis." in text
    assert "| 001 |" in (world.store.rounds_dir(TASK) / "index.md").read_text(encoding="utf-8")


def test_provider_prefix_only(world: OrcaWorld) -> None:
    assert _cycle(world, "codex", worker="codex/another-model").code == 0
    assert world.record(1)["provider_verified"] is True
    assert _cycle(world, "claude", focus="x", worker="claude").code == 0
    assert world.record(2)["provider_verified"] is True


def test_released_worker_without_agent_records_provider_unverified(world: OrcaWorld) -> None:
    assert _cycle(world, "claude", worker=None).code == 0
    record = world.record(1)
    assert record["provider_verified"] is False and record["state"] == "valid"
    assert "provider not verified" in Path(str(record["file"])).read_text(encoding="utf-8")


def _row(dispatch_id: str, agent: str = "claude") -> dict[str, str]:
    return {"dispatchId": dispatch_id, "state": "succeeded", "liveness": "live", "agent": agent}


def test_worker_list_fallback_pages(world: OrcaWorld) -> None:
    _dispatch(world)
    world.finish(1, "D1", register=False)
    world.pages([_row("U1")], [_row("D1")])
    assert world.collect(1, "D1").code == 0
    calls = world.orca_calls()
    assert [call[1] for call in calls] == ["worker-show", "worker-list", "worker-list"]
    assert calls[2][-2] == "--cursor" and decode_cursor(calls[2][-1]) == 1
    assert world.record(1)["provider_verified"] is True


def _calls(world: OrcaWorld) -> list[str]:
    return [call[1] for call in world.orca_calls()]


def test_show_without_agent_takes_the_provider_from_the_list_row(world: OrcaWorld) -> None:
    _dispatch(world)
    world.finish(1, "D1", agent="claude")
    assert world.collect(1, "D1").code == 0
    assert _calls(world) == ["worker-show", "worker-list"]
    assert world.record(1)["provider_verified"] is True


def test_show_with_its_own_agent_needs_no_list(world: OrcaWorld) -> None:
    _dispatch(world)
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
    _dispatch(world)
    world.finish(1, "D1", agent="claude")
    world.list_fails()
    assert world.collect(1, "D1").code == 0
    assert world.record(1)["provider_verified"] is False
    assert _calls(world) == ["worker-show", "worker-list"]


def test_list_row_with_another_provider_refuses_even_when_show_has_none(world: OrcaWorld) -> None:
    _dispatch(world)
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
    assert set(got) == set(real)
    assert set(got["scope"]) == set(real["scope"])
    assert isinstance(got["nextCursor"], str) and isinstance(got["warnings"][0], str)
    row_keys = set().union(*(set(r) for r in real["workers"]))
    needed = set(real["workers"][1])
    assert needed <= set(got["workers"][0]) <= row_keys
    last = _fake("worker-list", "--json", "--cursor", got["nextCursor"])["result"]
    assert "nextCursor" not in last and "agent" not in last["workers"][0]
    for answer in (shown, released):
        assert set(answer) == {"ok", "result"} and answer["ok"] is True
        keys = set(answer["result"])
        assert set(REAL_SHOW_LIVE["result"]) - {"autoReleaseAt"} <= keys | {"waitingOnHuman"}
        assert keys <= set(REAL_SHOW_LIVE["result"]) | set(REAL_SHOW_RELEASED["result"])
        assert "agent" not in keys
        assert answer["result"]["dispatchId"] in ("D1", "D2")


def _fake(*args: str) -> dict:
    done = subprocess.run(["orca-fake", "orchestration", *args], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


@pytest.mark.parametrize(
    "answer",
    [
        {"workers": []},
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
        orca._result(REAL_SHOW_LIVE["result"], "worker-show")


def test_worker_list_scan_is_bounded_to_five_pages(world: OrcaWorld) -> None:
    _dispatch(world)
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
    _dispatch(world, "claude")
    setup(world, monkeypatch)
    before = world.snapshot()
    res = world.collect(1, "D1")
    assert res.code == 1, res.text
    assert expected in res.text
    assert world.snapshot() == before
    assert world.task().rounds == []


def test_collect_needs_a_dispatch_id_and_a_dispatched_round(world: OrcaWorld) -> None:
    _dispatch(world)
    assert world.run("round", TASK, "collect", "--round", "1").code == 2
    res = world.collect(7, "D1")
    assert res.code == 1 and "round 7 was not dispatched by the engine" in res.text


def test_dispatch_id_cannot_settle_two_rounds(world: OrcaWorld) -> None:
    assert _cycle(world, "claude").code == 0
    _dispatch(world, "claude", focus="b")
    world.finish(2, "D1")
    before = world.snapshot()
    for res in (
        world.collect(2, "D1"),
        world.abort(2, "--reason", "r", "--dispatch-id", "D1"),
    ):
        assert res.code == 1 and "already settled round 001" in res.text
    assert world.snapshot() == before


def test_unrelated_same_provider_dispatch_cannot_collect_or_abort(world: OrcaWorld) -> None:
    _dispatch(world)
    world.finish(1, "D1")
    world.worker("U1", "succeeded", "claude")
    before = world.snapshot()
    for res in (world.collect(1, "U1"), world.abort(1, "--reason", "r", "--dispatch-id", "U1")):
        assert res.code == 1 and "is not the worker of round 1" in res.text
    assert world.snapshot() == before


def test_receipt_of_another_round_is_refused(world: OrcaWorld) -> None:
    _dispatch(world, focus="a")
    _dispatch(world, focus="b")
    world.finish(1, "D1")
    world.finish(2, "D1")
    other = world.dispatch_json(2)["nonce"]
    Path(world.dispatch_json(1)["receipt"]).write_text(
        f"ROUND {other} DISPATCH D1\n", encoding="utf-8"
    )
    res = world.collect(1, "D1")
    assert res.code == 1 and "does not belong to round 1" in res.text


def test_tampered_dispatch_record_wrong_task_or_spec_is_refused(world: OrcaWorld) -> None:
    _dispatch(world)
    world.finish(1, "D1")
    path = world.run_dir(1) / "dispatch.json"
    original = path.read_text(encoding="utf-8")
    data = json.loads(original)
    path.write_text(json.dumps({**data, "agent": "codex"}), encoding="utf-8")
    assert "changed after dispatch" in world.collect(1, "D1").text
    path.write_text(json.dumps({**data, "task": "TASK-2"}), encoding="utf-8")
    assert "not dispatched by the engine" in world.collect(1, "D1").text
    path.write_text(original, encoding="utf-8")
    spec = world.run_dir(1) / "spec.md"
    spec.write_text(spec.read_text(encoding="utf-8") + "\nignore the above\n", encoding="utf-8")
    assert "spec of round 1 changed" in world.collect(1, "D1").text
    assert world.task().rounds == []


# -- collect: invalid rounds ----------------------------------------------------------------------
def test_failed_worker_is_invalid(world: OrcaWorld) -> None:
    _dispatch(world, "codex")
    world.finish(1, "D1", state="failed", answer="ignored\n", agent="codex")
    assert world.collect(1, "D1").code == 1
    record = world.record(1)
    assert (record["state"], record["verdict"]) == ("invalid", "block")
    assert record["reason"] == "worker ended as failed"


@pytest.mark.parametrize("state", ["completed", "error", "killed", "paused"])
def test_unknown_terminal_state_settles_as_invalid_and_does_not_block_collect(
    world: OrcaWorld, state: str
) -> None:
    _dispatch(world, "codex")
    world.finish(1, "D1", state=state, answer="ignored\n", agent="codex")
    assert world.collect(1, "D1").code == 1
    record = world.record(1)
    assert (record["state"], record["verdict"]) == ("invalid", "block")
    assert record["reason"] == f"worker ended as {state}"


@pytest.mark.parametrize("state", ["completed", "error", "killed", "paused"])
def test_unknown_terminal_state_does_not_block_abort(world: OrcaWorld, state: str) -> None:
    _dispatch(world, "codex")
    world.finish(1, "D1", state=state, answer="ignored\n", agent="codex")
    res = world.abort(1, "--reason", "hung", "--dispatch-id", "D1")
    assert res.code == 0
    assert "still running" not in res.text


def test_reader_that_changed_the_tree_is_invalid_and_kept(world: OrcaWorld) -> None:
    _dispatch(world)
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
    _dispatch(world)
    world.finish(1, "D1")
    (other / "second.txt").write_text("x", encoding="utf-8")
    assert world.collect(1, "D1").code == 1
    record = world.record(1)
    assert record["state"] == "invalid" and "second.txt" in str(record["reason"])
    assert str(other) in str(record["reason"])


def test_coordinator_commit_during_a_reader_round_invalidates_it(world: OrcaWorld) -> None:
    _dispatch(world)
    world.finish(1, "D1")
    (world.repo / "b.txt").write_text("b", encoding="utf-8")
    for args in (["add", "."], ["commit", "-qm", "more"]):
        subprocess.run(["git", *args], cwd=world.repo, check=True, capture_output=True)
    assert world.collect(1, "D1").code == 1
    assert "HEAD moved" in str(world.record(1)["reason"])


def test_vanished_repo_at_collect_is_invalid_not_a_traceback(world: OrcaWorld) -> None:
    import shutil

    _dispatch(world)
    world.finish(1, "D1")
    os.chdir(world.base)
    shutil.rmtree(world.repo)
    res = world.collect(1, "D1")
    assert res.code == 1 and "Traceback" not in res.text
    assert "bound repo not found" in str(world.record(1)["reason"])


# -- collect: idempotence, abort interplay --------------------------------------------------------
def test_collect_is_idempotent(world: OrcaWorld) -> None:
    assert _cycle(world).code == 0
    before, record = world.snapshot(), world.record(1)
    res = world.collect(1, "D1")
    assert res.code == 0 and "Round 001 was already collected (verdict info)" in res.text
    assert world.snapshot() == before and world.record(1) == record
    other = world.collect(1, "D2")
    assert other.code == 1 and "already collected with dispatch D1" in other.text


def test_abort_after_collect_is_refused(world: OrcaWorld) -> None:
    assert _cycle(world).code == 0
    before = world.snapshot()
    res = world.abort(1, "--reason", "r", "--dispatch-id", "D1")
    assert res.code == 1 and "already collected" in res.text
    assert world.snapshot() == before


def test_collect_after_abort_is_refused(world: OrcaWorld) -> None:
    _dispatch(world)
    assert world.abort(1, "--reason", "r", "--never-started").code == 0
    before = world.snapshot()
    res = world.collect(1, "D1")
    assert res.code == 1 and "was aborted" in res.text
    assert world.snapshot() == before


# -- abort ----------------------------------------------------------------------------------------
def test_abort_needs_reason_and_binding(world: OrcaWorld) -> None:
    _dispatch(world)
    world.finish(1, "D1")
    assert world.abort(1, "--dispatch-id", "D1").code == 2
    assert world.abort(1, "--reason", "r").code == 2
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
    assert "aborted-round TASK-1 001" in world.store.read_log(TASK)
    audit = [e for e in world.task().evidence if e["kind"] == "aborted-round"]
    assert len(audit) == 1 and audit[0]["n"] == 1 and audit[0]["reason"] == "stale run"


def test_never_started_is_an_audited_operator_assertion(
    world: OrcaWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    _dispatch(world)
    _dispatch(world, focus="b")
    monkeypatch.setenv("ORCA_CLI_COMMAND", "no-such-orca")
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
    _dispatch(world)
    world.finish(1, "D1")
    real_write, real_log = TaskStore._write, TaskStore._append_log_unlocked
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
    monkeypatch.setattr(TaskStore, "_append_log_unlocked", flaky_log)
    tail = ("--reason", "r", "--dispatch-id", "D1")
    assert world.abort(1, *tail).code == 1
    assert world.task().rounds == [] and world.task().evidence == []
    res = world.abort(1, *tail)
    assert res.code == 1 and "log lost" in res.text
    assert world.record(1)["settlement"] == "aborted" and len(world.task().evidence) == 1
    assert "aborted-round TASK-1 001" not in world.store.read_log(TASK)
    res = world.abort(1, *tail)
    assert res.code == 1 and "restored" in res.text
    assert world.abort(1, *tail).code == 1
    assert world.store.read_log(TASK).count("aborted-round TASK-1 001") == 1
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
    _dispatch(world, "codex")
    world.finish(1, "D1", answer="ok\nPOSITION: Final.\n", agent="codex")
    monkeypatch.setattr(TaskStore, "_write", _flaky_once(TaskStore._write, "disk full"))
    res = world.collect(1, "D1")
    assert res.code == 1 and "disk full" in res.text
    assert world.task().rounds == []
    round_path = Path(world.dispatch_json(1)["file"])
    assert round_path.exists() and round_path.read_text(encoding="utf-8") == ""
    assert world.collect(1, "D1").code == 0
    record = world.record(1)
    settled_text = Path(str(record["file"])).read_text(encoding="utf-8")
    assert "- Dispatch: D1" in settled_text and "- Verdict: info (valid)" in settled_text
    assert "## Answer\n\nok\nPOSITION: Final." in settled_text
    assert record["verdict"] == "info"


def test_crash_after_record_before_index_collect_reports_already_collected(
    world: OrcaWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    _dispatch(world, "codex")
    world.finish(1, "D1", answer="ok\nPOSITION: Final.\n", agent="codex")
    monkeypatch.setattr(
        store_module, "render_index", _flaky_once(store_module.render_index, "no index")
    )
    assert world.collect(1, "D1").code == 1
    record = world.record(1)
    text = Path(str(record["file"])).read_text(encoding="utf-8")
    assert record["verdict"] == "info" and "Verdict: info" in text
    res = world.collect(1, "D1")
    assert res.code == 0 and "already collected" in res.text


def test_concurrent_collect_and_abort(world: OrcaWorld) -> None:
    _dispatch(world)
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
    _dispatch(world)
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
    _dispatch(world, focus="a")
    _dispatch(world, focus="b")
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
    "stamp-nested": (
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
    assert _cycle(world).code == 0
    evidence = tmp_path / "checks.txt"
    evidence.write_text("passed", encoding="utf-8")
    approval = {"action": "plan", "target": TASK, "user_reply": "ok", "stamp": "", "at": "x"}
    entry = {"kind": "checks", "repo": "r", "path": str(evidence)}

    def add_records(task: Task) -> None:
        task.approvals.append(approval)
        task.evidence.append(entry)

    world.store.mutate(TASK, add_records)
    _dispatch(world, "codex", focus="b")
    world.finish(2, "D2", answer="ok\nPOSITION: Done.\n", agent="codex")
    mutate, expected = CONTROL_CASES[case]
    mutate(world, evidence)
    before = world.snapshot()
    res = world.collect(2, "D2")
    assert res.code == 1 and "control files changed" in res.text and expected in res.text
    assert world.snapshot() == before
    assert len(world.task().rounds) <= 1


def test_modified_dispatch_metadata_is_detected_by_its_seal(world: OrcaWorld) -> None:
    _dispatch(world)
    world.finish(1, "D1")
    path = world.run_dir(1) / "dispatch.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["control"]["stamp_key"] = "forged"
    path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    res = world.collect(1, "D1")
    assert res.code == 1 and "changed after dispatch" in res.text


def test_legitimate_concurrent_engine_writes_do_not_trip_the_control_check(
    world: OrcaWorld,
) -> None:
    _dispatch(world, focus="a")
    _dispatch(world, focus="b")
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
    assert _cycle(world).code == 0
    _dispatch(world, focus="b")
    world.finish(2, "D2")
    earlier = Path(str(world.record(1)["file"]))
    earlier.write_text(earlier.read_text(encoding="utf-8") + "x", encoding="utf-8")
    res = world.collect(2, "D2")
    assert res.code == 1 and "round file" in res.text
    world.assert_hermetic()


# -- harness and compatibility --------------------------------------------------------------------
def test_fake_orca_receives_only_worker_show_and_worker_list(world: OrcaWorld) -> None:
    assert _cycle(world).code == 0
    calls = world.orca_calls()
    assert calls and all(call[1] in ("worker-show", "worker-list") for call in calls)
    with pytest.raises(OrcaError, match="refused"):
        _run(["orchestration", "worker-start", "--spec-file", "x"])
    assert world.orca_calls() == calls
    stray = subprocess.run(["orca-fake", "orchestration", "worker-stop"], capture_output=True)
    assert stray.returncode == 3
    world.orca_log.write_text("", encoding="utf-8")
    world.assert_hermetic()


def test_parser_needs_no_role_for_collect_and_abort() -> None:
    parser = build_parser()
    args = parser.parse_args(["round", TASK, "collect", "--round", "1", "--dispatch-id", "D"])
    assert args.action == "collect" and not hasattr(args, "role")
    with pytest.raises(SystemExit):
        parser.parse_args(
            ["round", TASK, "collect", "--round", "1", "--dispatch-id", "D", "--role", "x"]
        )
    for gone in ("run", "dispatch", "record", "start", "finish"):
        with pytest.raises(SystemExit):
            parser.parse_args(["round", TASK, gone])


def test_guide_documents_collect_and_abort() -> None:
    for verb in ("round <ID> collect", "round <ID> abort", "--never-started"):
        assert verb in GUIDE


# -- cross-examination, launch receipt and scratch -------------------------------------------------
def _receipt(dispatch_id: str, agent: str, model: str) -> dict[str, object]:
    """The shape of a real ``worker-start --json`` receipt (Orca 1.4.256, captured)."""
    result = {"dispatchId": dispatch_id, "taskId": "task_1", "runId": "run_1", "state": "ready"}
    result |= {"agent": agent, "model": model, "effort": "medium", "mode": "terminal"}
    return {"ok": True, "result": result}


def _launch(world: OrcaWorld, n: int, agent: str, model: str) -> None:
    _write_launch(world, n, _receipt("D1", agent, model))


def _write_launch(world: OrcaWorld, n: int, receipt: dict[str, object]) -> None:
    Path(world.dispatch_json(n)["launch"]).write_text(json.dumps(receipt), encoding="utf-8")


def test_printed_line_saves_the_launch_receipt(world: OrcaWorld) -> None:
    made = _dispatch(world, "claude")
    assert "--json" in made.argv
    launch = str(world.run_dir(1) / "launch.json")
    assert shlex.split(made.line())[-2:] == [">", launch]
    assert world.dispatch_json(1)["launch"] == launch


def test_rebuttal_round_cross_examines_settled_rounds(world: OrcaWorld) -> None:
    assert _cycle(world, "claude").code == 0
    first = str(world.record(1)["file"])
    made = _dispatch(world, "claude", "cross", rebuts=(1,))
    spec = (world.run_dir(made.n) / "spec.md").read_text(encoding="utf-8")
    assert "Cross-examination" in spec and f"round 001 (claude): {first}" in spec
    assert world.dispatch_json(made.n)["rebuts"] == [1]
    world.finish(made.n, f"D{made.n}")
    assert world.collect(made.n, f"D{made.n}").code == 0
    record = world.record(made.n)
    assert record["rebuts"] == [1]
    assert "Cross-examines rounds: 001" in Path(str(record["file"])).read_text(encoding="utf-8")


def test_rebut_refuses_unknown_and_invalid_rounds(world: OrcaWorld) -> None:
    with pytest.raises(DispatchError, match="round 007 is not settled"):
        _dispatch(world, "claude", rebuts=(7,))
    assert not (world.store.task_dir(TASK) / "runs").exists()
    _dispatch(world, "codex")
    world.finish(1, "D1", state="failed", agent="codex")
    assert world.collect(1, "D1").code == 1
    with pytest.raises(DispatchError, match="is invalid and cannot be cross-examined"):
        _dispatch(world, "claude", rebuts=(1,))
    world.store.mutate(
        TASK, lambda t: t.rounds.append({"n": 2, "agent": "codex", "state": "valid"})
    )
    with pytest.raises(DispatchError, match="has no recorded round file"):
        _dispatch(world, "claude", rebuts=(2,))


def test_launch_receipt_with_another_model_refuses_collect(world: OrcaWorld) -> None:
    _dispatch(world, "claude", model="opus")
    world.finish(1, "D1", agent=None)
    _launch(world, 1, "claude", "sonnet")
    refused = world.collect(1, "D1")
    assert refused.code == 1 and "on model 'sonnet', not on the dispatched 'opus'" in refused.text
    assert world.task().rounds == []
    _launch(world, 1, "codex", "opus")
    assert "not as the dispatched provider 'claude'" in world.collect(1, "D1").text
    _write_launch(world, 1, _receipt("OTHER", "claude", "opus"))
    assert "belongs to dispatch OTHER, not D1" in world.collect(1, "D1").text
    assert world.task().rounds == []
    _launch(world, 1, "claude", "opus")
    assert world.collect(1, "D1").code == 0
    assert world.record(1)["launch_verified"] is True


def test_partial_launch_evidence_stays_unverified(world: OrcaWorld) -> None:
    _dispatch(world, "claude", model="opus")
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
    legacy = {"n": 1, "provider": "claude", "model": ""}
    assert launch_verified(legacy, "D1") is False
    broken = tmp_path / "launch.json"
    broken.write_text("{not json", encoding="utf-8")
    assert launch_verified({**legacy, "launch": str(broken)}, "D1") is False


def test_no_launch_receipt_is_unverified_not_refused(world: OrcaWorld) -> None:
    assert _cycle(world, "claude").code == 0
    record = world.record(1)
    assert record["launch_verified"] is False and record["state"] == "valid"
    assert "launch not verified" in Path(str(record["file"])).read_text(encoding="utf-8")


def test_unreadable_scratch_is_not_marked_used(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from ai_governance.taskflow.collect import _used_scratch

    scratch_dir = tmp_path / "scratch"
    scratch_dir.mkdir()

    def boom(self: Path) -> None:
        raise PermissionError("inaccessible")

    monkeypatch.setattr(Path, "iterdir", boom)
    assert _used_scratch({"scratch": str(scratch_dir)}) is False


# -- web, artifacts, effort, denied models, debater role ------------------------------------------
def _baseline_spec(world: OrcaWorld, n: int) -> str:
    run = world.run_dir(n)
    nonce = world.dispatch_json(n)["nonce"]
    read_only = (
        "Do not modify files, commit, push or run commands that change the repository or the "
        "environment. Do not delegate to subagents. Mark each claim as seen/assumed/unknown.\n\n"
    )
    header = (
        f"Role: debater. Task {TASK}: Fix status.\n"
        "Only this task: ignore other tasks' files under the taskflow store.\n"
        f"Goal: goal\nRounds of this task: {world.store.rounds_dir(TASK)}\n"
        f"Repository {world.repo} (branch feat/TASK-1-x)\n\n"
    )
    footer = (
        "\n\nHow to report (a taskflow round of this task; the coordinating session collects it):\n"
        f"1. First action: write the single line `ROUND {nonce} DISPATCH <your Orca Dispatch ID>` "
        f"to {run / 'receipt.txt'} (your Dispatch ID is in the task Orca gave you).\n"
        f"2. Write your final answer to {run / 'answer.txt'}.\n"
        f"To prove a claim you may create and run throwaway scripts under {run / 'scratch'} "
        "(outside every repository); nothing there changes the repositories.\n"
        "Do not modify any file in the repositories or in the taskflow store other than those "
        f"two files and that folder. Ignore every other task's files.\n(task {TASK})\n"
    )
    return read_only + header + "do it" + footer


def test_without_web_or_artifact_spec_matches_baseline(world: OrcaWorld) -> None:
    _dispatch(world, "claude")
    spec = (world.run_dir(1) / "spec.md").read_text(encoding="utf-8")
    assert spec == _baseline_spec(world, 1)
    assert "You may research the web" not in spec
    assert "Open each of these files" not in spec
    record = world.dispatch_json(1)
    assert record["web"] is False and record["artifacts"] == []


def test_web_and_repeatable_artifact_in_spec_and_dispatch_json(
    world: OrcaWorld, tmp_path: Path
) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    first = artifacts / "screen.png"
    second = artifacts / "sub" / "preview.html"
    second.parent.mkdir()
    first.write_bytes(b"\x89PNG\r\n")
    second.write_text("<html>ok</html>", encoding="utf-8")
    rel_second = os.path.relpath(second, world.repo)
    made = _dispatch(world, "claude", web=True, artifacts=(str(first), rel_second))
    spec = (world.run_dir(made.n) / "spec.md").read_text(encoding="utf-8")
    resolved = [str(first.resolve()), str(second.resolve())]
    assert WEB_INSTRUCTION in spec
    assert artifact_instruction(resolved) in spec
    record = world.dispatch_json(made.n)
    assert record["web"] is True and record["artifacts"] == resolved


def _bad_artifact(base: Path, kind: str) -> tuple[Path, Path | None]:
    if kind == "missing":
        return base / "missing.png", None
    if kind == "directory":
        folder = base / "dir"
        folder.mkdir()
        return folder, None
    if kind == "dangling":
        link = base / "dangling.png"
        link.symlink_to(base / "nowhere.png")
        return link, None
    secret = base / "unreadable.png"
    secret.write_bytes(b"data")
    secret.chmod(0)
    return secret, secret


@pytest.mark.parametrize("kind", ["missing", "directory", "dangling", "unreadable"])
def test_invalid_artifact_refused_without_reserving_round(
    world: OrcaWorld, tmp_path: Path, kind: str
) -> None:
    target, restore = _bad_artifact(tmp_path, kind)
    try:
        with pytest.raises(DispatchError, match="artifact not found or unreadable"):
            _dispatch(world, "claude", artifacts=(str(target),))
    finally:
        if restore is not None:
            restore.chmod(0o600)
    assert not (world.store.task_dir(TASK) / "runs").exists()
    assert not list(world.store.rounds_dir(TASK).glob("[0-9]*.md"))
    assert not (world.store.root / "seals").exists()


def test_role_effort_reaches_worker_start_argv_after_model(
    world: OrcaWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    plain = _dispatch(world, "codex")
    assert "--effort" not in plain.argv
    assert world.dispatch_json(plain.n)["effort"] == ""

    monkeypatch.setenv("AI_GOVERNANCE_DEBATER_EFFORT", "medium")
    deb = _dispatch(world, "codex", focus="d2")
    assert deb.argv.index("--effort") == deb.argv.index("--model") + 2
    assert flag(deb.argv, "--effort") == "medium"
    assert world.dispatch_json(2)["effort"] == "medium"

    monkeypatch.setenv("AI_GOVERNANCE_DEBATER_EFFORT", "high")
    explicit = _dispatch(world, "codex", focus="d3", model="gpt-6.1-sol")
    assert explicit.argv.index("--effort") == explicit.argv.index("--model") + 2
    assert flag(explicit.argv, "--effort") == "high"


def test_role_effort_without_model_is_refused_and_works_with_model(
    world: OrcaWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AI_GOVERNANCE_DEBATER_EFFORT", "high")
    with pytest.raises(DispatchError, match="effort requires a model"):
        _dispatch(world, "claude")
    assert not (world.store.task_dir(TASK) / "runs").exists()

    with_model = _dispatch(world, "claude", model="claude-sonnet-4")
    assert with_model.argv.index("--effort") == with_model.argv.index("--model") + 2
    assert flag(with_model.argv, "--effort") == "high"
    assert world.dispatch_json(1)["effort"] == "high"


def test_denied_models_refused_at_dispatch_explicit_and_default(
    world: OrcaWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AI_GOVERNANCE_DENIED_MODELS", "gpt-6.1-sol,blocked-claude")
    with pytest.raises(DispatchError, match="taskflow.denied_models"):
        _dispatch(world, "claude", model="blocked-claude")
    with pytest.raises(DispatchError, match="taskflow.denied_models"):
        _dispatch(world, "claude")
    with pytest.raises(DispatchError, match="taskflow.denied_models"):
        _dispatch(world, "codex")
    assert not (world.store.task_dir(TASK) / "runs").exists()
    assert not (world.store.root / "seals").exists()


def test_collect_refuses_denied_effective_model_in_launch_receipt(
    world: OrcaWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AI_GOVERNANCE_DENIED_MODELS", "forbidden-model")
    _dispatch(world, "claude", focus="a", model="claude-sonnet-4")
    world.finish(1, "D1")
    receipt = {
        "ok": True,
        "result": {
            "dispatchId": "D1",
            "launch": {"effective": {"agent": "claude", "model": "anthropic/FORBIDDEN-MODEL"}},
        },
    }
    _write_launch(world, 1, receipt)
    before = world.snapshot()
    refused = world.collect(1, "D1")
    assert refused.code == 1 and "taskflow.denied_models" in refused.text
    assert world.snapshot() == before and world.task().rounds == []

    monkeypatch.delenv("AI_GOVERNANCE_DENIED_MODELS")
    _dispatch(world, "codex", focus="b")
    world.finish(2, "D2", answer="ok\nPOSITION: Done.\n", agent="codex")
    _write_launch(world, 2, _receipt("D2", "codex", "gpt-6.1-sol"))
    monkeypatch.setenv("AI_GOVERNANCE_DENIED_MODELS", "gpt-6.1-sol")
    before_two = world.snapshot()
    late = world.collect(2, "D2")
    assert late.code == 1 and "taskflow.denied_models" in late.text
    assert world.snapshot() == before_two and world.task().rounds == []


def test_collect_refuses_denied_or_corrupt_launch_without_dispatch_id(
    world: OrcaWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AI_GOVERNANCE_DENIED_MODELS", "forbidden-model")
    _dispatch(world, "claude", focus="a", model="claude-sonnet-4")
    world.finish(1, "D1")
    launch = Path(world.dispatch_json(1)["launch"])
    before_missing = world.snapshot()
    missing = world.collect(1, "D1")
    assert missing.code == 1 and "has no verified model in launch receipt" in missing.text
    assert world.snapshot() == before_missing and world.task().rounds == []

    partials = [
        {"ok": False, "result": {"launch": {"effective": {"model": "anthropic/FORBIDDEN-MODEL"}}}},
        {"ok": True, "result": {"launch": {"effective": {"model": "forbidden-model"}}}},
    ]
    for payload in partials:
        _write_launch(world, 1, payload)
        before = world.snapshot()
        res = world.collect(1, "D1")
        assert res.code == 1 and "taskflow.denied_models" in res.text
        assert world.snapshot() == before and world.task().rounds == []

    launch.write_text("{corrupt", encoding="utf-8")
    before = world.snapshot()
    corrupt = world.collect(1, "D1")
    assert corrupt.code == 1 and "while taskflow.denied_models is active" in corrupt.text
    assert world.snapshot() == before and world.task().rounds == []


def test_collect_refuses_unverified_allowed_model_and_fifo_when_denied_active(
    world: OrcaWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AI_GOVERNANCE_DENIED_MODELS", "forbidden-model")
    _dispatch(world, "claude", focus="a", model="claude-sonnet-4")
    world.finish(1, "D1")
    launch = Path(world.dispatch_json(1)["launch"])
    unverified = [
        {
            "ok": False,
            "result": {"dispatchId": "D1", "agent": "claude", "model": "claude-sonnet-4"},
        },
        {"ok": True, "result": {"agent": "claude", "model": "claude-sonnet-4"}},
    ]
    for payload in unverified:
        _write_launch(world, 1, payload)
        res = world.collect(1, "D1")
        assert res.code == 1
        assert "has no verified model in launch receipt" in res.text

    launch.unlink(missing_ok=True)
    os.mkfifo(launch)
    try:
        fifo = world.collect(1, "D1")
        assert fifo.code == 1
        assert "while taskflow.denied_models is active" in fifo.text
        assert world.task().rounds == []
    finally:
        launch.unlink(missing_ok=True)


def test_debater_dispatch_and_collect_on_manual_task(world: OrcaWorld) -> None:
    deb = _dispatch(world, "claude")
    world.finish(
        deb.n, f"D{deb.n}", answer="Checked store.\nPOSITION: Keep rounds flat.\n", agent="claude"
    )
    assert world.collect(deb.n, f"D{deb.n}").code == 0
    rec = world.record(deb.n)
    assert (rec["role"], rec["state"], rec["verdict"]) == ("debater", "valid", "info")
    assert rec["position"] == "Keep rounds flat."
    assert "- Position: Keep rounds flat." in Path(str(rec["file"])).read_text(encoding="utf-8")

    assert world.run("new", "MAN-1", "--title", "Manual", "--workflow", "manual").code == 0
    assert world.run("bind", "MAN-1", "--repo", str(world.repo)).code == 0
    world.task_id = "MAN-1"
    man_deb = _dispatch(world, "codex")
    world.finish(
        man_deb.n, "DM1", answer="Manual analysis.\nPOSITION: Stay manual.\n", agent="codex"
    )
    assert world.collect(man_deb.n, "DM1").code == 0
    assert world.record(man_deb.n)["position"] == "Stay manual."


def test_collect_ignores_non_dict_launch_json_when_no_denied_models(world: OrcaWorld) -> None:
    _dispatch(world, "claude", focus="a", model="claude-sonnet-4")
    world.finish(1, "D1")
    Path(world.dispatch_json(1)["launch"]).write_text("[1, 2]", encoding="utf-8")
    res = world.collect(1, "D1")
    assert res.code == 0
    assert world.record(1)["launch_verified"] is False


def test_collect_rechecks_drift_under_lock_before_writing(
    world: OrcaWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ai_governance.taskflow import collect as collect_mod

    _dispatch(world, "codex")
    world.finish(1, "D1", answer="ok\nPOSITION: Final.\n", agent="codex")
    real_launch = collect_mod.launch_verified

    def tamper_mid_collect(found: dict[str, object], dispatch_id: str) -> bool:
        world.edit_state(lambda data: data["code_stamp"].update(key="tampered"))
        return real_launch(found, dispatch_id)

    monkeypatch.setattr(collect_mod, "launch_verified", tamper_mid_collect)
    with pytest.raises(DispatchError, match="control files changed"):
        collect_round(world.store, RoundRef(TASK, 1), "D1")
    assert world.task().rounds == []
    assert Path(world.dispatch_json(1)["file"]).read_text(encoding="utf-8") == ""


def test_write_settled_rolls_back_missing_prior_and_preserves_save_error(
    world: OrcaWorld, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from ai_governance.taskflow import collect as collect_mod

    def fail_write(*_args: object) -> object:
        raise OSError("disk full")

    monkeypatch.setattr(TaskStore, "_write", fail_write)

    absent = tmp_path / "absent.md"
    rec = {"n": 9, "file": str(absent), "session": "D9"}
    with pytest.raises(OSError, match="disk full"):
        collect_mod._write_settled(world.store, TASK, collect_mod._Settlement(rec, "new"))
    assert not absent.exists()

    existing = tmp_path / "existing.md"
    existing.write_text("prior", encoding="utf-8")
    rec_prev = {"n": 10, "file": str(existing), "session": "D10"}
    with pytest.raises(OSError, match="disk full"):
        collect_mod._write_settled(world.store, TASK, collect_mod._Settlement(rec_prev, "new"))
    assert existing.read_text(encoding="utf-8") == "prior"

    monkeypatch.setattr(
        collect_mod, "_restore_text", lambda *_a: (_ for _ in ()).throw(OSError("cleanup"))
    )
    with pytest.raises(OSError, match="disk full"):
        collect_mod._write_settled(world.store, TASK, collect_mod._Settlement(rec_prev, "new"))
