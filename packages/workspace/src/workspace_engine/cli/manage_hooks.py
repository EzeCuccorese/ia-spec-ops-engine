"""
workspace_engine.cli.manage_hooks — CLI for multi-stack Git Hooks and Quality Gate management.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table

from workspace_engine.common import log_error, log_success
from workspace_engine.services.git_hooks import (
    get_hooks_status,
    install_git_hooks,
    run_quality_gate,
    uninstall_git_hooks,
)

console = Console()


def render_hooks_status(target_dir: Path | None = None) -> None:
    """Displays a status table for local and global Git hooks."""
    status = get_hooks_status(target_dir)

    table = Table(title="🛡️ Git Hooks & Quality Gate Status", border_style="cyan")
    table.add_column("Scope", style="bold magenta", justify="center")
    table.add_column("Hook Location", style="dim")
    table.add_column("core.hooksPath", style="bold")
    table.add_column("Permissions", justify="center")
    table.add_column("Active Status", justify="center")

    # Local Row
    loc = status["local"]
    loc_perm = (
        "[green]✓ Executable[/green]"
        if loc["is_executable"]
        else ("[yellow]No exec[/yellow]" if loc["hook_exists"] else "[red]Not installed[/red]")
    )
    loc_act = "[green]✓ ACTIVE[/green]" if loc["is_active"] else "[dim]Inactive[/dim]"
    table.add_row(
        "Local (Repo)",
        loc["hook_path"],
        loc["configured_hooks_path"] or "[dim]Not configured[/dim]",
        loc_perm,
        loc_act,
    )

    # Global Row
    glo = status["global"]
    glo_perm = (
        "[green]✓ Executable[/green]"
        if glo["is_executable"]
        else ("[yellow]No exec[/yellow]" if glo["hook_exists"] else "[red]Not installed[/red]")
    )
    glo_act = "[green]✓ ACTIVE[/green]" if glo["is_active"] else "[dim]Inactive[/dim]"
    table.add_row(
        "Global (System)",
        glo["hook_path"],
        glo["configured_hooks_path"] or "[dim]Not configured[/dim]",
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
        description="Multi-stack Git Hooks & Quality Gate Manager for Workspace Engine",
    )
    sub = parser.add_subparsers(dest="action", help="Action to perform")

    # install
    p_inst = sub.add_parser("install", help="Install multi-stack pre-push hook")
    p_inst.add_argument(
        "--global",
        "-g",
        dest="is_global",
        action="store_true",
        help="Install globally in ~/.githooks",
    )
    p_inst.add_argument("--dir", "-d", help="Repository root directory (defaults to cwd)")
    p_inst.add_argument(
        "--force", "-f", action="store_true", default=True, help="Overwrite existing hooks"
    )

    # status
    p_stat = sub.add_parser("status", help="Query local and global hook status")
    p_stat.add_argument("--dir", "-d", help="Repository root directory")

    # uninstall
    p_uninst = sub.add_parser("uninstall", help="Uninstall pre-push hook")
    p_uninst.add_argument(
        "--global", "-g", dest="is_global", action="store_true", help="Uninstall global hook"
    )
    p_uninst.add_argument("--dir", "-d", help="Repository root directory")

    # run
    p_run = sub.add_parser("run", help="Run the Quality Gate on-demand without git push")
    p_run.add_argument(
        "--scope",
        "-s",
        choices=["all", "changed"],
        default="all",
        help="Scope of linters and tests (all or changed)",
    )
    p_run.add_argument(
        "--skip",
        help="Comma-separated checks to skip (gitleaks,commits,lint,tests,repohooks)",
    )
    p_run.add_argument(
        "--timeout",
        "-t",
        type=int,
        default=900,
        help="Timeout in seconds per step (default: 900)",
    )
    p_run.add_argument(
        "--style",
        choices=["conventional"],
        help="Commit message style validation",
    )
    p_run.add_argument(
        "--output",
        choices=["errors", "verbose"],
        default="errors",
        help="Output mode: show failed commands only, or stream everything (default: errors)",
    )
    p_run.add_argument("--dir", "-d", help="Repository root directory")

    # test
    p_test = sub.add_parser("test", help="Test Quality Gate execution in current repository")
    p_test.add_argument("--dir", "-d", help="Repository root directory")

    args = parser.parse_args(argv)

    if not args.action or args.action == "status":
        target = Path(getattr(args, "dir", None) or Path.cwd())
        render_hooks_status(target)
        return 0

    target = Path(args.dir) if getattr(args, "dir", None) else Path.cwd()

    if args.action == "install":
        res = install_git_hooks(target_dir=target, is_global=args.is_global, force=args.force)
        if res["success"]:
            log_success(f"Git hook successfully installed at: {res['hook_path']}")
            return 0
        else:
            log_error(f"Error installing Git hook: {res.get('error')}")
            return 1

    elif args.action == "uninstall":
        res = uninstall_git_hooks(target_dir=target, is_global=args.is_global)
        if res["success"]:
            log_success("Git hook successfully uninstalled.")
            return 0
        else:
            log_error(f"Error uninstalling Git hook: {res.get('error')}")
            return 1

    elif args.action == "run":
        return run_quality_gate(
            target_dir=target,
            scope=args.scope,
            skip=args.skip,
            timeout=args.timeout,
            commit_style=args.style,
            output=args.output,
        )

    elif args.action == "test":
        return run_quality_gate(
            target_dir=target,
            scope="all",
            timeout=120,
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
