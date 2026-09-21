"""
workspace_engine.cli.kube.tui — Interactive Rich TUI interface for Kubernetes.
"""

from __future__ import annotations

from typing import Any

from rich.console import Console
from rich.prompt import Prompt
from rich.table import Table

from workspace_engine.common import log_warning

console = Console()


def select_context(contexts: list[dict[str, Any]]) -> str | None:
    """Shows an interactive Rich picker to select the Kubernetes context."""
    if not contexts:
        log_warning("No configured kubectl contexts found.")
        return None

    if len(contexts) == 1:
        return contexts[0]["name"]

    table = Table(title="Available Kubernetes Contexts", border_style="cyan")
    table.add_column("#", justify="right", style="cyan", no_wrap=True)
    table.add_column("Context Name", style="bold")
    table.add_column("Status", justify="center")

    for idx, ctx in enumerate(contexts, 1):
        status = "[green]✓ Current[/green]" if ctx["is_current"] else ""
        table.add_row(str(idx), ctx["name"], status)

    console.print(table)

    choice = Prompt.ask(
        "Select the context number",
        choices=[str(i) for i in range(1, len(contexts) + 1)],
        default="1",
    )
    return contexts[int(choice) - 1]["name"]


def select_operation() -> str:
    """Selects the desired K8s operation (env, logs, shell)."""
    table = Table(title="Kubernetes Operations", border_style="magenta")
    table.add_column("#", justify="right", style="cyan")
    table.add_column("Operation", style="bold")
    table.add_column("Description")

    ops = [
        ("env", "Extract environment variables (.env and set-env.sh)"),
        ("logs", "View real-time logs from the pods"),
        ("shell", "Open an interactive shell inside the pod"),
    ]

    for idx, (op, desc) in enumerate(ops, 1):
        table.add_row(str(idx), op, desc)

    console.print(table)
    choice = Prompt.ask(
        "Select an operation",
        choices=[str(i) for i in range(1, len(ops) + 1)],
        default="1",
    )
    return ops[int(choice) - 1][0]
