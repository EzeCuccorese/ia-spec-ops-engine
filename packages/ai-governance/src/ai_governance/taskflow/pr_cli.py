"""``taskflow pr add|rm|sync|list``: handlers (wired in ``parser``).

Registration is the only thing written to a task; status lives in the global cache and is read
from GitHub by code, so no model ever reads or interprets it."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ..output import emit_json, emit_rows, emit_status, emit_text
from . import cli
from .models import Task, now_iso
from .prs import board as pr_board
from .prs.origin import infer_repo
from .prs.refs import PrRef, extract, scan
from .prs.registry import AddMeta, add_refs, remove_ref
from .prs.status import summarize
from .prs.text import safe_text


def _refs(args: argparse.Namespace, task: Task) -> tuple[list[PrRef], bool]:
    """The PRs named in the arguments (``-`` reads stdin) and whether they came from stdin."""
    piped = "-" in args.refs
    text = " ".join(sys.stdin.read() if ref == "-" else ref for ref in args.refs)
    repo = args.repo or None
    if repo is None and scan(text).bare_skipped:
        repo = infer_repo([Path(r["path"]) for r in task.repos]) or None
    refs = extract(text, repo)
    if not refs:
        raise ValueError("no pull request found in the input (URL, owner/name#N or #N)")
    return refs, piped


def cmd_pr_add(args: argparse.Namespace) -> int:
    store = cli._store()
    task_id = cli._resolve(store, args.task_id)
    refs, piped = _refs(args, store.get(task_id))
    meta = AddMeta(args.group, "paste" if piped else "cli", now_iso())
    added = [0]

    def change(task: Task) -> None:
        added[0] = add_refs(task, refs, meta)

    store.mutate(task_id, change)
    emit_status("ok", f"{added[0]} new, {len(refs) - added[0]} already in '{task_id}'")
    return 0


def cmd_pr_rm(args: argparse.Namespace) -> int:
    store = cli._store()
    task_id = cli._resolve(store, args.task_id)
    refs, _ = _refs(args, store.get(task_id))
    removed = [0]

    def change(task: Task) -> None:
        removed[0] = sum(remove_ref(task, ref) for ref in refs)

    store.mutate(task_id, change)
    emit_status("ok", f"Removed {removed[0]} of {len(refs)} from '{task_id}'")
    return 0


def cmd_pr_sync(args: argparse.Namespace) -> int:
    store = cli._store()
    task_id = cli._resolve(store, args.task_id)
    failed = pr_board.sync(store, task_id)
    summary = pr_board.summary_for(store, task_id) or "no pull requests registered"
    if failed:
        emit_status("error", f"{summary} ({failed} sync error(s))")
        return 1
    emit_status("ok", summary)
    return 0


def _age(seconds: int | None) -> str:
    if seconds is None:
        return "never"
    for limit, unit, size in ((120, "s", 1), (7200, "m", 60), (172800, "h", 3600)):
        if seconds < limit:
            return f"{seconds // size}{unit}"
    return f"{seconds // 86400}d"


def _row(item: pr_board.Item, many_tasks: bool) -> tuple[str, ...]:
    ev, snap = item.evaluation, item.evaluation.snapshot
    status = "ready" if ev.ready else ", ".join(ev.blockers) or "-"
    cells = (
        safe_text(item.reg.group, 40) or "-",
        f"{item.reg.ref.repo}#{item.reg.ref.number}",
        ev.state,
        status + (" (stale)" if ev.stale else ""),
        _age(ev.age_s),
        safe_text(snap.title) if snap else safe_text(ev.error, 40),
    )
    return (item.holder, *cells) if many_tasks else cells


def cmd_pr_list(args: argparse.Namespace) -> int:
    store = cli._store()
    task_id = cli._resolve(store, args.task_id)
    if args.sync:
        pr_board.sync(store, task_id)
    data = pr_board.board(store, task_id)
    items = [i for i in data.items if not args.blocked or i.evaluation.blockers]
    if args.json:
        emit_json([pr_board.as_json(item) for item in items])
    else:
        _print_board(data, items)
    return 0


def _print_board(data: pr_board.Board, items: list[pr_board.Item]) -> None:
    many = len({item.holder for item in items}) > 1
    headers = ("Group", "PR", "State", "Status", "Age", "Title")
    emit_rows(
        [_row(item, many) for item in items],
        headers=(("Task", *headers) if many else headers),
        title=summarize([i.evaluation for i in data.items]) or "No pull requests registered",
        more_hint="taskflow pr list --json",
    )
    if data.bare_skipped:
        emit_text(f"{data.bare_skipped} bare #N in legacy sources skipped (no repository)")
