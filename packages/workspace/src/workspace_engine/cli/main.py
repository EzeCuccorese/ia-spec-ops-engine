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
import sys
import shutil
from rich.console import Console
from rich.table import Table

from workspace_engine.common import Color, log_info, log_error, log_success

console = Console()


def doctor_check() -> None:
    """Diagnoses development environment tools and runtimes."""
    table = Table(title="🏥 Development Environment Diagnostics (ws doctor)", border_style="green")
    table.add_column("Tool / Runtime", style="bold cyan")
    table.add_column("Status", justify="center")
    table.add_column("Details", style="dim")

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
            table.add_row(tool, "[green]✓ Available[/green]", f"{desc} ({path})")
        else:
            table.add_row(tool, "[yellow]⚠ Not Found[/yellow]", desc)

    console.print(table)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="ws",
        description="Cucco SpecOps Engine — Deterministic Workspace, Git Worktree & Local Microservices Manager.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", help="Available Workspace Engine commands")

    # ws generate
    p_gen = subparsers.add_parser("generate", help="Generate a new multi-repo workspace from Git worktrees")
    p_gen.add_argument("name", nargs="?", help="Workspace name")
    p_gen.add_argument("repos", nargs="*", help="Initial repositories (repo, repo:parent, or repo@branch format)")

    # ws edit
    p_edit = subparsers.add_parser("edit", help="Edit and add/remove repositories in an active workspace")
    p_edit.add_argument("name", nargs="?", help="Workspace name to edit")

    # ws worktree
    p_wt = subparsers.add_parser("worktree", help="Create an isolated Git worktree")
    p_wt.add_argument("repo", help="Base repository path or name")
    p_wt.add_argument("target", help="Target path for new worktree")
    p_wt.add_argument("branch", help="Branch name to associate")

    # ws clean
    p_clean = subparsers.add_parser("clean", help="Clean dependencies, caches, and build artifacts in workspace")
    p_clean.add_argument("target", nargs="?", default=".", help="Workspace directory")

    # ws stop
    p_stop = subparsers.add_parser("stop", help="Stop all running processes and services in workspace")
    p_stop.add_argument("workspace", nargs="?", help="Workspace name")

    # ws reset
    p_reset = subparsers.add_parser("reset", help="Reset workspace repositories to clean upstream state")
    p_reset.add_argument("workspace", nargs="?", help="Workspace name")
    p_reset.add_argument("--force", "-f", action="store_true", help="Force reset discarding local changes")

    # ws delete
    p_del = subparsers.add_parser("delete", help="Delete workspaces and unregister associated worktrees")
    p_del.add_argument("names", nargs="*", help="Names of workspaces to delete")

    # ws build
    p_build = subparsers.add_parser("build", help="Build project auto-detecting the technology stack")
    p_build.add_argument("dir", nargs="?", default=".", help="Project directory")

    # ws deps
    p_deps = subparsers.add_parser("deps", help="Install project dependencies (Gradle, Maven, NPM, uv, etc.)")
    p_deps.add_argument("dir", nargs="?", default=".", help="Project directory")

    # ws java
    p_java = subparsers.add_parser("java", help="Configure local Java JDK version via SDKMAN")
    p_java.add_argument("version", nargs="?", help="Java version (e.g. 17, 21)")

    # ws env-init
    p_einit = subparsers.add_parser("env-init", help="Initialize repository environment files from templates")
    p_einit.add_argument("repo", nargs="?", help="Repository name")

    # ws env-load
    p_eload = subparsers.add_parser("env-load", help="Load and inspect environment variables")
    p_eload.add_argument("repo", nargs="?", help="Repository name")

    # ws benchmark
    p_bench = subparsers.add_parser("benchmark", help="Execute parallel unit test benchmarks with visual reports")
    p_bench.add_argument("dir", nargs="?", default=".", help="Project directory")

    # ws run-local
    p_run = subparsers.add_parser("run-local", help="Orchestrate and launch local microservices with live TUI")
    p_run.add_argument("--profile", "-p", help="Execution profile to load")
    p_run.add_argument("--env", "-e", help="Target environment (faf, granos, staging)")

    # ws kube
    p_kube = subparsers.add_parser("kube", help="Kubernetes pod manager for environment extraction and shells")
    p_kube.add_argument("action", nargs="?", choices=["env", "logs", "shell"], help="Action to execute")

    # ws hooks
    p_hooks = subparsers.add_parser("hooks", help="Multi-stack Git Hooks & Quality Gates manager")
    p_hooks.add_argument("action", nargs="?", choices=["install", "status", "uninstall"], help="Action to perform")
    p_hooks.add_argument("--global", "-g", dest="is_global", action="store_true", help="Operate globally on ~/.githooks")
    p_hooks.add_argument("--dir", "-d", help="Root directory of repository")
    p_hooks.add_argument("--force", "-f", action="store_true", default=True, help="Overwrite existing hooks")

    # ws doctor
    subparsers.add_parser("doctor", help="Verify system tools, compilers, and development environment")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    # Delegate to corresponding modules
    if args.command == "doctor":
        doctor_check()
    elif args.command == "hooks":
        from workspace_engine.cli.manage_hooks import main as hooks_main
        hooks_main()
    elif args.command == "generate":
        from workspace_engine.cli.generate_workspace import main as gen_main
        gen_main()
    elif args.command == "edit":
        from workspace_engine.cli.edit_workspace import main as edit_main
        edit_main()
    elif args.command == "worktree":
        from workspace_engine.cli.create_worktree import main as wt_main
        wt_main()
    elif args.command == "clean":
        from workspace_engine.cli.clean_workspace import main as clean_main
        clean_main()
    elif args.command == "stop":
        from workspace_engine.cli.stop_workspace import main as stop_main
        stop_main()
    elif args.command == "reset":
        from workspace_engine.cli.reset_repos import main as reset_main
        reset_main()
    elif args.command == "delete":
        from workspace_engine.cli.delete_workspaces import main as del_main
        del_main()
    elif args.command == "build":
        from workspace_engine.cli.build_project import main as build_main
        build_main()
    elif args.command == "deps":
        from workspace_engine.cli.install_deps import main as deps_main
        deps_main()
    elif args.command == "java":
        from workspace_engine.cli.set_java import main as java_main
        java_main()
    elif args.command == "env-init":
        from workspace_engine.cli.init_env import main as einit_main
        einit_main()
    elif args.command == "env-load":
        from workspace_engine.cli.load_env import main as eload_main
        eload_main()
    elif args.command == "benchmark":
        from workspace_engine.cli.unit_test_benchmark import main as bench_main
        bench_main()
    elif args.command == "run-local":
        from workspace_engine.run_local.main import main as run_main
        run_main()
    elif args.command == "kube":
        from workspace_engine.cli.kube_env import main as kube_main
        kube_main()


if __name__ == "__main__":
    main()
