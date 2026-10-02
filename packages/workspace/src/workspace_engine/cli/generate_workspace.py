#!/usr/bin/env python3
"""
workspace_engine.cli.generate_workspace — Interactive, deterministic generator for multi-repository workspaces.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

from workspace_engine.common import (
    Color,
    find_project_root,
    log_error,
    log_success,
    log_warning,
    parse_dotenv,
    run_git,
)
from workspace_engine.services.configure_repos import RepoConfig, configure_repos
from workspace_engine.services.render_agents import render_agents_md
from workspace_engine.services.select_repos import select_repos


def setup_repo_worktree(repo_path: Path, target_path: Path, config: RepoConfig) -> None:
    """Deterministically creates a git worktree."""
    wt_list = run_git(repo_path, "worktree", "list", "--porcelain")
    for line in wt_list.stdout.splitlines():
        if line == f"worktree {target_path}":
            return

    if config.mode == "new":
        parent = config.parent or "main"
        run_git(repo_path, "fetch", "origin", parent)
        remote_ref = f"origin/{parent}"
        remote_check = run_git(repo_path, "rev-parse", "--verify", remote_ref)
        start = remote_ref if remote_check.returncode == 0 else parent
        result = run_git(repo_path, "worktree", "add", "-b", config.branch, str(target_path), start)
        if result.returncode != 0:
            raise RuntimeError(f"Failed to create worktree for {config.name}: {result.stderr}")
    elif config.mode == "existing":
        if getattr(config, "is_remote_only", False):
            run_git(repo_path, "fetch", "origin", config.branch)
            result = run_git(
                repo_path,
                "worktree",
                "add",
                "--track",
                "-b",
                config.branch,
                str(target_path),
                f"origin/{config.branch}",
            )
        else:
            result = run_git(repo_path, "worktree", "add", str(target_path), config.branch)
        if result.returncode != 0:
            raise RuntimeError(f"Failed to create worktree for {config.name}: {result.stderr}")


def _remove_worktrees(created: list[tuple[Path, Path, RepoConfig]]) -> None:
    """Undoes the worktrees (and the branches of `new` ones) this run created."""
    for src, target, cfg in reversed(created):
        run_git(src, "worktree", "remove", "--force", str(target))
        if cfg.mode == "new":
            run_git(src, "branch", "-D", cfg.branch)


def _create_worktrees(
    workspace_dir: Path, repo_configs: list[RepoConfig], repo_paths: dict[str, Path]
) -> None:
    """Creates every worktree, or none: on failure the workspace is rolled back and re-raised."""
    created: list[tuple[Path, Path, RepoConfig]] = []
    try:
        for cfg in repo_configs:
            src = repo_paths[cfg.name]
            target = workspace_dir / "repositories" / cfg.name
            setup_repo_worktree(src, target, cfg)
            created.append((src, target, cfg))
            log_success(f"Worktree created for {cfg.name} (branch: {cfg.branch})")
    except RuntimeError:
        _remove_worktrees(created)
        shutil.rmtree(workspace_dir, ignore_errors=True)
        raise


def create_workspace_structure(
    workspace_name: str,
    workspaces_root: Path,
    repo_configs: list[RepoConfig],
    repo_paths: dict[str, Path],
    template_dir: Path | None = None,
) -> Path:
    workspace_dir = workspaces_root / workspace_name
    workspace_repos = workspace_dir / "repositories"
    workspace_repos.mkdir(parents=True, exist_ok=True)
    (workspace_dir / "docs").mkdir(exist_ok=True)

    print(f"\n{Color.BOLD}Creating workspace '{workspace_name}'...{Color.RESET}")

    _create_worktrees(workspace_dir, repo_configs, repo_paths)

    # Write manifest
    ai_dir = workspace_dir / ".ai-toolkit"
    ai_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema_version": 1,
        "workspace": workspace_name,
        "repositories": [
            {
                "name": cfg.name,
                "branch": cfg.branch,
                "parent_branch": cfg.parent if cfg.mode == "new" else None,
            }
            for cfg in repo_configs
        ],
    }
    (ai_dir / "workspace.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    # Render AGENTS.md
    repos = [cfg.name for cfg in repo_configs]
    template_file = (template_dir / "workspace-agents.md.template") if template_dir else None
    content = render_agents_md(template_file, workspace_name, "repositories", repos)

    (workspace_dir / "AGENTS.md").write_text(content, encoding="utf-8")
    log_success(f"Workspace '{workspace_name}' generated successfully at {workspace_dir}")
    return workspace_dir


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="ws generate", description="Generates a multi-repository workspace."
    )
    parser.add_argument("name", nargs="?", help="Workspace name")
    parser.add_argument(
        "repos", nargs="*", help="Initial repositories (format repo or repo:parent or repo@branch)"
    )
    return parser.parse_args(argv)


def _workspace_roots() -> tuple[Path, Path, Path]:
    """Returns (toolkit_dir, workspaces_root, repos_root); creates workspaces_root."""
    toolkit_dir = find_project_root()
    env_vars = parse_dotenv(toolkit_dir / "config" / ".env")
    repos_dir_str = env_vars.get("AI_REPOSITORIES_DIR", os.environ.get("AI_REPOSITORIES_DIR", ""))

    dev_root = toolkit_dir.parent
    workspaces_root = dev_root / "workspaces"
    workspaces_root.mkdir(parents=True, exist_ok=True)

    repos_root = Path(repos_dir_str).resolve() if repos_dir_str else dev_root / "ai-repositories"
    return toolkit_dir, workspaces_root, repos_root


def _workspace_name(name: str | None, workspaces_root: Path) -> str:
    workspace_name = name
    if not workspace_name:
        workspace_name = input(f"{Color.BOLD}Enter the new workspace name: {Color.RESET}").strip()
        if not workspace_name:
            log_error("The workspace name cannot be empty.")
            sys.exit(1)

    if (workspaces_root / workspace_name).exists():
        log_error(f"Workspace '{workspace_name}' already exists.")
        sys.exit(1)
    return workspace_name


def _repo_config_from_arg(r_arg: str, workspace_name: str) -> RepoConfig:
    """Parses `repo`, `repo:parent` or `repo@branch`."""
    if "@" in r_arg:
        rname, rbranch = r_arg.split("@", 1)
        return RepoConfig(name=rname, mode="existing", branch=rbranch, parent=None)
    if ":" in r_arg:
        rname, rparent = r_arg.split(":", 1)
        return RepoConfig(name=rname, mode="new", branch=workspace_name, parent=rparent)
    return RepoConfig(name=r_arg, mode="new", branch=workspace_name, parent="main")


def _select_repo_configs(
    workspace_name: str, toolkit_dir: Path, repos_root: Path
) -> tuple[list[RepoConfig], dict[str, Path]]:
    selected = select_repos(toolkit_dir=toolkit_dir, repos_root=repos_root, show_toolkit=False)
    if not selected:
        log_warning("No repository was selected.")
        sys.exit(0)
    repo_paths = {name: repos_root / name for name in selected}
    repo_configs = configure_repos(workspace_name, selected, repo_paths)
    if not repo_configs:
        log_warning("Configuration cancelled.")
        sys.exit(0)
    return repo_configs, repo_paths


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    toolkit_dir, workspaces_root, repos_root = _workspace_roots()
    workspace_name = _workspace_name(args.name, workspaces_root)

    if args.repos:
        repo_configs = [_repo_config_from_arg(r_arg, workspace_name) for r_arg in args.repos]
        repo_paths = {cfg.name: repos_root / cfg.name for cfg in repo_configs}
    else:
        repo_configs, repo_paths = _select_repo_configs(workspace_name, toolkit_dir, repos_root)

    try:
        create_workspace_structure(
            workspace_name=workspace_name,
            workspaces_root=workspaces_root,
            repo_configs=repo_configs,
            repo_paths=repo_paths,
        )
    except RuntimeError as e:
        log_error(str(e).strip())
        sys.exit(1)


if __name__ == "__main__":
    main()
