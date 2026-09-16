#!/usr/bin/env python3
"""
workspace_engine.cli.delete_workspaces — Safe, interactive deletion of workspaces and their associated worktrees.
"""

from __future__ import annotations

import argparse
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
    run_git,
)


def _is_owned_workspace(target: Path) -> bool:
    """Checks whether the directory contains valid workspace ownership markers."""
    if (target / ".workspace_metadata").exists():
        return True
    if (target / ".ai-toolkit").is_dir():
        return True
    if (target / ".git").is_file():
        return True
    repos_dir = target / "repositories"
    if repos_dir.is_dir():
        for r in repos_dir.iterdir():
            if r.is_dir() and ((r / ".git").exists() or (r / ".git").is_file()):
                return True
    return False


def _has_dirty_repos(target: Path) -> list[str]:
    """Returns the names of repositories with uncommitted or untracked changes."""
    dirty: list[str] = []
    repos_dir = target / "repositories"
    if repos_dir.is_dir():
        for r_dir in repos_dir.iterdir():
            if r_dir.is_dir() and ((r_dir / ".git").exists() or (r_dir / ".git").is_file()):
                status = run_git(r_dir, "status", "--porcelain")
                if status.stdout.strip():
                    dirty.append(r_dir.name)
    if (target / ".git").exists() or (target / ".git").is_file():
        status = run_git(target, "status", "--porcelain")
        if status.stdout.strip():
            dirty.append(target.name)
    return dirty


def delete_single_workspace(
    workspace_dir: Path, force: bool = False, workspaces_dir: Path | None = None
) -> bool:
    # 1. Resolve the base workspaces_dir
    if workspaces_dir is not None:
        base_dir = Path(workspaces_dir).resolve()
    else:
        root = find_project_root()
        base_dir = (
            root / "workspaces" if (root / "workspaces").exists() else root.parent / "workspaces"
        ).resolve()

    # 2. Path confinement: validate that target is strictly contained in base_dir
    target = Path(workspace_dir).resolve()
    if not (target.is_relative_to(base_dir) and target != base_dir):
        raise ValueError(
            f"Workspace path '{workspace_dir}' escapes managed workspaces directory '{base_dir}'."
        )

    if not target.is_dir():
        log_error(f"Workspace not found at {target}")
        return False

    # 3. Ownership marker verification
    if not _is_owned_workspace(target):
        raise ValueError(
            f"Directory '{target}' is not an owned workspace: missing ownership marker "
            f"(.workspace_metadata, .ai-toolkit, or git worktree)."
        )

    workspace_name = target.name

    # 4. Check repositories' dirty state
    dirty_repos = _has_dirty_repos(target)
    if dirty_repos and not force:
        log_error(
            f"Workspace '{workspace_name}' has uncommitted changes in: "
            f"{', '.join(dirty_repos)}. Use force=True to force deletion."
        )
        return False

    print(f"\n{Color.BOLD}Deleting workspace '{workspace_name}'...{Color.RESET}")

    # 5. Clean deregistration of Git worktrees if applicable
    repos_dir = target / "repositories"
    if repos_dir.is_dir():
        for r_dir in repos_dir.iterdir():
            if r_dir.is_dir() and ((r_dir / ".git").exists() or (r_dir / ".git").is_file()):
                is_worktree = (r_dir / ".git").is_file()
                git_common = run_git(r_dir, "rev-parse", "--git-common-dir")
                if git_common.returncode == 0 and git_common.stdout.strip():
                    common_path = Path(git_common.stdout.strip())
                    if not common_path.is_absolute():
                        common_path = (r_dir / common_path).resolve()
                    # Only attempt git worktree remove if it is actually a linked worktree
                    if is_worktree or (
                        common_path != (r_dir / ".git").resolve() and common_path != r_dir
                    ):
                        cmd = ["worktree", "remove"]
                        if force:
                            cmd.append("--force")
                        cmd.append(str(r_dir))
                        remove_res = run_git(common_path, *cmd)
                        if (
                            remove_res.returncode != 0
                            and "is a main working tree" not in remove_res.stderr
                        ):
                            log_error(
                                f"Error removing worktree for '{r_dir.name}': {remove_res.stderr.strip()}"
                            )
                            return False

                        run_git(common_path, "worktree", "prune")

    # 6. Honest filesystem deletion (no silent ignore_errors)
    try:
        shutil.rmtree(target)
    except OSError as e:
        log_error(f"Error deleting workspace '{workspace_name}': {e}")
        return False

    if target.exists():
        log_error(f"Workspace directory '{target}' could not be fully deleted.")
        return False

    log_success(f"Workspace '{workspace_name}' deleted.")
    return True


def delete_workspaces(
    workspaces: list[str] | None = None,
    force: bool = False,
    workspaces_dir: Path | None = None,
) -> int:
    if workspaces_dir is not None:
        workspaces_root = Path(workspaces_dir).resolve()
    else:
        root = find_project_root()
        workspaces_root = (
            root / "workspaces" if (root / "workspaces").exists() else root.parent / "workspaces"
        ).resolve()

    # If run from inside a workspace
    root = find_project_root()
    if (root / "repositories").is_dir() and root.name != "workspaces":
        if not force:
            print(
                f"{Color.RED}{Color.BOLD}⚠ Warning: you are about to delete the current workspace: {root.name}{Color.RESET}"
            )
            resp = input(f"{Color.BOLD}Delete? [y/N]: {Color.RESET}").strip().lower()
            if resp not in ("y", "yes"):
                log_warning("Operation cancelled.")
                return 0
        ok = delete_single_workspace(root, force=True, workspaces_dir=workspaces_dir)
        return 0 if ok else 1

    if not workspaces:
        if not workspaces_root.exists():
            log_warning("Workspaces directory not found.")
            return 0
        available = [d.name for d in sorted(workspaces_root.iterdir()) if d.is_dir()]
        if not available:
            log_info("No workspaces available to delete.")
            return 0
        print(f"\n{Color.BOLD}Available workspaces:{Color.RESET}")
        for idx, w in enumerate(available, 1):
            print(f"  {idx}. {w}")
        choice = input(
            f"\n{Color.BOLD}Select the numbers to delete (comma-separated) or 'q' to quit: {Color.RESET}"
        ).strip()
        if not choice or choice.lower() == "q":
            log_warning("Operation cancelled.")
            return 0
        selected_indices = [int(x.strip()) for x in choice.split(",") if x.strip().isdigit()]
        workspaces = [available[i - 1] for i in selected_indices if 1 <= i <= len(available)]

    for ws_name in workspaces:
        ws_path = workspaces_root / ws_name
        ok = delete_single_workspace(ws_path, force=force, workspaces_dir=workspaces_root)
        if not ok:
            return 1

    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Deletes workspaces and deregisters their worktrees."
    )
    parser.add_argument("--force", action="store_true", help="Skip confirmation")
    parser.add_argument("workspaces", nargs="*", help="Names of the workspaces to delete")
    args = parser.parse_args()

    try:
        sys.exit(delete_workspaces(workspaces=args.workspaces, force=args.force))
    except ValueError as e:
        log_error(str(e))
        sys.exit(1)


if __name__ == "__main__":
    main()
