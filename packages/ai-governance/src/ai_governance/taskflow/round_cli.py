"""Command handlers of ``round dispatch|collect|abort`` (split out of ``cli``)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Literal

from ..output import emit_json, emit_status
from .collect import RoundRef, abort_round, collect_round
from .config import load_config
from .control import UsageRefusal
from .dispatch import DispatchRequest, plan_dispatch, refuse_role
from .models import JsonDict
from .refresh import refresh
from .store import TaskStore


def route(args: argparse.Namespace) -> int:
    """Run the handler of ``args.action``; a request that can never work exits 2."""
    handlers = {"dispatch": _dispatch, "collect": _collect, "abort": _abort}
    try:
        return handlers[args.action](args)
    except UsageRefusal as exc:
        emit_status("error", str(exc))
        return 2


def _prompt(args: argparse.Namespace) -> str:
    if args.prompt_file:
        return Path(args.prompt_file).read_text(encoding="utf-8")
    if args.prompt:
        return str(args.prompt)
    raise ValueError("Pass --prompt-file or --prompt")


def _dispatch(args: argparse.Namespace) -> int:
    store = TaskStore()
    task = store.get(args.task_id)
    refuse_role(task, args.role)
    config = load_config([Path(r["path"]) for r in task.repos])
    task, _risk = refresh(store, task, config)
    agent = {"agent": args.agent, "model": args.model} if args.agent else config.role(args.role)
    request = DispatchRequest(
        args.role,
        args.phase or task.phase,
        args.focus,
        _prompt(args),
        agent,
        rebuts=tuple(args.rebut),
    )
    plan = plan_dispatch(store, task, config, request)
    if args.json:
        emit_json(plan.argv)
        saved = f" with its JSON output saved to {plan.launch}"
    else:
        print(plan.line())
        saved = ""
    print(
        f"Round {plan.n:03d} reserved. Run the line above{saved}, end your turn, then: "
        f"taskflow round {task.id} collect --round {plan.n} --dispatch-id <ID from Orca>",
        file=sys.stderr,
    )
    return 0


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
