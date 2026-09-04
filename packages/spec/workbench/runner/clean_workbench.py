#!/usr/bin/env python3
"""Cleanup Runner for SDD Agent Workbench.

Restores packages/sdd-workbench/test-sdd to a pristine, clean, default state.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm
from rich.table import Table

console = Console()
WORKBENCH_DIR = Path(__file__).resolve().parent.parent
TARGET_PROJECT = WORKBENCH_DIR / "test-sdd"

# Add engine src to path
SPEC_SRC = Path(__file__).resolve().parent.parent.parent / "src"
sys.path.insert(0, str(SPEC_SRC))

from spec.governance.project import ProjectGovernance


def clean_project(force: bool = False, verbose: bool = True) -> None:
    if verbose:
        table = Table.grid(expand=True)
        table.add_column(justify="left")
        table.add_column(justify="right")
        table.add_row(
            "[bold cyan]🧹 SDD WORKBENCH CLEANER[/bold cyan]",
            "[bold green]Status: [RESET][/bold green]",
        )
        console.print(Panel(table, box=box.ROUNDED, style="cyan"))
        console.print(f"[bold]Target Project to reset:[/bold] {TARGET_PROJECT}")

    if not force:
        proceed = Confirm.ask(
            "\n¿Confirmas limpiar todo el código generado, reportes de Gradle y especificaciones activas para dejar el entorno 100% prístino?",
            default=True,
        )
        if not proceed:
            console.print("[yellow]Limpieza cancelada.[/yellow]")
            return

    # 1. Clean Java sources
    src_dir = TARGET_PROJECT / "src"
    if src_dir.exists():
        shutil.rmtree(src_dir)
        if verbose:
            console.print("[green]✔ Directorio src/ eliminado.[/green]")

    # 2. Clean Gradle build artifacts
    for d in ["build", ".gradle"]:
        p = TARGET_PROJECT / d
        if p.exists():
            shutil.rmtree(p)
            if verbose:
                console.print(f"[green]✔ Artefactos {d}/ eliminados.[/green]")

    # 3. Clean Spec runtime state & specs
    spec_dir = TARGET_PROJECT / ".spec"
    if spec_dir.exists():
        for item in ["specs", "evidence"]:
            p = spec_dir / item
            if p.exists():
                shutil.rmtree(p)
                if verbose:
                    console.print(f"[green]✔ .spec/{item}/ eliminado.[/green]")
        state_file = spec_dir / "state.json"
        if state_file.exists():
            state_file.unlink()
            if verbose:
                console.print("[green]✔ .spec/state.json reseteado a reposo (IDLE).[/green]")

    # 4. Re-ensure base verification.json & policy.json exist
    ProjectGovernance(TARGET_PROJECT).initialize()
    v_config = spec_dir / "verification.json"
    if not v_config.exists() or v_config.read_text().strip() in ('{"schema_version": 1, "checks": []}', ""):
        v_config.write_text(
            '{\n  "schema_version": 1,\n  "checks": [\n    {\n      "id": "gradle-test",\n      "command": ["./gradlew", "test", "--no-daemon", "-q"],\n      "required": true\n    }\n  ]\n}\n',
            encoding="utf-8",
        )
        if verbose:
            console.print("[green]✔ .spec/verification.json restaurado con ./gradlew test.[/green]")

    if verbose:
        console.print(
            Panel(
                "[bold green]✨ El entorno test-sdd ha quedado 100% limpio, por defecto y prístino para la próxima ejecución.[/bold green]",
                box=box.ROUNDED,
                style="green",
            )
        )


if __name__ == "__main__":
    force_flag = "--force" in sys.argv or "-f" in sys.argv
    clean_project(force=force_flag)
