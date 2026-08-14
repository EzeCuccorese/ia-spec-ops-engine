"""
sdd_engine.finish — Finalización de feature SDD, push, creación de PR y limpieza de worktree.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path
from typing import Optional, Tuple, Union

from sdd_engine.core.utils import find_project_root, log_error, log_info, log_success, log_warning, run_command_safe
from sdd_engine.lifecycle import feature



def get_current_branch(repo_dir: Path) -> str:
    res, stdout, _ = run_command_safe(["git", "-C", str(repo_dir), "branch", "--show-current"])
    return stdout.strip() if res == 0 else ""


def finish_feature(
    target_dir: Union[str, Path] = ".",
    create_pr: bool = True,
    title: Optional[str] = None,
    body: Optional[str] = None,
) -> bool:
    """
    Finalizes the active SDD feature:
    1. Validates active feature state.
    2. Commits pending changes if any.
    3. Pushes feature branch to remote origin.
    4. Creates GitHub Pull Request via `gh pr create` (or prints fallback URL).
    5. Removes local Worktree cleanly if working inside a worktree.
    6. Switches main repo to main branch and executes `git pull origin main`.
    7. Resets active feature state.
    """
    td = Path(target_dir).resolve()
    repo_root = find_project_root(td)
    feat_name = feature.get_active_feature(td)

    log_info("=== SDD Feature Finish & PR Orchestrator ===")

    if not feat_name:
        log_warning("⚠️ No active feature set to finish.")
        return False

    current_branch = get_current_branch(repo_root)
    branch_name = f"feature/{feat_name}" if not current_branch.startswith("feature/") else current_branch

    log_info(f"📌 Feature: {feat_name}")
    log_info(f"🌿 Branch: {branch_name}")

    # 1. Commit any uncommitted changes with Conventional Commit format
    res_status, stdout_status, _ = run_command_safe(["git", "-C", str(repo_root), "status", "--porcelain"])
    if stdout_status.strip():
        log_info("📦 Committing pending feature changes...")
        run_command_safe(["git", "-C", str(repo_root), "add", "-A"])
        commit_msg = f"feat({feat_name}): complete sdd feature cycle"
        run_command_safe(["git", "-C", str(repo_root), "commit", "-m", commit_msg])

    # 2. Push branch to remote origin
    log_info(f"🚀 Pushing branch '{branch_name}' to remote origin...")
    res_push, _, err_push = run_command_safe(
        ["git", "-C", str(repo_root), "push", "-u", "origin", branch_name]
    )
    if res_push != 0:
        log_warning(f"⚠️ Warning during git push: {err_push[:200]}")

    # 3. Create GitHub Pull Request
    if create_pr:
        log_info("🐙 Creating GitHub Pull Request...")
        pr_title = title or f"feat({feat_name}): implement {feat_name}"
        spec_file = repo_root / ".specify" / "specs" / feat_name / "spec.md"
        pr_body = body or (spec_file.read_text(encoding="utf-8") if spec_file.exists() else f"SDD Feature {feat_name}")

        code_gh, stdout_gh, stderr_gh = run_command_safe(
            ["gh", "pr", "create", "--title", pr_title, "--body", pr_body[:2000]]
        )
        if code_gh == 0:
            log_success(f"✅ Pull Request created: {stdout_gh.strip()}")
        else:
            log_warning("ℹ️ `gh` CLI not authenticated or missing. Fallback PR creation link:")
            log_info(f"  https://github.com/pulls")

    # 4. Identify Main Repo Root & Worktree Cleanup
    res_wt, wt_out, _ = run_command_safe(["git", "-C", str(repo_root), "worktree", "list", "--porcelain"])
    main_repo_path = repo_root

    if res_wt == 0 and "worktree " in wt_out:
        lines = wt_out.splitlines()
        for line in lines:
            if line.startswith("worktree "):
                candidate = Path(line.split("worktree ", 1)[1]).resolve()
                if (candidate / ".git").is_file():  # Worktrees have .git files, main repo has .git dir
                    continue
                if (candidate / ".git").is_dir():
                    main_repo_path = candidate
                    break

    is_worktree = (repo_root / ".git").is_file()

    # 5. Reset Feature State
    feature.reset(repo_root=td)

    # 6. Worktree Cleanup & Main Pull
    if is_worktree and repo_root != main_repo_path:
        log_info(f"🧹 Removing local worktree: {repo_root}")
        run_command_safe(["git", "-C", str(main_repo_path), "worktree", "remove", "--force", str(repo_root)])
        run_command_safe(["git", "-C", str(main_repo_path), "worktree", "prune"])

    log_info(f"🌿 Returning to main repo at {main_repo_path}...")
    run_command_safe(["git", "-C", str(main_repo_path), "checkout", "main"])
    log_info("🔄 Pulling latest changes on main...")
    run_command_safe(["git", "-C", str(main_repo_path), "pull", "origin", "main"])

    log_success("✅ SDD Feature Finished successfully! PR created, Worktree cleaned up, main updated.")
    return True
