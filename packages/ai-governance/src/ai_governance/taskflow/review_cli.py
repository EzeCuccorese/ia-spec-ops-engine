"""Command handlers of ``taskflow review <id> open|judge|status|close``."""

from __future__ import annotations

import argparse
import shlex
import sys
from pathlib import Path

from ..output import emit_json, emit_rows, emit_status
from .config import FlowConfig, load_config
from .control import UsageRefusal
from .models import JsonDict
from .review import (
    OpenReviewOptions,
    ReviewDispatch,
    judge_review,
    open_review,
    review_status,
)
from .review_publish import EVENTS, PayloadRequest, write_payload
from .review_summary import close_review
from .store import TaskStore


def route(args: argparse.Namespace) -> int:
    """Run the handler of ``args.review_action``; an impossible request exits 2."""
    handlers = {"open": _open, "judge": _judge, "status": _status, "close": _close}
    handlers["payload"] = _payload
    try:
        return handlers[args.review_action](args)
    except UsageRefusal as exc:
        emit_status("error", str(exc))
        return 2


def _config(store: TaskStore, task_id: str) -> FlowConfig:
    return load_config([Path(r["path"]) for r in store.get(task_id).repos])


def _emit(args: argparse.Namespace, result: ReviewDispatch, next_action: str) -> None:
    for warning in result.warnings:
        print(f"WARN: {warning}", file=sys.stderr)
    if args.json:
        payload: JsonDict = {
            "review_id": result.review_id,
            "warnings": list(result.warnings),
            "rounds": [
                {
                    "pr": item.key,
                    "round": item.round.n,
                    "argv": item.round.argv,
                    "spec": str(item.round.spec),
                    "launch": str(item.round.launch) if item.round.launch else "",
                }
                for item in result.items
            ],
        }
        emit_json(payload)
    else:
        for item in result.items:
            print(item.round.line())
    rounds = ", ".join(f"{item.round.n:03d} ({item.key})" for item in result.items)
    print(
        f"Review #{result.review_id}: reserved rounds {rounds}. Run each line (they are "
        f"independent: start them together), end your turn, collect each with "
        f"`taskflow round {args.task_id} collect --round N --dispatch-id <ID>`, "
        f"then: taskflow review {args.task_id} {next_action}",
        file=sys.stderr,
    )


def _open(args: argparse.Namespace) -> int:
    store = TaskStore()
    opts = OpenReviewOptions(
        urls=tuple(args.pr), agent=args.agent, model=args.model or "", lens=args.lens or ""
    )
    result = open_review(store, args.task_id, _config(store, args.task_id), opts)
    _emit(args, result, "judge")
    return 0


def _judge(args: argparse.Namespace) -> int:
    store = TaskStore()
    result = judge_review(
        store, args.task_id, _config(store, args.task_id), args.agent or "", args.model or ""
    )
    _emit(args, result, "close")
    return 0


def _fmt_round(value: object) -> str:
    return f"{value:03d}" if isinstance(value, int) and not isinstance(value, bool) else "-"


def _status(args: argparse.Namespace) -> int:
    rows = review_status(TaskStore(), args.task_id)
    if args.json:
        emit_json(rows)
        return 0
    emit_rows(
        [
            (
                str(row["pr"]),
                str(row["head"]),
                _fmt_round(row["reviewer_round"]),
                str(row["reviewer_state"]),
                _fmt_round(row["judge_round"]),
                str(row["judge_state"]),
            )
            for row in rows
        ],
        headers=("pr", "head", "reviewer_round", "reviewer", "judge_round", "judge"),
        title=f"Review status of {args.task_id}",
        full=True,
    )
    return 0


def _close(args: argparse.Namespace) -> int:
    print(close_review(TaskStore(), args.task_id, partial=bool(args.partial)))
    return 0


def _finding_numbers(raw: str) -> tuple[int, ...]:
    parts = [part.strip() for part in raw.split(",") if part.strip()]
    if not all(part.isdigit() for part in parts):
        raise UsageRefusal(f"--include takes finding numbers separated by commas, not '{raw}'")
    return tuple(int(part) for part in parts)


def _payload(args: argparse.Namespace) -> int:
    request = PayloadRequest(args.pr, args.event, _finding_numbers(args.include or ""))
    made = write_payload(TaskStore(), args.task_id, request)
    print(shlex.join(made.command))
    print(
        f"Payload written to {made.path}: {made.inline} inline comment(s), {made.in_body} in "
        f"the review body, event {EVENTS[args.event]}. Nothing was sent. Show it to the owner, "
        f"record the approval (`taskflow approve {args.task_id} --action comment ...`) and "
        "only then run the line above.",
        file=sys.stderr,
    )
    return 0
