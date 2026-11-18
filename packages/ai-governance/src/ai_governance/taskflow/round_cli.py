"""Command handlers of ``round collect|abort`` (split out of ``cli``)."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Literal

from ..output import emit_status
from .collect import RoundRef, abort_round, collect_round
from .control import UsageRefusal
from .models import JsonDict
from .store import TaskStore


def route(args: argparse.Namespace) -> int:
    """Run the handler of ``args.action``; a request that can never work exits 2."""
    handlers = {"collect": _collect, "abort": _abort}
    try:
        return handlers[args.action](args)
    except UsageRefusal as exc:
        emit_status("error", str(exc))
        return 2


def _report(record: JsonDict, prefix: str = "") -> None:
    level: Literal["ok", "warn"] = "ok" if record["state"] == "valid" else "warn"
    reason = f" - {record['reason']}" if record.get("reason") else ""
    emit_status(
        level,
        f"{prefix}Round {int(record['n']):03d} {record['role']}: {record['verdict']} "
        f"({record['state']}{reason}). Read it: {record['file']}",
    )


def _collect(args: argparse.Namespace) -> int:
    answer = Path(args.answer_file) if args.answer_file else None
    settled = collect_round(
        TaskStore(), RoundRef(args.task_id, args.round), args.dispatch_id, answer
    )
    record = settled.record
    if settled.already:
        level: Literal["ok", "warn"] = "ok" if record["state"] == "valid" else "warn"
        emit_status(
            level,
            f"Round {int(record['n']):03d} was already collected (verdict {record['verdict']})",
        )
    else:
        _report(record)
    return 0 if record["state"] == "valid" else 1


def _abort(args: argparse.Namespace) -> int:
    dispatch_id = None if args.never_started else args.dispatch_id
    record = abort_round(TaskStore(), RoundRef(args.task_id, args.round), args.reason, dispatch_id)
    who = f"dispatch {dispatch_id}" if dispatch_id else "your assertion that no worker started"
    emit_status("ok", f"Round {int(record['n']):03d} aborted ({who}): {record['reason']}")
    if not dispatch_id:
        emit_status(
            "warn",
            "If a worker was started anyway it keeps running and its output is ignored; "
            "stop it in Orca.",
        )
    return 0
