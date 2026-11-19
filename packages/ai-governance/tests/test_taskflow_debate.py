"""Design debate mode: thesis, cross-examination, synthesis, web/artifacts, effort and denied models."""

# ruff: noqa: F401, F811
from __future__ import annotations

import argparse
import json
import os
import shutil
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import pytest
from ai_governance.taskflow import debate, debate_cli
from ai_governance.taskflow.config import load_config
from ai_governance.taskflow.control import DispatchError, UsageRefusal
from ai_governance.taskflow.debate import (
    TOPIC_MAX_BYTES,
    OpenDebateOptions,
    assign_seats,
    debate_path,
    load_debate,
    open_debate,
)
from ai_governance.taskflow.prompts import (
    CROSS_INSTRUCTION,
    THESIS_INSTRUCTION,
    WEB_INSTRUCTION,
    answer_section,
    artifact_instruction,
    parse_rebuts,
)
from ai_governance.taskflow.synthesis import STEP_MAX_CHARS, SYNTHESIS_FILE
from orca_fakes import TASK, OrcaWorld, Result, flag, world


@dataclass(frozen=True)
class _AnswerSpec:
    agent: str
    text: str
    answer_file: Path | None = None
    state: str = "succeeded"


def _topic(tmp_path: Path, text: str = "Choose session store: Redis vs SQLite.\n") -> Path:
    path = tmp_path / "topic.md"
    path.write_text(text, encoding="utf-8")
    return path


def _round_no(line: list[str]) -> int:
    return int(flag(line, "--task-title").split()[2])


def _open_debate(
    world: OrcaWorld, topic: Path, agents: str = "claude,codex,claude", extra: Sequence[str] = ()
) -> list[list[str]]:
    res = world.run(
        "debate", world.task_id, "open", "--topic-file", str(topic), "--agents", agents, *extra
    )
    assert res.code == 0, res.text
    return world.worker_lines(res)


def _settle(world: OrcaWorld, n: int, did: str, spec: _AnswerSpec) -> Result:
    if spec.answer_file is not None:
        spec.answer_file.write_text(spec.text, encoding="utf-8")
    raw_answer = None if (spec.answer_file is not None or spec.state != "succeeded") else spec.text
    world.finish(n, did, answer=raw_answer, agent=spec.agent, state=spec.state)
    extra = ("--answer-file", str(spec.answer_file)) if spec.answer_file is not None else ()
    return world.collect(n, did, *extra)


def _check_clean_store(world: OrcaWorld, task_id: str = TASK) -> None:
    tdir = world.store.task_dir(task_id)
    assert not debate_path(world.store, task_id).exists()
    assert not list((tdir / "runs").glob("*"))
    assert not list(world.store.rounds_dir(task_id).glob("[0-9]*.md"))
    assert not list((world.store.root / "seals").glob("*"))


def _section(text: str, heading: str) -> str:
    marker = f"## {heading}\n"
    start = text.index(marker) + len(marker)
    end = text.find("\n## ", start)
    return text[start:] if end == -1 else text[start:end]


def _bad_topic(tmp_path: Path, kind: str) -> Path:
    path = tmp_path / f"{kind}.md"
    if kind == "empty":
        path.write_text("  \n\t\n", encoding="utf-8")
    elif kind == "binary":
        path.write_bytes(b"\xff\xfe\x00\x80")
    elif kind == "oversized":
        path.write_text("x" * (TOPIC_MAX_BYTES + 1), encoding="utf-8")
    return path


def _bad_artifact(tmp_path: Path, kind: str) -> Path:
    if kind == "missing":
        return tmp_path / "missing.png"
    if kind == "directory":
        folder = tmp_path / "artifact-dir"
        folder.mkdir()
        return folder
    link = tmp_path / "dangling.png"
    link.symlink_to(tmp_path / "nowhere.png")
    return link


def _new_bound_task(world: OrcaWorld, task_id: str, workflow: str = "tri-agent") -> None:
    assert world.run("new", task_id, "--title", f"Task {task_id}", "--workflow", workflow).code == 0
    assert world.run("bind", task_id, "--repo", str(world.repo)).code == 0


def _write_toml(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def _run_two_seat_debate(
    world: OrcaWorld, topic: Path, cross1: str, cross2: str = "POSITION: Done.\n"
) -> None:
    _open_debate(world, topic, "claude,codex")
    seats = load_debate(world.store, world.task_id)["seats"]
    for seat in seats:
        n = int(seat["thesis_round"])
        assert (
            _settle(world, n, f"D{n}", _AnswerSpec(seat["agent"], f"T{n}.\nPOSITION: P{n}.\n")).code
            == 0
        )
    assert world.run("debate", world.task_id, "cross").code == 0
    seats = load_debate(world.store, world.task_id)["seats"]
    for seat, body in zip(seats, (cross1, cross2), strict=True):
        n = int(seat["cross_round"])
        assert _settle(world, n, f"D{n}", _AnswerSpec(seat["agent"], body)).code == 0
    assert world.run("debate", world.task_id, "close").code == 0


# -- Delivery 1: open, cross, status, debater collect ------------------------------------------


def _check_thesis_spec(world: OrcaWorld, n: int, focus: str, topic_snippet: str) -> None:
    spec = (world.run_dir(n) / "spec.md").read_text(encoding="utf-8")
    record = world.dispatch_json(n)
    assert record["focus"] == focus
    assert THESIS_INSTRUCTION in spec
    assert str(world.run_dir(n) / "scratch") in spec
    assert record["nonce"] in spec
    assert topic_snippet in spec


def _seed_prior_round(world: OrcaWorld, n: int = 1, role: str = "planner") -> Path:
    path = world.store.rounds_dir(world.task_id) / f"{n:03d}-work-{role}-claude.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# Round\n\nPrior notes.\n", encoding="utf-8")
    world.store.mutate(
        world.task_id,
        lambda t: t.rounds.append(
            {
                "n": n,
                "phase": "work",
                "role": role,
                "focus": "",
                "agent": "claude",
                "model": "",
                "stamp": t.stamp_key,
                "file": str(path),
                "state": "valid",
                "verdict": "info",
                "source": "engine",
            }
        ),
    )
    return path


