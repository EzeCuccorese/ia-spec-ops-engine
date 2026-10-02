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


CONDENSE_COMMANDS = ("run", "condense", "log", "check", "changed", "design")

# Commands that own their argument parser: `ws <command> ...` forwards everything after the
# command name to `<module>.main(argv)`.
DELEGATED_COMMANDS = {
    "generate": (
        "workspace_engine.cli.generate_workspace",
        "Generate a new multi-repo workspace from Git worktrees",
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
}


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] in DELEGATED_COMMANDS:
        module_name, _ = DELEGATED_COMMANDS[sys.argv[1]]
        importlib.import_module(module_name).main(sys.argv[2:])
        return

    if len(sys.argv) > 1 and sys.argv[1] in CONDENSE_COMMANDS:
        from workspace_engine.cli import check as check_cli
        from workspace_engine.cli import design as design_cli
        from workspace_engine.condense import cli as condense_cli

        handler = {
            "run": condense_cli.run,
            "condense": condense_cli.condense_stdin,
            "log": condense_cli.show_log,
            "check": check_cli.check,
            "changed": check_cli.changed,
            "design": design_cli.design,
        }[sys.argv[1]]
        sys.exit(handler(sys.argv[2:]))

    parser = argparse.ArgumentParser(
        prog="ws",
        description="ia-spec-ops-engine — deterministic workspace, Git worktree & local microservices manager.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", help="Available Workspace Engine commands")

    for name, (_, help_text) in DELEGATED_COMMANDS.items():
        subparsers.add_parser(name, help=help_text)

    # ws worktree
    p_wt = subparsers.add_parser("worktree", help="Create an isolated Git worktree")
    p_wt.add_argument("repo", help="Base repository path or name")
    p_wt.add_argument("target", help="Target path for new worktree")
    p_wt.add_argument("branch", help="Branch name to associate")

    # ws kube
    p_kube = subparsers.add_parser(
        "kube", help="Kubernetes pod manager for environment extraction and shells"
    )
    p_kube.add_argument(
        "action", nargs="?", choices=["env", "logs", "shell"], help="Action to execute"
    )

    # ws hooks
    p_hooks = subparsers.add_parser("hooks", help="Multi-stack Git Hooks & Quality Gates manager")
    p_hooks.add_argument(
        "hook_args", nargs=argparse.REMAINDER, help="Subcommand and options for ws hooks"
    )

    # ws hook (host integration hooks)
    subparsers.add_parser(
        "run", help="Run a command and print a condensed summary (ws run -- <cmd>)"
    )
    subparsers.add_parser("condense", help="Condense command output read from stdin")
    subparsers.add_parser("log", help="Read a saved full output (ws log <id> --grep RE)")
    subparsers.add_parser(
        "check", help="Run the quality gate with condensed output (--changed, --cache, --json)"
    )
    subparsers.add_parser("changed", help="Files changed vs. the base branch (--json)")
    subparsers.add_parser(
        "design", help="Design/complexity metrics per function (--changed, --files-from, --json)"
    )
    p_detect = subparsers.add_parser(
        "detect", help="Detect the repository technology stacks (deterministic)"
    )
    p_detect.add_argument("--dir", "-d", default=".", help="Repository root (defaults to cwd)")
    p_detect.add_argument("--json", action="store_true", help="Emit the versioned JSON contract")

    p_host_hook = subparsers.add_parser("hook", help="Run a coding-agent integration hook")
    p_host_hook.add_argument("hook_name", choices=["claude-worktree-create"])
    p_host_hook.add_argument("hook_args", nargs=argparse.REMAINDER)

    # ws doctor
    subparsers.add_parser(
        "doctor", help="Verify system tools, compilers, and development environment"
    )

    # ws config
    p_config = subparsers.add_parser("config", help="Initialize and manage workspace configuration")
    from workspace_engine.config.init_config import add_config_arguments

    add_config_arguments(p_config)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    # Delegate to corresponding modules
    if args.command == "detect":
        from workspace_engine.services.detect import detect_stacks

        detection = detect_stacks(args.dir)
        if args.json:
            print(json.dumps(detection.to_dict(), separators=(",", ":")))
        else:
            print(" ".join(detection.stacks) or "(no known stack detected)")
        sys.exit(0)
    elif args.command == "config":
        from workspace_engine.config.init_config import run_config

        sys.exit(run_config(args))
    elif args.command == "doctor":
        doctor_check()
    elif args.command == "hooks":
        from workspace_engine.cli.manage_hooks import main as hooks_main

        sys.exit(hooks_main(args.hook_args))
    elif args.command == "hook":
        if args.hook_name == "claude-worktree-create":
            from workspace_engine.integrations.claude.worktree_hook import main as hook_main

            sys.exit(hook_main(args.hook_args))
    elif args.command == "worktree":
        from workspace_engine.cli.create_worktree import main as wt_main

        wt_main([args.repo, args.target, args.branch])
    elif args.command == "kube":
        from workspace_engine.cli.kube.main import main as kube_main

        sys.exit(kube_main(args.action))


if __name__ == "__main__":
    main()
