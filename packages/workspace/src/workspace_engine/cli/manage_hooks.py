"""
workspace_engine.cli.manage_hooks — CLI for multi-stack Git Hooks and Quality Gate management.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from workspace_engine.common import emit_rows, is_agent_mode, log_error, log_success
from workspace_engine.services.git_hooks import (
    get_hooks_status,
    install_git_hooks,
    run_quality_gate,
    uninstall_git_hooks,
)


def _scope_row(
    label: str, scope_status: dict[str, object], *, agent_mode: bool
) -> tuple[str, str, str, str, str]:
    hook_exists = bool(scope_status["hook_exists"])
    is_executable = bool(scope_status["is_executable"])
    is_active = bool(scope_status["is_active"])
    configured_command = scope_status["configured_command"] or (
        "Not configured" if agent_mode else "[dim]Not configured[/dim]"
    )

    if agent_mode:
        perm = "Executable" if is_executable else ("No exec" if hook_exists else "Not installed")
        active = "ACTIVE" if is_active else "Inactive"
    else:
        perm = (
            "[green]✓ Executable[/green]"
            if is_executable
            else ("[yellow]No exec[/yellow]" if hook_exists else "[red]Not installed[/red]")
        )
        active = "[green]✓ ACTIVE[/green]" if is_active else "[dim]Inactive[/dim]"

    return (label, str(scope_status["hook_path"]), str(configured_command), perm, active)


def render_hooks_status(target_dir: Path | None = None) -> None:
    """Displays a status table for local and global Git hooks."""
    status = get_hooks_status(target_dir)
    agent_mode = is_agent_mode()

    rows = [
        _scope_row("Local (Repo)", status["local"], agent_mode=agent_mode),
        _scope_row("Global (System)", status["global"], agent_mode=agent_mode),
    ]
    emit_rows(
        rows,
        headers=(
            "Scope",
            "Hook Location",
            "hook.workspace-gate.command",
            "Permissions",
            "Active Status",
        ),
        title="Git Hooks & Quality Gate Status",
        full=True,
    )


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
        help="Register globally (git config --global hook.workspace-gate.*)",
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
        help="Comma-separated checks to skip (gitleaks,commits,lint,design,tests,repohooks)",
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