def test_open_three_seats_writes_specs_lines_debate_json_and_manual_task(
    world: OrcaWorld, tmp_path: Path
) -> None:
    topic = _topic(tmp_path, "Compare Redis vs SQLite for sessions.\n")
    res = world.run(
        "debate", TASK, "open", "--topic-file", str(topic), "--agents", "claude,codex,claude"
    )
    assert res.code == 0, res.text
    assert len(world.worker_lines(res)) == 3
    assert len(res.out.strip().splitlines()) == 3
    assert "Debate #1 opened" in res.err
    assert f"taskflow debate {TASK} cross" in res.err

    state = load_debate(world.store, TASK)
    assert state is not None
    assert (state["debate_id"], state["status"]) == (1, "open")
    assert [s["focus"] for s in state["seats"]] == ["claude", "codex", "claude-2"]
    assert [s["agent"] for s in state["seats"]] == ["claude", "codex", "claude"]
    assert [s["thesis_round"] for s in state["seats"]] == [1, 2, 3]
    assert [s["cross_round"] for s in state["seats"]] == [None, None, None]
    assert world.task().rounds == []

    for n, focus in ((1, "claude"), (2, "codex"), (3, "claude-2")):
        _check_thesis_spec(world, n, focus, "Compare Redis vs SQLite for sessions.")

    _new_bound_task(world, "MAN-1", workflow="manual")
    world.task_id = "MAN-1"
    assert len(_open_debate(world, topic, "claude,codex")) == 2


@pytest.mark.parametrize(
    ("args", "needle"),
    [
        (["--agents", "codex,codex"], "at least 2 distinct providers"),
        (["--agents", "codex"], "at least 2 seats"),
        (["--agents", "claude,nope"], "not allowed here"),
        (["--agents", "claude,human"], "human cannot run"),
        (["--agents", "claude,codex", "--model", "antigravity=m"], "unknown --model target"),
        (["--agents", "claude,codex", "--model", "codex"], "invalid --model"),
        (["--agents", "claude,codex", "--model", "=gpt"], "invalid --model"),
        (["--agents", "claude,codex", "--model", "codex="], "invalid --model"),
    ],
)
def test_open_refuses_invalid_seats_and_models_atomically(
    world: OrcaWorld, tmp_path: Path, args: list[str], needle: str
) -> None:
    topic = _topic(tmp_path)
    res = world.run("debate", TASK, "open", "--topic-file", str(topic), *args)
    assert res.code == 1 and needle in res.text
    _check_clean_store(world)


@pytest.mark.parametrize("kind", ["missing", "empty", "binary", "oversized"])
def test_open_refuses_bad_topic_files(world: OrcaWorld, tmp_path: Path, kind: str) -> None:
    path = _bad_topic(tmp_path, kind)
    res = world.run("debate", TASK, "open", "--topic-file", str(path), "--agents", "claude,codex")
    assert res.code == 1
    _check_clean_store(world)


def test_open_refuses_second_open_while_debate_open(world: OrcaWorld, tmp_path: Path) -> None:
    topic = _topic(tmp_path)
    _open_debate(world, topic, "claude,codex")
    before = world.snapshot()
    again = world.run(
        "debate", TASK, "open", "--topic-file", str(topic), "--agents", "claude,codex"
    )
    assert again.code == 1 and "already has an open debate" in again.text
    assert world.snapshot() == before


@pytest.mark.parametrize(
    ("payload", "needle"),
    [
        ('{"debate_id": 1, "status": "paused", "seats": []}', "unsupported status 'paused'"),
        ('{"debate_id": 1, "status": "corrupt", "seats": []}', "unsupported status 'corrupt'"),
        ("{not valid json", "cannot read"),
    ],
)
def test_open_fails_closed_on_unexpected_or_corrupt_debate_state(
    world: OrcaWorld, tmp_path: Path, payload: str, needle: str
) -> None:
    topic = _topic(tmp_path)
    dpath = debate_path(world.store, TASK)
    dpath.parent.mkdir(parents=True, exist_ok=True)
    dpath.write_text(payload, encoding="utf-8")
    res = world.run("debate", TASK, "open", "--topic-file", str(topic), "--agents", "claude,codex")
    assert res.code == 1 and needle in res.text
    assert dpath.read_text(encoding="utf-8") == payload
    assert not list((world.store.task_dir(TASK) / "runs").glob("*"))


