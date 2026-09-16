#!/usr/bin/env python3
"""
workspace_engine.cli.edit_workspace — Interactive editing of repositories in an existing workspace (add or remove).
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

from workspace_engine.common import (
    Color,
    find_project_root,
    log_error,
    log_info,
    log_success,
    log_warning,
    parse_dotenv,
    run_git,
)
from workspace_engine.services.add_repos import add_repositories_to_workspace
from workspace_engine.services.render_agents import update_workspace_agents


def remove_repositories_from_workspace(workspace_dir: Path) -> None:
    manifest_path = workspace_dir / ".ai-toolkit" / "workspace.json"
    if not manifest_path.exists():
        log_error(f"Workspace manifest not found at {manifest_path}")
        sys.exit(1)

    existing_data = json.loads(manifest_path.read_text(encoding="utf-8"))
    workspace_name: str = existing_data["workspace"]
    current_repo_names: list[str] = [r["name"] for r in existing_data.get("repositories", [])]

    if not current_repo_names:
        log_info("No repositories in this workspace.")
        return

    print(f"\n{Color.BOLD}Select the repositories to remove from '{workspace_name}':{Color.RESET}")
    for idx, name in enumerate(current_repo_names, 1):
        print(f"  {idx}. {name}")

    choice = input(
        f"\n{Color.BOLD}Enter comma-separated numbers or 'q' to cancel: {Color.RESET}"
    ).strip()
    if not choice or choice.lower() == "q":
        log_warning("Operation cancelled.")
        return

    selected_indices = [int(x.strip()) for x in choice.split(",") if x.strip().isdigit()]
    to_remove = [
        current_repo_names[i - 1] for i in selected_indices if 1 <= i <= len(current_repo_names)
    ]

    if not to_remove:
        log_warning("No repository selected.")
        return

    repos_dir = workspace_dir / "repositories"
    for rname in to_remove:
        target_wt = repos_dir / rname
        if target_wt.exists():
            git_common = run_git(target_wt, "rev-parse", "--git-common-dir")
            if git_common.returncode == 0 and git_common.stdout.strip():
                common_path = Path(git_common.stdout.strip())
                if not common_path.is_absolute():
                    common_path = (target_wt / common_path).resolve()
                run_git(common_path, "worktree", "remove", "--force", str(target_wt))
                run_git(common_path, "worktree", "prune")
            shutil.rmtree(target_wt, ignore_errors=True)
            log_info(f"  Removed worktree: {rname}")

    remaining_repos = [r for r in current_repo_names if r not in to_remove]
    existing_data["repositories"] = [
        r for r in existing_data.get("repositories", []) if r.get("name") not in to_remove
    ]
    manifest_path.write_text(json.dumps(existing_data, indent=2), encoding="utf-8")

    update_workspace_agents(workspace_dir, remaining_repos)

    log_success(f"Repositories removed successfully: {', '.join(to_remove)}")


def main() -> None:
    workspace_dir = find_project_root()
    if not (workspace_dir / "repositories").is_dir():
        log_error("edit-workspace must be run from inside a workspace.")
        sys.exit(1)

    print(f"\n{Color.BOLD}Edit Workspace:{Color.RESET} {workspace_dir.name}\n")
    print("  1) Add repositories")
    print("  2) Remove repositories")
    choice = input(f"\n{Color.BOLD}Option [1/2]: {Color.RESET}").strip()

    env_vars = parse_dotenv(workspace_dir / "config" / ".env")
    repos_dir_str = env_vars.get("AI_REPOSITORIES_DIR", os.environ.get("AI_REPOSITORIES_DIR", ""))
    repos_root = (
        Path(repos_dir_str).resolve()
        if repos_dir_str
        else workspace_dir.parent.parent / "ai-repositories"
    )

    if choice == "1":
        add_repositories_to_workspace(workspace_dir, repos_root)
    elif choice == "2":
        remove_repositories_from_workspace(workspace_dir)
    else:
        log_warning("Operation cancelled.")


if __name__ == "__main__":
    main()
