"""CLI for install / uninstall / update / status / doctor / agents."""

from __future__ import annotations

import argparse
from pathlib import Path

from .. import corporate
from ..output import emit_rows, emit_status, emit_text
from ..rules.catalog import RuleCatalog
from . import doctor
from .agents import AGENTS, capability_table
from .budget import BYTES_PER_TOKEN, fixed_cost
from .engine import Ledger, Report
from .installer import (
    PROJECT_DIR,
    ProjectConfig,
    forget_project,
    global_ledger,
    install_user,
    is_project_installed,
    registered_projects,
    sync_project,
    uninstall_user,
)


def _emit(report: Report, *, dry_run: bool) -> None:
    prefix = "[dry-run] " if dry_run else ""
    emit_text("\n".join(prefix + line for line in report.lines()), full=True)


def _add_common(parser: argparse.ArgumentParser, *, agent_required: bool = False) -> None:
    parser.add_argument(
        "--scope",
        choices=("user", "project"),
        default="project",
        help="Where to install or uninstall from",
    )
    parser.add_argument(
        "--agent",
        action="append",
        choices=sorted(AGENTS),
        required=agent_required,
        help="Target agent (repeatable). Only the chosen agents are touched.",
    )
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="Project root")
    parser.add_argument("--dry-run", action="store_true", help="Show the plan without writing")
    parser.add_argument(
        "--profile",
        action="append",
        choices=sorted(RuleCatalog().profiles),
        help="Opt-in rule profile (repeatable). Only valid with --scope project.",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ai-governance", add_help=False)
    sub = parser.add_subparsers(dest="cmd")
    install = sub.add_parser("install", help="Install for the chosen agent(s)")
    _add_common(install)
    install.add_argument("--force", action="store_true", help="Replace files we do not own")
    install.add_argument(
        "--corporate",
        help="Company packs to install, comma separated (default: every pack present)",
    )
    uninstall = sub.add_parser("uninstall", help="Remove what was installed for the agent(s)")
    _add_common(uninstall)
    update = sub.add_parser("update", help="Refresh project rules for the detected stacks")
    update.add_argument("--root", type=Path, default=Path.cwd())
    update.add_argument("--all", action="store_true", help="Every registered project")
    update.add_argument("--dry-run", action="store_true")
    update.add_argument("--check", action="store_true", help="Exit 1 if anything is out of date")
    status = sub.add_parser("status", help="What is installed where")
    status.add_argument("--root", type=Path, default=Path.cwd())
    doc = sub.add_parser("doctor", help="Read-only health checks")
    doc.add_argument("--root", type=Path, default=Path.cwd())
    sub.add_parser("agents", help="Capability matrix of supported agents")
    budget = sub.add_parser("budget", help="Fixed context loaded per agent every session")
    budget.add_argument("--root", type=Path, default=Path.cwd())
    return parser


def _scope_error(args: argparse.Namespace) -> str | None:
    if args.profile and args.scope != "project":
        return "--profile is only valid with --scope project."
    return None


def _selected_agents(args: argparse.Namespace) -> list[str]:
    """`uninstall --profile` without `--agent` touches no agent at all."""
    if args.cmd == "uninstall" and not args.agent and args.profile:
        return []
    if not args.agent:
        raise ValueError("Choose the agent(s) explicitly: --agent claude|codex|antigravity")
    return list(args.agent)


def _user_report(args: argparse.Namespace, agents: list[str]) -> Report:
    if args.cmd == "install":
        names = corporate.selected_names(args.corporate)
        try:
            corporate.packs(only=names)
        except ValueError as exc:
            raise SystemExit(f"Error: {exc}") from exc
        return install_user(agents, dry_run=args.dry_run, force=args.force, corporate_names=names)
    return uninstall_user(agents, dry_run=args.dry_run)


def _project_report(args: argparse.Namespace, agents: list[str]) -> Report:
    profiles = tuple(args.profile or ())
    if args.cmd == "install":
        return sync_project(
            args.root,
            add_agents=agents,
            add_profiles=profiles,
            dry_run=args.dry_run,
            force=args.force,
        )
    return sync_project(
        args.root, remove_agents=agents, remove_profiles=profiles, dry_run=args.dry_run
    )


def _install_or_uninstall(args: argparse.Namespace) -> int:
    error = _scope_error(args)
    if error:
        emit_status("error", error)
        return 2
    agents = _selected_agents(args)
    report = _user_report(args, agents) if args.scope == "user" else _project_report(args, agents)
    _emit(report, dry_run=args.dry_run)
    return 0


def _update_root(root: Path, *, forget: bool, dry_run: bool, heading: bool) -> bool:
    """Refreshes one project; returns whether anything was (or would be) changed."""
    if not is_project_installed(root):
        if forget:
            forget_project(root, dry_run=dry_run)
            emit_status("warn", f"{root}: no longer installed; removed from registry")
        else:
            emit_status("warn", f"{root}: not installed; run `ai-governance install`")
        return False
    report = sync_project(root, dry_run=dry_run)
    if heading:
        emit_text(f"# {root}", full=True)
    _emit(report, dry_run=dry_run)
    return report.changed


def _update(args: argparse.Namespace) -> int:
    roots = registered_projects() if args.all else [args.root]
    dry_run = args.dry_run or args.check
    changed = [
        _update_root(root, forget=args.all, dry_run=dry_run, heading=len(roots) > 1)
        for root in roots
    ]
    return 1 if args.check and any(changed) else 0


def _status(args: argparse.Namespace) -> int:
    rows = [("user", e["agent"], e["kind"], e["path"]) for e in global_ledger().entries]
    if is_project_installed(args.root):
        config = ProjectConfig.load(args.root)
        rows.append(("project", ",".join(config.agents), "config", PROJECT_DIR))
        lock = Ledger(args.root / PROJECT_DIR / "lock.json", base=args.root)
        rows.extend(("project", e["agent"], e["kind"], e["path"]) for e in lock.entries)
    emit_rows(rows, headers=("Scope", "Owner", "Kind", "Path"), full=True)
    return 0


def _doctor(args: argparse.Namespace) -> int:
    checks = doctor.check(args.root.resolve())
    emit_rows(checks, headers=("Check", "Status", "Detail"), full=True)
    return 1 if any(status == doctor.FAIL for _, status, _ in checks) else 0


def _budget(args: argparse.Namespace) -> int:
    ledgers = [("user", global_ledger())]
    if (args.root / PROJECT_DIR / "lock.json").exists():
        ledgers.append(("project", Ledger(args.root / PROJECT_DIR / "lock.json", base=args.root)))
    rows = [
        (scope, agent, str(size), f"~{size // BYTES_PER_TOKEN} tokens")
        for scope, ledger in ledgers
        for agent, size in sorted(fixed_cost(ledger).items())
    ]
    emit_rows(rows, headers=("Scope", "Owner", "Bytes", "Tokens"), full=True)
    return 0


def _agents(args: argparse.Namespace) -> int:
    emit_text(capability_table(), full=True)
    return 0


COMMANDS = {
    "install": _install_or_uninstall,
    "uninstall": _install_or_uninstall,
    "update": _update,
    "status": _status,
    "doctor": _doctor,
    "budget": _budget,
    "agents": _agents,
}


def main(command: str, argv: list[str]) -> int:
    args = build_parser().parse_args([command, *argv])
    handler = COMMANDS.get(args.cmd)
    if handler is None:
        return 0
    try:
        return handler(args)
    except (ValueError, OSError) as exc:
        emit_status("error", str(exc))
        return 1
