#!/usr/bin/env python3
"""
workspace_engine.services.add_repos — Interactive addition of repositories to an existing workspace.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from workspace_engine.common import log_error, log_success, log_warning, parse_dotenv, run_git
from workspace_engine.services.configure_repos import RepoConfig, configure_repos, pre_validate
from workspace_engine.services.render_agents import update_workspace_agents
from workspace_engine.services.select_repos import select_repos


def setup_repo_worktree(repo_path: Path, target_path: Path, config: RepoConfig) -> None:
    """Creates a git worktree at target_path according to config's settings."""
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


def add_repositories_to_workspace(
    workspace_dir: Path, repos_root: Path, template_path: Path | None = None
) -> None:
    manifest_path = workspace_dir / ".ai-toolkit" / "workspace.json"
    if not manifest_path.exists():
        log_error(f"Workspace manifest not found at {manifest_path}")
        sys.exit(1)

    existing_data = json.loads(manifest_path.read_text(encoding="utf-8"))
    workspace_name: str = existing_data["workspace"]
    current_repo_names: list = [r["name"] for r in existing_data.get("repositories", [])]

    prev_selected: list = []
    configs: list[RepoConfig] | None = None
    repo_paths: dict[str, Path] = {}
    while True:
        selected = select_repos(
            toolkit_dir=workspace_dir,
            repos_root=repos_root,
            show_toolkit=False,
            locked=current_repo_names,
            preselected=prev_selected,
        )
        if selected is None:
            sys.exit(130)

        repo_paths = {name: repos_root / name for name in selected}
        configs = configure_repos(workspace_name, selected, repo_paths)
        if configs is not None:
            break
        prev_selected = selected

    errors = pre_validate(configs, repo_paths)
    if errors:
        log_error("Validation errors:")
        for e in errors:
            print(f"  • {e}", file=sys.stderr)
        sys.exit(1)

    added = []
    failed = []
    for config in configs:
        target = workspace_dir / "repositories" / config.name
        try:
            setup_repo_worktree(repos_root / config.name, target, config)
            added.append(config)
        except (OSError, subprocess.SubprocessError, RuntimeError) as exc:
            log_error(f"Failed to create worktree for {config.name}: {exc}")
            failed.append(config.name)

    if not added:
        sys.exit(1)

    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        for cfg in added:
            data["repositories"].append(
                {
                    "name": cfg.name,
                    "branch": cfg.branch,
                    "parent_branch": cfg.parent if cfg.mode == "new" else None,
                }
            )
        manifest_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except (OSError, json.JSONDecodeError, KeyError) as exc:
        log_error(f"Could not update the workspace manifest: {exc}")
        sys.exit(1)

    try:
        repos = current_repo_names + [cfg.name for cfg in added]
        update_workspace_agents(workspace_dir, repos, template_path)
    except OSError as exc:
        log_warning(f"Could not update AGENTS.md: {exc}")

    log_success(f"Repositories added successfully: {', '.join(c.name for c in added)}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Adds repositories to an existing workspace.")
    parser.add_argument("--workspace-dir", required=True, type=Path, help="Path to the workspace.")
    parser.add_argument("--repos-dir", type=Path, help="Path to the repositories directory.")
    args = parser.parse_args()

    workspace_dir = args.workspace_dir.resolve()
    repos_dir = args.repos_dir
    if not repos_dir:
        env_vars = parse_dotenv(workspace_dir / "config" / ".env")
        repos_dir_str = env_vars.get(
            "AI_REPOSITORIES_DIR", os.environ.get("AI_REPOSITORIES_DIR", "")
        )
        if not repos_dir_str:
            log_error("AI_REPOSITORIES_DIR not configured.")
            sys.exit(1)
        repos_dir = Path(repos_dir_str)

    add_repositories_to_workspace(workspace_dir, repos_dir.resolve())


if __name__ == "__main__":
    main()