def test_open_rolls_back_atomically_on_mid_dispatch_failure(
    world: OrcaWorld, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    topic = _topic(tmp_path)
    real_plan = debate.plan_dispatch
    calls = [0]

    def fail_second(store, task, config, request):  # type: ignore[no-untyped-def]
        calls[0] += 1
        if calls[0] == 2:
            raise DispatchError("simulated failure on seat 2")
        return real_plan(store, task, config, request)

    monkeypatch.setattr(debate, "plan_dispatch", fail_second)
    res = world.run("debate", TASK, "open", "--topic-file", str(topic), "--agents", "claude,codex")
    assert calls[0] == 2 and res.code == 1 and "simulated failure" in res.text
    _check_clean_store(world)


def test_concurrent_open_debate_leaves_one_open_debate_and_clean_rounds(
    world: OrcaWorld, tmp_path: Path
) -> None:
    topic = _topic(tmp_path)
    cmd = ["debate", TASK, "open", "--topic-file", str(topic), "--agents", "claude,codex"]
    results = world.race(cmd, cmd)
    assert sorted(code for code, _ in results) == [0, 1], results
    state = load_debate(world.store, TASK)
    assert state is not None and (state["debate_id"], state["status"]) == (1, "open")
    assert [int(s["thesis_round"]) for s in state["seats"]] == [1, 2]
    assert sorted(p.name for p in (world.store.task_dir(TASK) / "runs").iterdir()) == ["001", "002"]
    assert len(list(world.store.rounds_dir(TASK).glob("[0-9]*.md"))) == 2


def _check_cross_spec(world: OrcaWorld, cross_n: int, own_n: int, others: tuple[int, ...]) -> None:
    spec = (world.run_dir(cross_n) / "spec.md").read_text(encoding="utf-8")
    assert str(world.record(own_n)["file"]) not in spec
    block_start = spec.index("Cross-examination:")
    instr_start = spec.index(CROSS_INSTRUCTION.strip())
    assert block_start < instr_start
    for other in others:
        other_file = str(world.record(other)["file"])
        assert block_start < spec.index(other_file) < instr_start


def test_cross_waits_for_theses_excludes_own_round_and_places_instruction_after_block(
    world: OrcaWorld, tmp_path: Path
) -> None:
    _seed_prior_round(world)
    _open_debate(world, _topic(tmp_path), "claude,codex,claude")
    assert world.run("debate", TASK, "cross").code == 1

    body2 = "Thesis A.\nPOSITION: <one sentence>\nPOSITION: Use Redis.\n"
    s2 = _AnswerSpec("claude", body2, tmp_path / "a2.txt")
    s3 = _AnswerSpec("codex", "T.\nPOSITION: SQLite.\n", tmp_path / "a3.txt")
    s4 = _AnswerSpec("claude", "T.\nPOSITION: Hybrid.\n", tmp_path / "a4.txt")
    assert _settle(world, 2, "D2", s2).code == 0
    assert _settle(world, 3, "D3", s3).code == 0
    still_pending = world.run("debate", TASK, "cross")
    assert still_pending.code == 1 and "004" in still_pending.text
    assert _settle(world, 4, "D4", s4).code == 0

    rec2 = world.record(2)
    assert (rec2["state"], rec2["verdict"], rec2["position"]) == ("valid", "info", "Use Redis.")
    assert rec2["answer_transport"] == "answer_file"
    assert not (world.run_dir(2) / "answer.txt").exists()
    assert "- Position: Use Redis." in Path(str(rec2["file"])).read_text(encoding="utf-8")

    cross_res = world.run("debate", TASK, "cross")
    assert cross_res.code == 0, cross_res.text
    assert [_round_no(line) for line in world.worker_lines(cross_res)] == [5, 6, 7]
    for cross_n, own_n, others in ((5, 2, (3, 4)), (6, 3, (2, 4)), (7, 4, (2, 3))):
        _check_cross_spec(world, cross_n, own_n, others)


def test_cross_drops_invalid_repeated_seat_with_warning_and_continues(
    world: OrcaWorld, tmp_path: Path
) -> None:
    _open_debate(world, _topic(tmp_path), "claude,codex,claude")
    assert _settle(world, 1, "D1", _AnswerSpec("claude", "A.\nPOSITION: A.\n")).code == 0
    assert _settle(world, 2, "D2", _AnswerSpec("codex", "B.\nPOSITION: B.\n")).code == 0
    (world.repo / "app.py").write_text("x = 2\n", encoding="utf-8")
    assert _settle(world, 3, "D3", _AnswerSpec("claude", "C.\nPOSITION: C.\n")).code == 1

    res = world.run("debate", TASK, "cross")
    assert res.code == 0, res.text
    assert "dropped seat 'claude-2'" in res.text
    assert len(world.worker_lines(res)) == 2
    assert [d["focus"] for d in load_debate(world.store, TASK)["dropped"]] == ["claude-2"]
    invalid_file = str(world.record(3)["file"])
    assert all(invalid_file not in (world.run_dir(n) / "spec.md").read_text() for n in (4, 5))


def test_cross_refuses_under_two_valid_seats_or_providers(world: OrcaWorld, tmp_path: Path) -> None:
    topic = _topic(tmp_path)
    _open_debate(world, topic, "claude,codex,claude")
    assert _settle(world, 1, "D1", _AnswerSpec("claude", "A.\nPOSITION: A.\n")).code == 0
    assert _settle(world, 2, "D2", _AnswerSpec("codex", "", state="failed")).code == 1
    assert _settle(world, 3, "D3", _AnswerSpec("claude", "C.\nPOSITION: C.\n")).code == 0
    one_provider = world.run("debate", TASK, "cross")
    assert one_provider.code == 1 and "fewer than 2 distinct providers" in one_provider.text
    assert load_debate(world.store, TASK)["dropped"] == []

    _new_bound_task(world, "TASK-2")
    world.task_id = "TASK-2"
    _open_debate(world, topic, "claude,codex")
    assert _settle(world, 1, "T2D1", _AnswerSpec("claude", "A.\nPOSITION: A.\n")).code == 0
    assert _settle(world, 2, "T2D2", _AnswerSpec("codex", "", state="failed")).code == 1
    one_seat = world.run("debate", "TASK-2", "cross")
    assert one_seat.code == 1 and "fewer than 2 valid" in one_seat.text
    assert load_debate(world.store, "TASK-2")["dropped"] == []


def test_status_reports_pending_collected_invalid_and_dropped_json_and_table(
    world: OrcaWorld, tmp_path: Path
) -> None:
    _open_debate(world, _topic(tmp_path), "claude,codex,claude,antigravity")
    initial = json.loads(world.run("debate", TASK, "status", "--json").out)
    assert [row["state"] for row in initial] == ["pending"] * 4

    for n, agent in ((1, "claude"), (2, "codex"), (3, "claude")):
        assert _settle(world, n, f"D{n}", _AnswerSpec(agent, f"T{n}.\nPOSITION: P{n}.\n")).code == 0
    assert _settle(world, 4, "D4", _AnswerSpec("antigravity", "", state="failed")).code == 1
    pre_cross = {
        r["focus"]: r for r in json.loads(world.run("debate", TASK, "status", "--json").out)
    }
    assert pre_cross["antigravity"]["state"] == "invalid"

    assert world.run("debate", TASK, "cross").code == 0
    assert _settle(world, 5, "D5", _AnswerSpec("claude", "C5.\nPOSITION: F5.\n")).code == 0
    assert _settle(world, 7, "D7", _AnswerSpec("claude", "", state="failed")).code == 1

    rows = json.loads(world.run("debate", TASK, "status", "--json").out)
    assert {r["focus"]: r["state"] for r in rows} == {
        "claude": "collected",
        "codex": "pending",
        "claude-2": "invalid",
        "antigravity": "dropped",
    }
    table = world.run("debate", TASK, "status")
    assert (
        table.code == 0
        and "focus | agent | model | thesis_round | cross_round | state" in table.out
    )
    for token in ("collected", "pending", "invalid", "dropped"):
        assert token in table.out


# -- Delivery 2: synthesis, formatting, missing lines, partial close, idempotency --------------


def _cross_body_three_seats() -> tuple[str, str, str]:
    c1 = (
        "REBUT: round 002 | SQLite scales writes | bench shows lock waits | refuted\n"
        "REBUT: round 002 | Zero external ops | embedded file | agreed\n"
        "REBUT: round 002 | Snapshot cadence | cron vs litestream | open\n"
        "REBUT: round 003 | Hybrid sync lag | partition behavior untested | open\n"
        "CHANGED: Keep Redis for hot state | round 002\n"
        "POSITION: Redis with async snapshot.\n"
    )
    c2 = (
        "REBUT: round 001 | Redis RAM cheap | 4GB for 1M sessions | refuted\n"
        "CHANGED: Partition SQLite per tenant | round 001\n"
        "POSITION: Sharded SQLite per tenant.\n"
    )
    c3 = "No structured rebuttals from this seat.\nPOSITION: Hybrid stays viable.\n"
    return c1, c2, c3


def _run_three_seat_cross(world: OrcaWorld, tmp_path: Path, topic: Path) -> None:
    _open_debate(world, topic, "claude,codex,claude")
    for n, agent, pos in ((1, "claude", "Redis"), (2, "codex", "SQLite"), (3, "claude", "Hybrid")):
        ans = f"Thesis {n}.\nPOSITION: {pos}.\n"
        assert _settle(world, n, f"D{n}", _AnswerSpec(agent, ans, tmp_path / f"t{n}.txt")).code == 0
    assert world.run("debate", TASK, "cross").code == 0
    for n, agent, body in zip(
        (4, 5, 6), ("claude", "codex", "claude"), _cross_body_three_seats(), strict=True
    ):
        assert (
            _settle(world, n, f"D{n}", _AnswerSpec(agent, body, tmp_path / f"c{n}.txt")).code == 0
        )


def test_close_synthesis_matrix_refutations_changes_open_points_answer_only(
    world: OrcaWorld, tmp_path: Path
) -> None:
    decoy_topic = _topic(
        tmp_path,
        "Compare cache layers.\nREBUT: round 001 | decoy | decoy | refuted\n"
        "CHANGED: decoy change | round 001\nPOSITION: decoy topic pos\n",
    )
    _run_three_seat_cross(world, tmp_path, decoy_topic)
    assert not any((world.run_dir(n) / "answer.txt").exists() for n in range(1, 7))

    close_res = world.run("debate", TASK, "close")
    assert close_res.code == 0, close_res.text
    synth_path = world.store.task_dir(TASK) / SYNTHESIS_FILE
    assert Path(close_res.out.strip()) == synth_path
    text = synth_path.read_text(encoding="utf-8")

    matrix = _section(text, "Cross-Examination Matrix")
    assert "| claude | — | 1 / 1 / 1 | 0 / 0 / 1 |" in matrix
    assert "| codex | 1 / 0 / 0 | — | 0 / 0 / 0 |" in matrix
    assert "| claude-2 | no structured lines | no structured lines | — |" in matrix

    refutations = _section(text, "Refutations")
    assert "SQLite scales writes" in refutations and "Redis RAM cheap" in refutations
    assert "decoy" not in matrix and "decoy" not in refutations
    changes = _section(text, "Position Changes")
    assert "Keep Redis for hot state" in changes and "Partition SQLite per tenant" in changes
    assert "thesis: Redis. | cross: Redis with async snapshot." in changes
    assert "thesis: SQLite. | cross: Sharded SQLite per tenant." in changes
    assert "thesis: Hybrid. | cross: Hybrid stays viable." in changes
    assert "decoy" not in changes and "<one sentence>" not in changes
    open_pts = _section(text, "Open Points")
    assert "Snapshot cadence" in open_pts and "Hybrid sync lag" in open_pts
    assert "decoy" not in open_pts and _section(text, "Missing").strip() == "(none)"


def test_close_parses_markdown_formatted_lines_and_internal_answer_subheading(
    world: OrcaWorld, tmp_path: Path
) -> None:
    cross_claude = (
        "- `REBUT: round 002 | backtick claim | ev1 | refuted.`\n"
        "**CHANGED:** bold before subheading | round 002\n"
        "## Request\nQuoted header inside worker reply\n"
        "## Answer\n"
        "**REBUT**: round 002 | bold claim | ev2 | **agreed.**\n"
        "`CHANGED: backtick after subheading | round 002`\n"
        "**POSITION:** Bold final position.\n"
    )
    cross_codex = (
        "REBUT: round 001 | tick outcome | ev3 | `refuted.`\n"
        "`REBUT: round 001 | tick open | ev4 | open.`\n"
        "`POSITION: Backtick final position.`\n"
    )
    _run_two_seat_debate(world, _topic(tmp_path), cross_claude, cross_codex)
    text = (world.store.task_dir(TASK) / SYNTHESIS_FILE).read_text(encoding="utf-8")

    matrix = _section(text, "Cross-Examination Matrix")
    assert "| claude | — | 1 / 1 / 0 |" in matrix
    assert "| codex | 1 / 0 / 1 | — |" in matrix
    assert "backtick claim" in _section(text, "Refutations")
    assert "tick outcome" in _section(text, "Refutations")
    assert "tick open" in _section(text, "Open Points")
    changes = _section(text, "Position Changes")
    assert "bold before subheading" in changes and "backtick after subheading" in changes
    assert "cross: Bold final position." in changes
    assert "cross: Backtick final position." in changes
    assert _section(text, "Missing").strip() == "(none)"

    doc = (
        "# Round 003 · design · debater · claude claude-4\n\n"
        "- Date: 2026-01-01T00:00:00Z\n- Code stamp: deadbeef\n\n"
        "## Request\n\nprompt\n\n## Answer\n\n"
        "# Round 002 notes\nREBUT: round 002 | c1 | e1 | refuted\n"
        "## Request\nquoted\n## Answer\nREBUT: round 002 | c2 | e2 | agreed\n"
    )
    unwrapped = answer_section(doc)
    assert answer_section(unwrapped) == unwrapped
    assert len(parse_rebuts(unwrapped)[0]) == 2


def test_close_invalid_rebuts_only_shows_zero_counts_not_no_structured_lines(
    world: OrcaWorld, tmp_path: Path
) -> None:
    cross_claude = "REBUT: round 099 | ghost | proof | refuted\nPOSITION: A.\n"
    cross_codex = "REBUT: round 001 | real | proof | agreed\nPOSITION: B.\n"
    _run_two_seat_debate(world, _topic(tmp_path), cross_claude, cross_codex)
    text = (world.store.task_dir(TASK) / SYNTHESIS_FILE).read_text(encoding="utf-8")
    matrix = _section(text, "Cross-Examination Matrix")
    assert "| claude | — | 0 / 0 / 0 |" in matrix
    assert "no structured lines" not in matrix
    assert "invalid target 099" in _section(text, "Missing")


_BAD_CROSS_ANSWER = (
    "REBUT: round 003 | valid point | read code | agreed\n"
    "REBUT: round 002 | own claim | self proof | refuted\n"
    "REBUT: round 001 | planner claim | p proof | open\n"
    "REBUT: round 099 | ghost claim | g proof | refuted\n"
    "REBUT: round 003 | too few fields | missing outcome\n"
    "REBUT: round 003 | c | e | maybe\n"
    "REBUT: round 003 |   | e | refuted\n"
    "REBUT: round 003 | c |   | open\n"
    "REBUT: round xyz | c | e | agreed\n"
    "CHANGED: self swap | round 002\n"
    "CHANGED: planner swap | round 001\n"
    "CHANGED: missing pipe\n"
    "CHANGED: shifted | round nope\n"
    "POSITION: Final A.\n"
)


def test_close_routes_non_debate_self_and_malformed_lines_to_missing(
    world: OrcaWorld, tmp_path: Path
) -> None:
    _seed_prior_round(world)
    _open_debate(world, _topic(tmp_path), "claude,codex")
    assert _settle(world, 2, "D2", _AnswerSpec("claude", "T2.\nPOSITION: A.\n")).code == 0
    assert _settle(world, 3, "D3", _AnswerSpec("codex", "T3.\nPOSITION: B.\n")).code == 0
    assert world.run("debate", TASK, "cross").code == 0
    assert _settle(world, 4, "D4", _AnswerSpec("claude", _BAD_CROSS_ANSWER)).code == 0
    r5 = _AnswerSpec("codex", "REBUT: round 002 | x | y | refuted\nPOSITION: B.\n")
    assert _settle(world, 5, "D5", r5).code == 0

    assert world.run("debate", TASK, "close").code == 0
    text = (world.store.task_dir(TASK) / SYNTHESIS_FILE).read_text(encoding="utf-8")
    assert "| claude | — | 0 / 1 / 0 |" in _section(text, "Cross-Examination Matrix")
    assert _section(text, "Open Points").strip() == "(none)"
    changes = _section(text, "Position Changes")
    assert "self swap" not in changes and "planner swap" not in changes
    missing = _section(text, "Missing")
    for expected in (
        "self-rebuttal",
        "invalid target 001",
        "invalid target 099",
        "self-changed -> `CHANGED: self swap | round 002`",
        "CHANGED references invalid target 001",
        '"REBUT: round 003 | too few fields | missing outcome"',
        '"REBUT: round 003 | c | e | maybe"',
        '"REBUT: round 003 |   | e | refuted"',
        '"REBUT: round 003 | c |   | open"',
        '"REBUT: round xyz | c | e | agreed"',
        '"CHANGED: missing pipe"',
        '"CHANGED: shifted | round nope"',
    ):
        assert expected in missing


def test_close_routes_unreadable_invalid_utf8_round_files_to_missing(
    world: OrcaWorld, tmp_path: Path
) -> None:
    _run_two_seat_debate(world, _topic(tmp_path), "REBUT: round 002 | c | e | agreed\n")
    Path(str(world.record(1)["file"])).write_bytes(b"\xff\xfe\x00")
    Path(str(world.record(4)["file"])).write_bytes(b"\xff\xfe\x00")

    assert world.run("debate", TASK, "close").code == 0
    text = (world.store.task_dir(TASK) / SYNTHESIS_FILE).read_text(encoding="utf-8")
    missing = _section(text, "Missing")
    assert "Unreadable thesis round file for 'claude' (round 001)" in missing
    assert "Unreadable cross round file for 'codex' (round 004)" in missing
    assert "| codex | invalid | — |" in _section(text, "Cross-Examination Matrix")


def _prepare_partial_debate(world: OrcaWorld, topic: Path) -> Path:
    _open_debate(world, topic, "claude,codex,claude")
    for n, agent in ((1, "claude"), (2, "codex"), (3, "claude")):
        assert _settle(world, n, f"D{n}", _AnswerSpec(agent, f"T{n}.\nPOSITION: P{n}.\n")).code == 0
    assert world.run("debate", TASK, "cross").code == 0
    c4 = (
        "REBUT: round 002 | Open A claim | proof A | open\n"
        "REBUT: round 003 | Open B claim | proof B | open\nPOSITION: Final A.\n"
    )
    assert _settle(world, 4, "D4", _AnswerSpec("claude", c4)).code == 0
    return world.store.task_dir(TASK) / SYNTHESIS_FILE


def test_close_refuses_pending_cross_and_partial_writes_steps_and_blocks_reopen(
    world: OrcaWorld, tmp_path: Path
) -> None:
    topic = _topic(tmp_path)
    synth_path = _prepare_partial_debate(world, topic)
    assert world.run("debate", TASK, "close").code == 1
    assert not synth_path.exists()

    assert world.run("debate", TASK, "close", "--partial").code == 0
    synth = synth_path.read_text(encoding="utf-8")
    assert "005" in _section(synth, "Missing") and "006" in _section(synth, "Missing")
    assert "pending" in _section(synth, "Cross-Examination Matrix")
    assert load_debate(world.store, TASK)["status"] == "closed"
    assert [s["text"] for s in world.task().steps] == [
        "[debate] Open A claim",
        "[debate] Open B claim",
    ]
    blocked = world.run(
        "debate", TASK, "open", "--topic-file", str(topic), "--agents", "claude,codex"
    )
    assert blocked.code == 1 and "still pending" in blocked.text
    assert load_debate(world.store, TASK)["debate_id"] == 1


def test_close_partial_idempotency_removed_step_and_late_collect(
    world: OrcaWorld, tmp_path: Path
) -> None:
    topic = _topic(tmp_path)
    synth_path = _prepare_partial_debate(world, topic)
    assert world.run("debate", TASK, "close", "--partial").code == 0
    first_bytes = synth_path.read_bytes()

    assert world.run("debate", TASK, "close", "--partial").code == 0
    assert synth_path.read_bytes() == first_bytes
    assert len(world.task().steps) == 2

    assert world.run("step", TASK, "remove", "1").code == 0
    c5 = "REBUT: round 001 | Open C claim | proof C | open\nPOSITION: Final B.\n"
    assert _settle(world, 5, "D5", _AnswerSpec("codex", c5)).code == 0
    assert world.run("debate", TASK, "close", "--partial").code == 0
    assert [s["text"] for s in world.task().steps] == [
        "[debate] Open B claim",
        "[debate] Open C claim",
    ]

    assert world.abort(6, "--reason", "abandoned", "--never-started").code == 0
    assert len(_open_debate(world, topic, "claude,codex")) == 2
    assert load_debate(world.store, TASK)["debate_id"] == 2


def test_close_long_open_claims_distinct_and_done_step_readded_next_debate(
    world: OrcaWorld, tmp_path: Path
) -> None:
    topic = _topic(tmp_path)
    prefix = "shared-" + "a" * 198
    claim1 = prefix + "-first-ending"
    claim2 = prefix + "-second-ending"
    cross1 = (
        f"REBUT: round 002 | {claim1} | proof 1 | open\n"
        f"REBUT: round 002 | {claim2} | proof 2 | open\nPOSITION: A.\n"
    )
    _run_two_seat_debate(world, topic, cross1)
    steps1 = world.task().steps
    assert len(steps1) == 2
    assert steps1[0]["text"] != steps1[1]["text"]
    assert all(len(s["text"]) <= STEP_MAX_CHARS for s in steps1)

    assert world.run("step", TASK, "done", "1").code == 0
    cross2 = f"REBUT: round 006 | {claim1} | proof 3 | open\nPOSITION: A2.\n"
    _run_two_seat_debate(world, topic, cross2)
    steps2 = world.task().steps
    assert len(steps2) == 3
    assert [bool(s["done"]) for s in steps2] == [True, False, False]
    assert steps2[2]["text"].startswith("[debate #2] ")
    assert steps2[2]["text"] != steps2[0]["text"]
    assert len(steps2[2]["text"]) <= STEP_MAX_CHARS


# -- Delivery 3: web research and visual artifacts on debate -----------------------------------


def test_open_web_and_artifact_propagates_to_cross(world: OrcaWorld, tmp_path: Path) -> None:
    artifact = tmp_path / "ui" / "wireframe.png"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"\x89PNG\r\n")
    rel = os.path.relpath(artifact, world.repo)
    resolved = str(artifact.resolve())

    _open_debate(world, _topic(tmp_path), "claude,codex", ("--web", "--artifact", rel))
    assert load_debate(world.store, TASK)["flags"] == {"web": True, "artifacts": [resolved]}
    for n, agent in ((1, "claude"), (2, "codex")):
        spec = (world.run_dir(n) / "spec.md").read_text(encoding="utf-8")
        assert WEB_INSTRUCTION in spec and artifact_instruction([resolved]) in spec
        assert _settle(world, n, f"D{n}", _AnswerSpec(agent, f"T{n}.\nPOSITION: P{n}.\n")).code == 0

    assert world.run("debate", TASK, "cross").code == 0
    for n in (3, 4):
        spec = (world.run_dir(n) / "spec.md").read_text(encoding="utf-8")
        assert WEB_INSTRUCTION in spec and artifact_instruction([resolved]) in spec


