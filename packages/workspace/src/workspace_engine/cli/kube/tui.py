"""
workspace_engine.cli.kube.tui — Interfaz interactiva Rich TUI para Kubernetes.
"""

from __future__ import annotations

import sys
from typing import Any, Dict, List, Optional

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt, Confirm
from rich.table import Table

from workspace_engine.common import Color, log_info, log_warning, log_error

console = Console()


def select_context(contexts: List[Dict[str, Any]]) -> Optional[str]:
    """Muestra un picker interactivo con Rich para seleccionar el contexto de Kubernetes."""
    if not contexts:
        log_warning("No se encontraron contextos de kubectl configurados.")
        return None

    if len(contexts) == 1:
        return contexts[0]["name"]

    table = Table(title="Contextos Kubernetes Disponibles", border_style="cyan")
    table.add_column("#", justify="right", style="cyan", no_wrap=True)
    table.add_column("Nombre del Contexto", style="bold")
    table.add_column("Estado", justify="center")

    for idx, ctx in enumerate(contexts, 1):
        status = "[green]✓ Actual[/green]" if ctx["is_current"] else ""
        table.add_row(str(idx), ctx["name"], status)

    console.print(table)
    
    choice = Prompt.ask(
        "Selecciona el número del contexto",
        choices=[str(i) for i in range(1, len(contexts) + 1)],
        default="1",
    )
    return contexts[int(choice) - 1]["name"]


def select_operation() -> str:
    """Selecciona la operación K8s deseada (env, logs, shell)."""
    table = Table(title="Operaciones Kubernetes", border_style="magenta")
    table.add_column("#", justify="right", style="cyan")
    table.add_column("Operación", style="bold")
    table.add_column("Descripción")

    ops = [
        ("env", "Extraer variables de entorno (.env y set-env.sh)"),
        ("logs", "Ver logs en tiempo real de los pods"),
        ("shell", "Abrir shell interactivo dentro del pod"),
    ]

    for idx, (op, desc) in enumerate(ops, 1):
        table.add_row(str(idx), op, desc)

    console.print(table)
    choice = Prompt.ask(
        "Selecciona una operación",
        choices=[str(i) for i in range(1, len(ops) + 1)],
        default="1",
    )
    return ops[int(choice) - 1][0]
