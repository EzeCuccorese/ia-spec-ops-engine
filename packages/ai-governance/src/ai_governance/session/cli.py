"""CLI for compact, durable cross-session task tracking."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table

from ..output import emit_json, emit_kv, emit_rows, emit_status, emit_text, is_agent_mode
from .resolver import TaskResolver
from .tracker import SessionTracker, TaskState

console = Console()


def show_task(
    task: TaskState, full_log: bool = False, tracker: SessionTracker | None = None
) -> None:
    if is_agent_mode():
        pairs: list[tuple[str, str]] = [
            ("Status", task.status),
            ("Summary", task.summary or "No summary"),
        ]
        if task.steps:
            pairs.append(
                (
                    "Steps",
                    "; ".join(
                        f"{'✓' if s.get('done') else '□'} {s.get('text', '')}" for s in task.steps
                    ),
                )
            )
        if task.facts:
            pairs.append(("Facts", "; ".join(fact.get("text", "") for fact in task.facts)))
        if task.repos:
            pairs.append(
                (
                    "Repositories",
                    "; ".join(
                        f"{r.get('path', '')} (branch: {r.get('branch') or '?'})"
                        for r in task.repos
                    ),
                )
            )
        if task.links:
            pairs.append(
                (
                    "Links",
                    "; ".join(
                        f"{link.get('title', '')}: {link.get('url', '')}" for link in task.links
                    ),
                )
            )
        if task.references:
            pairs.append(
                (
                    "References",
                    "; ".join(
                        f"{ref.get('kind', '')}: {ref.get('value', '')}" for ref in task.references
                    ),
                )
            )
        emit_kv(pairs, title=f"Task: {task.id} — {task.title}", full=full_log)
        if full_log and tracker:
            log = tracker.read_log(task.id)
            if log:
                print("\nComplete Log:")
                print(log)
        return

    table = Table(title=f"Task: {task.id} — {task.title}", border_style="cyan")
    table.add_column("Property", style="bold green")
    table.add_column("Details", style="white")
    table.add_row("Status", task.status)
    table.add_row("Summary", task.summary or "[dim]No summary[/dim]")
    if task.steps:
        table.add_row(
            "Steps",
            "\n".join(f"{'✓' if s.get('done') else '□'} {s.get('text', '')}" for s in task.steps),
        )
    if task.facts:
        table.add_row("Facts", "\n".join(f"• {fact.get('text', '')}" for fact in task.facts))
    if task.repos:
        table.add_row(
            "Repositories",
            "\n".join(
                f"• {r.get('path', '')} (branch: {r.get('branch') or '?'})" for r in task.repos
            ),
        )
    if task.links:
        table.add_row(
            "Links",
            "\n".join(f"• {link.get('title', '')}: {link.get('url', '')}" for link in task.links),
        )
    if task.references:
        table.add_row(
            "References",
            "\n".join(
                f"• {ref.get('kind', '')}: {ref.get('value', '')}" for ref in task.references
            ),
        )
    console.print(table)
    if full_log and tracker:
        log = tracker.read_log(task.id)
        if log:
            console.print("\n[bold cyan]Complete Log:[/bold cyan]")
            console.print(log)


def _add_json_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ai-governance progress", description="Compact cross-session task tracking"
    )
    sub = parser.add_subparsers(dest="cmd")

    item = sub.add_parser("list", help="List tasks")
    item.add_argument("--all", action="store_true", help="Include closed tasks")
    _add_json_flag(item)

    for name in ("show",):
        item = sub.add_parser(name, help="View task state")
        item.add_argument("task_id", nargs="?")
        item.add_argument("--full", action="store_true")
        _add_json_flag(item)

    for name in ("here",):
        item = sub.add_parser(name, help="Resolve task by branch or registered repository")
        item.add_argument("--full", action="store_true")
        _add_json_flag(item)

    for name in ("new",):
        item = sub.add_parser(name, help="Create task")
        item.add_argument("task_id")
        item.add_argument("--title", required=True)
        item.add_argument("--summary", default="")

    for name in ("close", "reopen", "pause"):
        item = sub.add_parser(name)
        item.add_argument("task_id")
        item.add_argument("--reason", default="")

    for name in ("resume",):
        item = sub.add_parser(name)
        item.add_argument("task_id", nargs="?")
        item.add_argument("--full", action="store_true")

    item = sub.add_parser("summary", help="Replace the compact summary")
    item.add_argument("task_id")
    item.add_argument("text")

    item = sub.add_parser("step", help="Add, complete, or remove a step")
    item.add_argument("task_id")
    item.add_argument("action", choices=("add", "done", "remove"))
    item.add_argument("value")

    item = sub.add_parser("fact", help="Record a verified fact")
    item.add_argument("task_id")
    item.add_argument("text")

    item = sub.add_parser("link", help="Add a titled URL")
    item.add_argument("task_id")
    item.add_argument("title")
    item.add_argument("url")

    item = sub.add_parser("reference", help="Add an external reference")
    item.add_argument("task_id")
    item.add_argument("kind")
    item.add_argument("value")
    item.add_argument("--url", default="")

    item = sub.add_parser("repo", help="Add or remove a repository")
    item.add_argument("task_id")
    item.add_argument("action", choices=("add", "remove"))
    item.add_argument("path", nargs="?", default=".")
    item.add_argument("--branch", default="")
    item.add_argument("--pr", default="")
    item.add_argument("--worktree", default="")

    item = sub.add_parser("sync", help="Refresh registered repository branches")
    item.add_argument("task_id", nargs="?")

    item = sub.add_parser("note", help="Append to the long log")
    item.add_argument("task_id")
    item.add_argument("text")

    item = sub.add_parser("digest", help="Render compact task context")
    item.add_argument("--id", dest="task_id")
    item.add_argument("--max-chars", type=int, default=1600)
    _add_json_flag(item)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        tracker = SessionTracker()
        if args.cmd == "list" or not args.cmd:
            tasks = tracker.list_tasks(include_closed=getattr(args, "all", False))
            if getattr(args, "json", False):
                emit_json([task.to_dict() for task in tasks])
            else:
                emit_rows(
                    [(task.id, task.title, task.status, task.summary) for task in tasks],
                    headers=("Task ID", "Title", "Status", "Summary"),
                    title="Tasks",
                    more_hint="progress list --json",
                )
            return 0

        if args.cmd == "here":
            target = TaskResolver.resolve_from_context(tracker.list_tasks(), Path.cwd())
        elif args.cmd in ("show", "resume"):
            target = args.task_id or TaskResolver.resolve_from_context(
                tracker.list_tasks(), Path.cwd()
            )
        else:
            target = None

        if args.cmd in ("show", "here"):
            found_task = tracker.get_task(target) if target else None
            if not found_task:
                raise FileNotFoundError("No task matches the current context")
            task = found_task
            if args.json:
                data = task.to_dict()
                if args.full:
                    data["log"] = tracker.read_log(task.id)
                emit_json(data)
            else:
                show_task(task, args.full, tracker)
            return 0

        if args.cmd == "new":
            task = tracker.create_task(
                TaskState(id=args.task_id, title=args.title, summary=args.summary)
            )
        elif args.cmd == "close":
            task = tracker.close_task(args.task_id, args.reason)
        elif args.cmd == "reopen":
            task = tracker.reopen_task(args.task_id, args.reason)
        elif args.cmd == "pause":
            task = tracker.pause_task(args.task_id, args.reason)
        elif args.cmd == "resume":
            if not target:
                raise FileNotFoundError("No task matches the current context")
            task = tracker.resume_task(target)
        elif args.cmd == "summary":
            task = tracker.update_summary(args.task_id, args.text)
        elif args.cmd == "step":
            operation = {
                "add": tracker.add_step,
                "done": tracker.complete_step,
                "remove": tracker.remove_step,
            }[args.action]
            task = operation(args.task_id, args.value)
        elif args.cmd == "fact":
            task = tracker.add_fact(args.task_id, args.text)
        elif args.cmd == "link":
            task = tracker.add_link(args.task_id, args.title, args.url)
        elif args.cmd == "reference":
            task = tracker.add_reference(args.task_id, args.kind, args.value, args.url)
        elif args.cmd == "repo":
            if args.action == "add":
                task = tracker.add_repository(
                    args.task_id,
                    Path(args.path),
                    branch=args.branch,
                    pr=args.pr,
                    worktree=args.worktree,
                )
            else:
                task = tracker.remove_repository(args.task_id, Path(args.path))
        elif args.cmd == "sync":
            ids = [args.task_id] if args.task_id else [item.id for item in tracker.list_tasks()]
            for task_id in ids:
                tracker.sync_repositories(task_id, TaskResolver._git_branch)
            emit_status("ok", f"Synced {len(ids)} task(s)")
            return 0
        elif args.cmd == "note":
            task = tracker.add_note(args.task_id, args.text)
        elif args.cmd == "digest":
            text = tracker.digest(args.task_id, args.max_chars)
            if args.json:
                emit_json({"digest": text})
            else:
                emit_text(text, full=True)
            return 0
        else:
            parser.print_help()
            return 0

        emit_status("ok", f"Updated task '{task.id}' ({task.status})")
        return 0
    except (ValueError, OSError) as exc:
        prefix = "Error creating task" if getattr(args, "cmd", None) == "new" else "Error"
        emit_status("error", f"{prefix}: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