def test_cross_refuses_when_artifact_changes_after_open(world: OrcaWorld, tmp_path: Path) -> None:
    artifact = tmp_path / "diagram.png"
    artifact.write_bytes(b"v1")
    _open_debate(world, _topic(tmp_path), "claude,codex", ("--artifact", str(artifact)))
    assert _settle(world, 1, "D1", _AnswerSpec("claude", "T1.\nPOSITION: P1.\n")).code == 0
    assert _settle(world, 2, "D2", _AnswerSpec("codex", "T2.\nPOSITION: P2.\n")).code == 0

    artifact.write_bytes(b"v2-modified")
    res = world.run("debate", TASK, "cross")
    assert res.code == 1 and "artifact changed since the debate was opened" in res.text
    assert all(s["cross_round"] is None for s in load_debate(world.store, TASK)["seats"])


@pytest.mark.parametrize("kind", ["missing", "directory", "dangling"])
def test_open_refuses_missing_or_non_regular_artifact_atomically(
    world: OrcaWorld, tmp_path: Path, kind: str
) -> None:
    topic = _topic(tmp_path)
    bad = _bad_artifact(tmp_path, kind)
    res = world.run(
        "debate",
        TASK,
        "open",
        "--topic-file",
        str(topic),
        "--agents",
        "claude,codex",
        "--artifact",
        str(bad),
    )
    assert res.code == 1
    _check_clean_store(world)


