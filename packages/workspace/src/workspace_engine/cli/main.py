"""
workspace_engine.cli.main — Master unified entry point for the `ws` CLI.

Unifies workspace management operations into a single command:
  ws generate
  ws edit
  ws worktree
  ws clean
  ws stop
  ws reset
  ws delete
  ws build
  ws deps
  ws java
  ws env-init
  ws env-load
  ws benchmark
  ws run-local
  ws kube
  ws doctor
  ws hooks
"""

from __future__ import annotations

import argparse
import importlib
import json
import shutil
import sys

from workspace_engine.common import emit_rows, is_agent_mode


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
            status = "Available" if agent_mode else "[green]✓ Available[/green]"
            rows.append((tool, status, f"{desc} ({path})"))
        else:
            status = "Not Found" if agent_mode else "[yellow]⚠ Not Found[/yellow]"
            rows.append((tool, status, desc))

    from workspace_engine.services.git_hooks import get_hooks_status

    hooks_stat = get_hooks_status()
    if hooks_stat["local"]["is_active"] or hooks_stat["global"]["is_active"]:
        active_scope = (
            "Local & Global"
            if (hooks_stat["local"]["is_active"] and hooks_stat["global"]["is_active"])
            else ("Local" if hooks_stat["local"]["is_active"] else "Global")
        )
        status = "Active" if agent_mode else "[green]✓ Active[/green]"
        rows.append(("git-hooks", status, f"Pre-Push Quality Gate ({active_scope})"))
    else:
        status = "Inactive" if agent_mode else "[yellow]⚠ Inactive[/yellow]"
        rows.append(("git-hooks", status, "Run 'ws hooks install --global' to protect git push"))

    emit_rows(
        rows,
        headers=("Tool / Runtime", "Status", "Details"),
        title="Development Environment Diagnostics (ws doctor)",
        full=True,
    )


# Commands that own their argument parser: `ws <command> ...` forwards everything after the
# command name to `<module>.main(argv)`.
DELEGATED_COMMANDS = {
    "generate": (
        "workspace_engine.cli.generate_workspace",
        "Generate a new multi-repo workspace from Git worktrees",
    ),
    "worktree": (
        "workspace_engine.cli.create_worktree",
        "Create an isolated Git worktree",
    ),
    "edit": (
        "workspace_engine.cli.edit_workspace",
        "Add/remove repositories in the current workspace",
    ),
    "clean": (
        "workspace_engine.cli.clean_workspace",
        "Clean dependencies, caches, and build artifacts in workspace",
    ),
    "stop": (
        "workspace_engine.cli.stop_workspace",
        "Stop all running processes and services in workspace",
    ),
    "reset": (
        "workspace_engine.cli.reset_repos",
        "Reset workspace repositories to their branch point or a clean HEAD",
    ),
    "delete": (
        "workspace_engine.cli.delete_workspaces",
        "Delete workspaces and unregister associated worktrees",
    ),
    "build": (
        "workspace_engine.cli.build_project",
        "Build project auto-detecting the technology stack",
    ),
    "deps": (
        "workspace_engine.cli.install_deps",
        "Install workspace repository dependencies (Gradle, Maven, npm, uv, etc.)",
    ),
    "java": (
        "workspace_engine.cli.set_java",
        "Print the JAVA_HOME/PATH exports for the project's JDK via SDKMAN",
    ),
    "env-init": (
        "workspace_engine.cli.init_env",
        "Initialize or sync config/.env from its .env.example template",
    ),
    "env-load": (
        "workspace_engine.cli.load_env",
        "Update a variable across per-environment values.<env>.yaml files",
    ),
    "benchmark": (
        "workspace_engine.cli.unit_test_benchmark",
        "Execute parallel unit test benchmarks with visual reports",
    ),
    "run-local": (
        "workspace_engine.run_local.main",
        "Orchestrate and launch local microservices with live TUI",
    ),
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
        description="ia-spec-ops-engine — deterministic workspace, Git worktree & local microservices manager.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("-v", "--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", help="Available Workspace Engine commands")

    for name, (_, help_text) in DELEGATED_COMMANDS.items():
        subparsers.add_parser(name, help=help_text, add_help=False)

    p_kube = subparsers.add_parser(
        "kube", help="Kubernetes pod manager for environment extraction and shells"
    )
    p_kube.add_argument(
        "action", nargs="?", choices=["env", "logs", "shell"], help="Action to execute"
    )

    p_detect = subparsers.add_parser(
        "detect", help="Detect the repository technology stacks (deterministic)"
    )
    p_detect.add_argument("--dir", "-d", default=".", help="Repository root (defaults to cwd)")
    p_detect.add_argument("--json", action="store_true", help="Emit the versioned JSON contract")

    p_host_hook = subparsers.add_parser("hook", help="Run a coding-agent integration hook")
    p_host_hook.add_argument("hook_name", choices=["claude-worktree-create"])
    p_host_hook.add_argument("hook_args", nargs=argparse.REMAINDER)

    subparsers.add_parser(
        "doctor", help="Verify system tools, compilers, and development environment"
    )

    p_config = subparsers.add_parser("config", help="Initialize and manage workspace configuration")
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


def _run_hook(args: argparse.Namespace) -> None:
    if args.hook_name == "claude-worktree-create":
        from workspace_engine.integrations.claude.worktree_hook import main as hook_main

        sys.exit(hook_main(args.hook_args))


def _run_kube(args: argparse.Namespace) -> None:
    from workspace_engine.cli.kube.main import main as kube_main

    sys.exit(kube_main(args.action))


_BUILTIN_HANDLERS = {
    "detect": _run_detect,
    "config": _run_config,
    "doctor": lambda _args: doctor_check(),
    "hook": _run_hook,
    "kube": _run_kube,
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
