"""
workspace_engine.cli.manage_hooks — CLI para gestión e instalación de Git Hooks multi-stack.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table

from devscripts_common import log_error, log_info, log_success, log_warning
from workspace_engine.services.git_hooks import (
    get_hooks_status,
    install_git_hooks,
    uninstall_git_hooks,
)

console = Console()


def render_hooks_status(target_dir: Path | None = None) -> None:
    """Muestra una tabla con el estado actual de los hooks locales y globales."""
    status = get_hooks_status(target_dir)

    table = Table(title="🛡️ Estado de Git Hooks & Quality Gate", border_style="cyan")
    table.add_column("Ámbito", style="bold magenta", justify="center")
    table.add_column("Ubicación del Hook", style="dim")
    table.add_column("core.hooksPath", style="bold")
    table.add_column("Permisos", justify="center")
    table.add_column("Estado Activo", justify="center")

    # Fila Local
    loc = status["local"]
    loc_perm = "[green]✓ Ejecutable[/green]" if loc["is_executable"] else ("[yellow]Sin exec[/yellow]" if loc["hook_exists"] else "[red]No instalado[/red]")
    loc_act = "[green]✓ ACTIVO[/green]" if loc["is_active"] else "[dim]Inactivo[/dim]"
    table.add_row(
        "Local (Repo)",
        loc["hook_path"],
        loc["configured_hooks_path"] or "[dim]No configurado[/dim]",
        loc_perm,
        loc_act,
    )

    # Fila Global
    glo = status["global"]
    glo_perm = "[green]✓ Ejecutable[/green]" if glo["is_executable"] else ("[yellow]Sin exec[/yellow]" if glo["hook_exists"] else "[red]No instalado[/red]")
    glo_act = "[green]✓ ACTIVO[/green]" if glo["is_active"] else "[dim]Inactivo[/dim]"
    table.add_row(
        "Global (Sistema)",
        glo["hook_path"],
        glo["configured_hooks_path"] or "[dim]No configurado[/dim]",
        glo_perm,
        glo_act,
    )

    console.print(table)


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
        if argv and argv[0] == "hooks":
            argv = argv[1:]

    parser = argparse.ArgumentParser(
        prog="ws hooks",
        description="Gestor de Git Hooks y Quality Gates Multi-Stack para Workspace Engine",
    )
    sub = parser.add_subparsers(dest="action", help="Acción a realizar")

    # install
    p_inst = sub.add_parser("install", help="Instalar hook pre-push multi-stack")
    p_inst.add_argument("--global", "-g", dest="is_global", action="store_true", help="Instalar globalmente en ~/.githooks")
    p_inst.add_argument("--dir", "-d", help="Directorio raíz del repositorio (por defecto cwd)")
    p_inst.add_argument("--force", "-f", action="store_true", default=True, help="Sobreescribir hooks existentes")

    # status
    p_stat = sub.add_parser("status", help="Consultar estado de los hooks locales y globales")
    p_stat.add_argument("--dir", "-d", help="Directorio raíz del repositorio")

    # uninstall
    p_uninst = sub.add_parser("uninstall", help="Desinstalar hook pre-push")
    p_uninst.add_argument("--global", "-g", dest="is_global", action="store_true", help="Desinstalar hook global")
    p_uninst.add_argument("--dir", "-d", help="Directorio raíz del repositorio")

    args = parser.parse_args(argv)

    if not args.action or args.action == "status":
        target = Path(getattr(args, "dir", None) or Path.cwd())
        render_hooks_status(target)
        return 0

    target = Path(args.dir) if getattr(args, "dir", None) else Path.cwd()

    if args.action == "install":
        res = install_git_hooks(target_dir=target, is_global=args.is_global, force=args.force)
        if res["success"]:
            log_success(res["message"])
            render_hooks_status(target)
            return 0
        else:
            log_warning(res["message"])
            return 1

    if args.action == "uninstall":
        res = uninstall_git_hooks(target_dir=target, is_global=args.is_global)
        log_info(res["message"])
        render_hooks_status(target)
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