# -- Delivery 4: debater effort and denied models ----------------------------------------------


def test_debater_effort_reaches_open_and_cross_worker_lines(
    world: OrcaWorld, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    topic = _topic(tmp_path)
    monkeypatch.setenv("AI_GOVERNANCE_DEBATER_EFFORT", "")
    open_lines = _open_debate(world, topic, "claude,codex", ("--model", "claude=claude-sonnet-4"))
    assert all("--effort" not in line for line in open_lines)
    assert all(world.dispatch_json(n)["effort"] == "" for n in (1, 2))

    assert _settle(world, 1, "D1", _AnswerSpec("claude", "A.\nPOSITION: A.\n")).code == 0
    assert _settle(world, 2, "D2", _AnswerSpec("codex", "B.\nPOSITION: B.\n")).code == 0
    monkeypatch.setenv("AI_GOVERNANCE_DEBATER_EFFORT", "high")
    cross_res = world.run("debate", TASK, "cross")
    assert cross_res.code == 0, cross_res.text
    cross_lines = world.worker_lines(cross_res)
    assert all(flag(line, "--effort") == "high" for line in cross_lines)
    assert all(line.index("--effort") == line.index("--model") + 2 for line in cross_lines)

    _new_bound_task(world, "TASK-2")
    world.task_id = "TASK-2"
    missing_model = world.run(
        "debate", "TASK-2", "open", "--topic-file", str(topic), "--agents", "claude,codex"
    )
    assert missing_model.code == 1 and "effort requires a model" in missing_model.text
    high_open = _open_debate(world, topic, "claude,codex", ("--model", "claude=claude-sonnet-4"))
    assert all(flag(line, "--effort") == "high" for line in high_open)


def _assert_denied_open(world: OrcaWorld, topic: Path, extra: Sequence[str] = ()) -> None:
    res = world.run(
        "debate", TASK, "open", "--topic-file", str(topic), "--agents", "claude,codex", *extra
    )
    assert res.code == 1 and "taskflow.denied_models" in res.text
    _check_clean_store(world)


def test_denied_models_refuse_open_via_env_explicit_and_default(
    world: OrcaWorld, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    topic = _topic(tmp_path)
    monkeypatch.setenv("AI_GOVERNANCE_DENIED_MODELS", "blocked-claude")
    _assert_denied_open(world, topic, ("--model", "claude=blocked-claude"))
    _assert_denied_open(world, topic)  # implicit empty claude model also refused
    monkeypatch.setenv("AI_GOVERNANCE_DENIED_MODELS", "gpt-6.1-sol")
    _assert_denied_open(world, topic, ("--model", "claude=claude-sonnet-4"))


def test_denied_models_refuse_open_via_user_and_repo_config(
    world: OrcaWorld, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    topic = _topic(tmp_path)
    monkeypatch.delenv("AI_GOVERNANCE_DENIED_MODELS", raising=False)
    user_cfg = tmp_path / "config" / "ai-governance" / "config.toml"
    repo_cfg = world.repo / ".ai-governance" / "config.toml"
    claude_model = ("--model", "claude=claude-sonnet-4")

    _write_toml(user_cfg, '[taskflow]\ndenied_models = ["gpt-6.1-sol"]\n')
    _assert_denied_open(world, topic, claude_model)

    _write_toml(repo_cfg, '[taskflow]\ndenied_models = ["other-model"]\n')
    _assert_denied_open(world, topic, claude_model)

    user_cfg.unlink()
    _write_toml(repo_cfg, '[taskflow]\ndenied_models = ["repo-denied"]\n')
    _assert_denied_open(world, topic, ("--model", "claude=repo-denied"))
    assert not user_cfg.exists()


def test_debate_cli_json_warnings_and_usage_refusal(
    world: OrcaWorld, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert artifact_instruction(()) == ""
    assert world.run("debate", TASK, "status").code == 1
    assert world.run("debate", TASK, "close").code == 1

    topic = _topic(tmp_path)
    open_res = world.run(
        "debate",
        TASK,
        "open",
        "--topic-file",
        str(topic),
        "--agents",
        "claude,,codex,claude",
        "--json",
    )
    assert open_res.code == 0
    assert json.loads(open_res.out)["debate_id"] == 1
    assert _settle(world, 1, "D1", _AnswerSpec("claude", "P1.\nPOSITION: A.\n")).code == 0
    assert _settle(world, 2, "D2", _AnswerSpec("codex", "P2.\nPOSITION: B.\n")).code == 0
    assert _settle(world, 3, "D3", _AnswerSpec("claude", "bad", state="stopped")).code == 1

    cross_res = world.run("debate", TASK, "cross", "--json")
    assert cross_res.code == 0 and "WARN: dropped seat 'claude-2'" in cross_res.err
    assert len(json.loads(cross_res.out)["seats"]) == 2

    def _raise_refusal(_args: argparse.Namespace) -> int:
        raise UsageRefusal("wrong usage")

    monkeypatch.setattr(debate_cli, "_status", _raise_refusal)
    assert debate_cli.route(argparse.Namespace(debate_action="status")) == 2


def test_debate_guards_for_inputs_task_state_and_midflight_config(
    world: OrcaWorld, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = load_config([world.repo])
    with pytest.raises(DispatchError, match="cannot be empty"):
        assign_seats(["claude", "  "], None, cfg)
    with pytest.raises(DispatchError, match="artifact path cannot be empty"):
        open_debate(
            world.store,
            TASK,
            cfg,
            OpenDebateOptions(_topic(tmp_path), ("claude", "codex"), artifacts=("  ",)),
        )

    debate_path(world.store, TASK).write_text("[1, 2]", encoding="utf-8")
    assert world.run("debate", TASK, "status").code == 1
    debate_path(world.store, TASK).unlink()

    def _block(task) -> None:
        task.blocked = {"owner": "ops", "needs": "approval"}

    world.store.mutate(TASK, _block)
    res_blk = world.run(
        "debate", TASK, "open", "--topic-file", str(_topic(tmp_path)), "--agents", "claude,codex"
    )
    assert res_blk.code == 1 and "blocked by ops" in res_blk.text

    _new_bound_task(world, "TASK-GONE")
    monkeypatch.chdir(world.base)
    shutil.rmtree(world.repo)
    assert (
        world.run(
            "debate",
            "TASK-GONE",
            "open",
            "--topic-file",
            str(_topic(tmp_path)),
            "--agents",
            "claude,codex",
        ).code
        == 1
    )


@pytest.mark.parametrize(
    "bad_field", ["flags", "artifacts", "artifact_digests", "topic_sha", "status"]
)
def test_debate_cross_rejects_corrupted_or_changed_state_and_midflight_denial(
    world: OrcaWorld, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, bad_field: str
) -> None:
    topic = _topic(tmp_path)
    _open_debate(world, topic, "claude,codex")
    assert _settle(world, 1, "D1", _AnswerSpec("claude", "T1.\nPOSITION: A.\n")).code == 0
    assert _settle(world, 2, "D2", _AnswerSpec("codex", "T2.\nPOSITION: B.\n")).code == 0

    state = load_debate(world.store, TASK)
    if bad_field == "flags":
        state["flags"] = ["not-a-dict"]
    elif bad_field == "artifacts":
        state["flags"] = {"web": False, "artifacts": "not-a-list"}
    elif bad_field == "artifact_digests":
        state["artifact_digests"] = ["not-a-dict"]
    elif bad_field == "topic_sha":
        topic.write_text("Edited topic.\n", encoding="utf-8")
    else:
        state["status"] = "closed"
    debate.save_debate(world.store, TASK, state)
    assert world.run("debate", TASK, "cross").code == 1


def test_debate_cross_midflight_denial_duplicate_and_save_rollback(
    world: OrcaWorld, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    topic = _topic(tmp_path)
    orig_save = debate.save_debate
    monkeypatch.setattr(debate, "save_debate", lambda *_a: (_ for _ in ()).throw(OSError("disk")))
    assert (
        world.run(
            "debate", TASK, "open", "--topic-file", str(topic), "--agents", "claude,codex"
        ).code
        == 1
    )
    _check_clean_store(world)
    monkeypatch.setattr(debate, "save_debate", orig_save)

    _open_debate(world, topic, "claude,codex")
    assert _settle(world, 1, "D1", _AnswerSpec("claude", "T1.\nPOSITION: A.\n")).code == 0
    assert _settle(world, 2, "D2", _AnswerSpec("codex", "T2.\nPOSITION: B.\n")).code == 0

    monkeypatch.setenv("AI_GOVERNANCE_DENIED_MODELS", "gpt-6.1-sol")
    assert world.run("debate", TASK, "cross").code == 1
    monkeypatch.delenv("AI_GOVERNANCE_DENIED_MODELS")
    monkeypatch.setenv("AI_GOVERNANCE_ALLOWED_AGENTS", "claude")
    assert world.run("debate", TASK, "cross").code == 1
    monkeypatch.delenv("AI_GOVERNANCE_ALLOWED_AGENTS")

    monkeypatch.setattr(debate, "save_debate", lambda *_a: (_ for _ in ()).throw(OSError("disk")))
    assert world.run("debate", TASK, "cross").code == 1
    monkeypatch.setattr(debate, "save_debate", orig_save)
    assert world.run("debate", TASK, "cross").code == 0
    assert world.run("debate", TASK, "cross").code == 1


def test_synthesis_handles_invalid_cross_unreadable_rounds_and_string_drops(
    world: OrcaWorld, tmp_path: Path
) -> None:
    topic = _topic(tmp_path)
    _open_debate(world, topic, "claude,codex,claude")
    assert _settle(world, 1, "D1", _AnswerSpec("claude", "T1.\nPOSITION: A.\n")).code == 0
    assert _settle(world, 2, "D2", _AnswerSpec("codex", "T2.\nPOSITION: B.\n")).code == 0
    assert _settle(world, 3, "D3", _AnswerSpec("claude", "stopped", state="stopped")).code == 1
    assert world.run("debate", TASK, "close").code == 1  # cross not dispatched

    assert world.run("debate", TASK, "cross").code == 0
    assert _settle(world, 4, "D4", _AnswerSpec("claude", "stopped", state="stopped")).code == 1
    assert (
        _settle(
            world,
            5,
            "D5",
            _AnswerSpec("codex", "REBUT: round 001 | c | e | agreed\nPOSITION: B.\n"),
        ).code
        == 0
    )

    state = load_debate(world.store, TASK)
    state["dropped"].append("manual drop note")
    debate.save_debate(world.store, TASK, state)
    Path(world.task().rounds[0]["file"]).unlink()  # unreadable thesis file
    assert world.run("debate", TASK, "close", "--partial").code == 0
    text = (world.store.task_dir(TASK) / SYNTHESIS_FILE).read_text(encoding="utf-8")
    assert "| invalid |" in _section(text, "Cross-Examination Matrix")
    missing = _section(text, "Missing")
    assert "Invalid cross round 004" in missing and "Unreadable thesis round file" in missing
    assert "manual drop note" in missing


def test_rollback_dispatched_acquires_task_lock_and_skips_empty(
    world: OrcaWorld, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from contextlib import contextmanager

    locks: list[str] = []
    real_lock = world.store._lock

    @contextmanager
    def tracked_lock(task_id: str):  # type: ignore[no-untyped-def]
        locks.append(task_id)
        with real_lock(task_id) as directory:
            yield directory

    monkeypatch.setattr(world.store, "_lock", tracked_lock)
    debate._rollback_dispatched(world.store, TASK, [])
    assert locks == []

    topic = _topic(tmp_path)
    monkeypatch.setattr(debate, "save_debate", lambda *_a: (_ for _ in ()).throw(OSError("disk")))
    with pytest.raises(OSError, match="disk"):
        debate.open_debate(
            world.store,
            TASK,
            load_config([world.repo]),
            OpenDebateOptions(topic_file=topic, agents=("claude", "codex")),
        )
    # 1 lock for refresh + 2 locks for reserve_round + 1 lock for _rollback_dispatched
    assert len(locks) >= 4 and locks[-1] == TASK
    _check_clean_store(world)
