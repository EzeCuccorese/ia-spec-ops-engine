"""CLI for compact, durable cross-session task tracking."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table

from .resolver import TaskResolver
from .tracker import SessionTracker, TaskState

console = Console()


def show_task(
    task: TaskState, full_log: bool = False, tracker: SessionTracker | None = None
) -> None:
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
    parser = argparse.ArgumentParser(prog="progress", description="SpecOps task tracking")
    sub = parser.add_subparsers(dest="cmd")

    item = sub.add_parser("list", aliases=["listar"], help="List tasks")
    item.add_argument("--all", action="store_true", help="Include closed tasks")
    _add_json_flag(item)

    for name in ("show", "ver", "view"):
        item = sub.add_parser(name, help="View task state")
        item.add_argument("task_id", nargs="?")
        item.add_argument("--full", action="store_true")
        _add_json_flag(item)

    for name in ("here", "aqui"):
        item = sub.add_parser(name, help="Resolve task by branch or registered repository")
        item.add_argument("--full", action="store_true")
        _add_json_flag(item)

    for name in ("new", "nueva"):
        item = sub.add_parser(name, help="Create task")
        item.add_argument("task_id")
        item.add_argument("--title", "--titulo", required=True)
        item.add_argument("--summary", "--resumen", default="")

    for name in ("close", "cerrar", "reopen", "reabrir", "pause", "pausar"):
        item = sub.add_parser(name)
        item.add_argument("task_id")
        item.add_argument("--reason", "--razon", default="")

    for name in ("resume", "reanudar"):
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

    item = sub.add_parser("migrate-legacy", help="Import old progress-to-md state once")
    item.add_argument("path", type=Path)
    _add_json_flag(item)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        tracker = SessionTracker()
        if args.cmd in ("list", "listar") or not args.cmd:
            tasks = tracker.list_tasks(include_closed=getattr(args, "all", False))
            if getattr(args, "json", False):
                print(json.dumps([task.to_dict() for task in tasks], indent=2, ensure_ascii=False))
            else:
                table = Table(title="Tasks", border_style="cyan")
                table.add_column("Task ID")
                table.add_column("Title")
                table.add_column("Status")
                table.add_column("Summary")
                for task in tasks:
                    table.add_row(task.id, task.title, task.status, task.summary)
                console.print(table)
            return 0

        if args.cmd in ("here", "aqui"):
            target = TaskResolver.resolve_from_context(tracker.list_tasks(), Path.cwd())
        elif args.cmd in ("show", "ver", "view", "resume", "reanudar"):
            target = args.task_id or TaskResolver.resolve_from_context(
                tracker.list_tasks(), Path.cwd()
            )
        else:
            target = None

        if args.cmd in ("show", "ver", "view", "here", "aqui"):
            found_task = tracker.get_task(target) if target else None
            if not found_task:
                raise FileNotFoundError("No task matches the current context")
            task = found_task
            if args.json:
                data = task.to_dict()
                if args.full:
                    data["log"] = tracker.read_log(task.id)
                print(json.dumps(data, indent=2, ensure_ascii=False))
            else:
                show_task(task, args.full, tracker)
            return 0

        if args.cmd in ("new", "nueva"):
            task = tracker.create_task(
                TaskState(id=args.task_id, title=args.title, summary=args.summary)
            )
        elif args.cmd in ("close", "cerrar"):
            task = tracker.close_task(args.task_id, args.reason)
        elif args.cmd in ("reopen", "reabrir"):
            task = tracker.reopen_task(args.task_id, args.reason)
        elif args.cmd in ("pause", "pausar"):
            task = tracker.pause_task(args.task_id, args.reason)
        elif args.cmd in ("resume", "reanudar"):
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
            console.print(f"[green]Synced {len(ids)} task(s).[/green]")
            return 0
        elif args.cmd == "note":
            task = tracker.add_note(args.task_id, args.text)
        elif args.cmd == "digest":
            text = tracker.digest(args.task_id, args.max_chars)
            print(json.dumps({"digest": text}) if args.json else text)
            return 0
        elif args.cmd == "migrate-legacy":
            report = tracker.import_legacy_directory(args.path)
            if args.json:
                print(json.dumps(report, indent=2))
            else:
                print(
                    f"Imported {report['imported']}; skipped {report['skipped']}; "
                    f"invalid {report['invalid']}"
                )
            return 0
        else:
            parser.print_help()
            return 0

        console.print(f"[green]Updated task '{task.id}' ({task.status}).[/green]")
        return 0
    except (ValueError, OSError) as exc:
        prefix = (
            "Error creating task" if getattr(args, "cmd", None) in ("new", "nueva") else "Error"
        )
        console.print(f"[red]{prefix}: {exc}[/red]")
        return 1


if __name__ == "__main__":
    sys.exit(main())
