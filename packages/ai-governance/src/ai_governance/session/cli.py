"""
cli.py — CLI for `progress`: lightweight cross-session task tracking.
"""

from __future__ import annotations

import argparse
import sys

from rich.console import Console
from rich.table import Table

from .resolver import TaskResolver
from .tracker import SessionTracker, TaskState

console = Console()


def show_task(
    task: TaskState, full_log: bool = False, tracker: SessionTracker | None = None
) -> None:
    table = Table(title=f"📌 Task: {task.id} — {task.title}", border_style="cyan")
    table.add_column("Property", style="bold green")
    table.add_column("Details", style="white")

    table.add_row("Status", task.status)
    table.add_row("Summary", task.summary or "[dim]No summary[/dim]")

    if task.steps:
        steps_str = "\n".join(
            f"{'[green]✓[/green]' if s.get('done') else '[red]□[/red]'} {s.get('text')}"
            for s in task.steps
        )
        table.add_row("Steps", steps_str)

    if task.repos:
        repos_str = "\n".join(
            f"• {r.get('path', '')} (branch: {r.get('branch', 'main')})" for r in task.repos
        )
        table.add_row("Repositories", repos_str)

    console.print(table)

    if full_log and tracker:
        log = tracker.read_log(task.id)
        if log:
            console.print("\n[bold cyan]📖 Complete Log:[/bold cyan]")
            console.print(log)


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="progress", description="SpecOps Lightweight Session Tracking"
    )
    sub = parser.add_subparsers(dest="cmd")

    # list / listar
    sub.add_parser("list", help="List active tasks")
    sub.add_parser("listar", help=argparse.SUPPRESS)

    # show / ver
    for cmd_name in ("show", "ver", "view"):
        p_show = sub.add_parser(cmd_name, help="View task state")
        p_show.add_argument("task_id", nargs="?", help="Task ID or Jira ticket")
        p_show.add_argument("--full", action="store_true", help="Show complete log")

    # here / aqui
    for cmd_name in ("here", "aqui"):
        p_here = sub.add_parser(cmd_name, help="Resolve active task by current branch/directory")
        p_here.add_argument("--full", action="store_true", help="Show complete log")

    # new / nueva
    for cmd_name in ("new", "nueva"):
        p_new = sub.add_parser(cmd_name, help="Create new task")
        p_new.add_argument("task_id", help="Task ID or Jira ticket")
        p_new.add_argument("--title", "--titulo", dest="title", required=True, help="Task title")
        p_new.add_argument(
            "--summary", "--resumen", dest="summary", default="", help="Initial summary"
        )

    args = parser.parse_args()
    tracker = SessionTracker()

    if args.cmd in ("list", "listar") or not args.cmd:
        tasks = tracker.list_active_tasks()
        if not tasks:
            console.print("[yellow]No active tasks found.[/yellow]")
            return 0
        table = Table(title="📋 Active Tasks", border_style="cyan")
        table.add_column("Task ID", style="bold green")
        table.add_column("Title", style="white")
        table.add_column("Status", style="yellow")
        for t in tasks:
            table.add_row(t.id, t.title, t.status)
        console.print(table)
        return 0

    elif args.cmd in ("here", "aqui"):
        resolved = TaskResolver.resolve_from_git()
        if not resolved:
            console.print("[yellow]No Jira ticket detected on current branch.[/yellow]")
            return 1
        t = tracker.get_task(resolved)
        if not t:
            console.print(
                f"[yellow]Ticket detected ({resolved}), but no task has been created yet.[/yellow]"
            )
            return 1
        show_task(t, full_log=args.full, tracker=tracker)
        return 0

    elif args.cmd in ("show", "ver", "view"):
        target = args.task_id or TaskResolver.resolve_from_git()
        if not target:
            console.print(
                "[red]Specify a task_id or run within a branch containing a ticket.[/red]"
            )
            return 1
        try:
            t = tracker.get_task(target)
        except (ValueError, OSError) as e:
            console.print(f"[red]Error retrieving task '{target}': {e}[/red]")
            return 1
        if not t:
            console.print(f"[red]Task '{target}' not found.[/red]")
            return 1
        show_task(t, full_log=args.full, tracker=tracker)
        return 0

    elif args.cmd in ("new", "nueva"):
        try:
            t = TaskState(id=args.task_id, title=args.title, summary=args.summary)
            tracker.save_task(t)
            console.print(f"[green]✓ Task '{args.task_id}' created successfully.[/green]")
            return 0
        except (ValueError, OSError) as e:
            console.print(f"[red]Error creating task '{args.task_id}': {e}[/red]")
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
