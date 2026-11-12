"""
workspace_engine.cli.main — Master unified entry point for the `ws` CLI.

Unifies deterministic workspace quality-gate and inspection operations into a single command:
  ws check
  ws changed
  ws design
  ws run
  ws condense
  ws log
  ws detect
  ws hooks
  ws config
  ws doctor
"""

from __future__ import annotations

import argparse
import importlib
import json
import shutil
import sys

from workspace_engine.common import emit_rows, is_agent_mode


def _hooks_doctor_row(*, agent_mode: bool) -> tuple[str, str, str]:
    from workspace_engine.services.git_hooks import get_hooks_status

    hooks_stat = get_hooks_status()
    local_active = bool(hooks_stat["local"]["is_active"])
    global_active = bool(hooks_stat["global"]["is_active"])
    if not (local_active or global_active):
        status = "Inactive" if agent_mode else "⚠ Inactive"
        return ("git-hooks", status, "Run 'ws hooks install --global' to protect git push")

    if local_active and global_active:
        active_scope = "Local & Global"
    else:
        active_scope = "Local" if local_active else "Global"
    status = "Active" if agent_mode else "✓ Active"
    return ("git-hooks", status, f"Pre-Push Quality Gate ({active_scope})")


def doctor_check() -> None:
    """Diagnoses development environment tools and runtimes."""
    agent_mode = is_agent_mode()
    rows: list[tuple[str, str, str]] = []

    tools = [
        ("git", "Git Version Control"),
        ("uv", "Fast Python Package Manager"),
        ("kubectl", "Kubernetes CLI Controller"),
        ("java", "Java Development Kit"),
        ("mvn", "Apache Maven Build Tool"),
        ("node", "Node.js JavaScript Runtime"),
        ("npm", "Node Package Manager"),
        ("docker", "Docker Container Engine"),
    ]

    for tool, desc in tools:
        path = shutil.which(tool)
        if path:
            status = "Available" if agent_mode else "✓ Available"
            rows.append((tool, status, f"{desc} ({path})"))
        else:
            status = "Not Found" if agent_mode else "⚠ Not Found"
            rows.append((tool, status, desc))

    rows.append(_hooks_doctor_row(agent_mode=agent_mode))

    emit_rows(
        rows,
        headers=("Tool / Runtime", "Status", "Details"),
        title="Development Environment Diagnostics (ws doctor)",
        full=True,
    )


# Commands that own their argument parser: `ws <command> ...` forwards everything after the
# command name to `<module>.main(argv)`.
DELEGATED_COMMANDS = {
    "hooks": (
        "workspace_engine.cli.manage_hooks:main",
        "Multi-stack Git Hooks & Quality Gates manager",
    ),
    "run": (
        "workspace_engine.condense.cli:run",
        "Run a command and print a condensed summary (ws run -- <cmd>)",
    ),
    "condense": (
        "workspace_engine.condense.cli:condense_stdin",
        "Condense command output read from stdin",
    ),
    "log": (
        "workspace_engine.condense.cli:show_log",
        "Read a saved full output (ws log <id> --grep RE)",
    ),
    "check": (
        "workspace_engine.cli.check:check",
        "Run the quality gate with condensed output (--changed, --cache, --json)",
    ),
    "changed": (
        "workspace_engine.cli.check:changed",
        "Files changed vs. the base branch (--json)",
    ),
    "design": (
        "workspace_engine.cli.design:design",
        "Design/complexity metrics per function (--changed, --files-from, --json)",
    ),
}


def _invoke_delegated(target: str, argv: list[str]) -> int | None:
    module_name, _, attr = target.partition(":")
    fn = getattr(importlib.import_module(module_name), attr or "main")
    result = fn(argv)
    return result if isinstance(result, int) else None


def _build_parser() -> argparse.ArgumentParser:
    from workspace_engine import __version__

    parser = argparse.ArgumentParser(
        prog="ws",
        description="ia-spec-ops-engine — deterministic quality gates, design limits, and command condensation.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("-v", "--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", help="Available Workspace Engine commands")

    for name, (_, help_text) in DELEGATED_COMMANDS.items():
        subparsers.add_parser(name, help=help_text, add_help=False)

    p_detect = subparsers.add_parser(
        "detect", help="Detect the repository technology stacks (deterministic)"
    )
    p_detect.add_argument("--dir", "-d", default=".", help="Repository root (defaults to cwd)")
    p_detect.add_argument("--json", action="store_true", help="Emit the versioned JSON contract")

    subparsers.add_parser(
        "doctor", help="Verify system tools, compilers, and development environment"
    )

    p_config = subparsers.add_parser("config", help="Inspect effective workspace configuration")
    from workspace_engine.config.init_config import add_config_arguments

    add_config_arguments(p_config)
    return parser


def _run_detect(args: argparse.Namespace) -> None:
    from workspace_engine.services.detect import detect_stacks

    detection = detect_stacks(args.dir)
    if args.json:
        print(json.dumps(detection.to_dict(), separators=(",", ":")))
    else:
        print(" ".join(detection.stacks) or "(no known stack detected)")
    sys.exit(0)


def _run_config(args: argparse.Namespace) -> None:
    from workspace_engine.config.init_config import run_config

    sys.exit(run_config(args))


_BUILTIN_HANDLERS = {
    "detect": _run_detect,
    "config": _run_config,
    "doctor": lambda _args: doctor_check(),
}


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] in DELEGATED_COMMANDS:
        target, _ = DELEGATED_COMMANDS[sys.argv[1]]
        code = _invoke_delegated(target, sys.argv[2:])
        if code is not None:
            sys.exit(code)
        return

    parser = _build_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    handler = _BUILTIN_HANDLERS.get(args.command)
    if handler:
        handler(args)


if __name__ == "__main__":
    main()
