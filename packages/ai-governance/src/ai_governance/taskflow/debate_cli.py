"""Command handlers of ``taskflow debate <id> open|cross|status|close``."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from ..output import emit_json, emit_rows, emit_status
from .config import load_config
from .control import UsageRefusal
from .debate import (
    DispatchedSeat,
    OpenDebateOptions,
    cross_debate,
    debate_status,
    open_debate,
)
from .models import JsonDict
from .store import TaskStore
from .synthesis import close_debate


def route(args: argparse.Namespace) -> int:
    """Run the handler of ``args.debate_action``; an impossible request exits 2."""
    handlers = {"open": _open, "cross": _cross, "status": _status, "close": _close}
    try:
        return handlers[args.debate_action](args)
    except UsageRefusal as exc:
        emit_status("error", str(exc))
        return 2


def _parse_agents(raw: object) -> tuple[str, ...]:
    items = [raw] if isinstance(raw, str) else list(raw) if isinstance(raw, (list, tuple)) else []
    tokens: list[str] = []
    for item in items:
        for part in str(item).split(","):
            if cleaned := part.strip():
                tokens.append(cleaned)
    return tuple(tokens)


def _parse_models(raw: Sequence[str]) -> dict[str, str]:
    models: dict[str, str] = {}
    for entry in raw:
        if "=" not in entry:
            raise ValueError(f"invalid --model '{entry}': expected agent=model")
        key, val = entry.split("=", 1)
        key, val = key.strip(), val.strip()
        if not key or not val:
            raise ValueError(f"invalid --model '{entry}': expected non-empty agent=model")
        models[key] = val
    return models


def _seat_payload(item: DispatchedSeat) -> JsonDict:
    return {
        "focus": item.seat.focus,
        "agent": item.seat.agent,
        "model": item.seat.model,
        "round": item.round.n,
        "argv": item.round.argv,
        "spec": str(item.round.spec),
        "launch": str(item.round.launch) if item.round.launch else "",
    }


def _emit_dispatched(seats: Sequence[DispatchedSeat], payload: JsonDict, json_mode: bool) -> None:
    if json_mode:
        emit_json(payload)
        return
    for item in seats:
        print(item.round.line())


def _print_hint(
    task_id: str, debate_id: int, seats: Sequence[DispatchedSeat], next_action: str
) -> None:
    rounds = ", ".join(f"{item.round.n:03d} ({item.seat.focus})" for item in seats)
    stage = "opened" if next_action == "cross" else "cross-examination"
    print(
        f"Debate #{debate_id} {stage}: reserved rounds {rounds}. "
        f"Run each line, end your turn, collect each with "
        f"`taskflow round {task_id} collect --round N --dispatch-id <ID>`, "
        f"then: taskflow debate {task_id} {next_action}",
        file=sys.stderr,
    )


def _open(args: argparse.Namespace) -> int:
    store = TaskStore()
    task = store.get(args.task_id)
    config = load_config([Path(r["path"]) for r in task.repos])
    opts = OpenDebateOptions(
        topic_file=Path(args.topic_file).expanduser(),
        agents=_parse_agents(args.agents),
        models=_parse_models(args.model),
        web=bool(args.web),
        artifacts=tuple(args.artifact),
    )
    res = open_debate(store, task.id, config, opts)
    payload: JsonDict = {
        "debate_id": res.debate_id,
        "seats": [_seat_payload(s) for s in res.seats],
    }
    _emit_dispatched(res.seats, payload, bool(args.json))
    _print_hint(task.id, res.debate_id, res.seats, "cross")
    return 0


def _cross(args: argparse.Namespace) -> int:
    store = TaskStore()
    task = store.get(args.task_id)
    config = load_config([Path(r["path"]) for r in task.repos])
    res = cross_debate(store, task.id, config)
    for warning in res.warnings:
        if args.json:
            print(f"WARN: {warning}", file=sys.stderr)
        else:
            emit_status("warn", warning)
    payload: JsonDict = {
        "debate_id": res.debate_id,
        "seats": [_seat_payload(s) for s in res.seats],
        "warnings": list(res.warnings),
    }
    _emit_dispatched(res.seats, payload, bool(args.json))
    _print_hint(task.id, res.debate_id, res.seats, "close")
    return 0


def _fmt_round(value: object) -> str:
    return f"{value:03d}" if isinstance(value, int) and not isinstance(value, bool) else "-"


def _status(args: argparse.Namespace) -> int:
    store = TaskStore()
    task = store.get(args.task_id)
    rows = debate_status(store, task.id)
    if args.json:
        emit_json(rows)
        return 0
    emit_rows(
        [
            (
                str(row["focus"]),
                str(row["agent"]),
                str(row["model"]) or "-",
                _fmt_round(row["thesis_round"]),
                _fmt_round(row["cross_round"]),
                str(row["state"]),
            )
            for row in rows
        ],
        headers=("focus", "agent", "model", "thesis_round", "cross_round", "state"),
        title=f"Debate status of {task.id}",
        full=True,
    )
    return 0


def _close(args: argparse.Namespace) -> int:
    store = TaskStore()
    task = store.get(args.task_id)
    path = close_debate(store, task.id, partial=bool(args.partial))
    print(path)
    return 0
