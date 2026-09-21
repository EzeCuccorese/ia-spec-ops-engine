#!/usr/bin/env python3
"""
workspace_engine.cli.create_worktree — Deterministic creation of Git Worktrees and environment file synchronization.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from workspace_engine.common import (
    find_project_root,
    log_error,
    log_info,
    log_success,
    run_command_safe,
)


def _run_cmd(cmd: list[str]) -> tuple[int, str, str]:
    return run_command_safe(cmd, isolated_git=True)


def create_worktree(
    branch: str,
    from_branch: str | None = None,
    start_dir: Path | None = None,
    target_dir: Path | None = None,
) -> int:
    """Creates a git worktree for the specified branch and copies local configurations."""
    repo_root = find_project_root(start_dir)
    sanitized_branch = branch.replace("/", "-")
    worktree_dir = target_dir or (repo_root.parent / f"workspace-{sanitized_branch}")

    if worktree_dir.exists():
        log_error(f"Error: '{worktree_dir}' already exists")
        return 1

    base_branch = from_branch
    if not base_branch:
        res_branch, current_branch, _ = _run_cmd(
            ["git", "-C", str(repo_root), "branch", "--show-current"]
        )
        current_branch = current_branch.strip()
        base_branch = current_branch if (res_branch == 0 and current_branch) else "main"

    if base_branch in ("main", "master", "develop", "staging"):
        log_info(f"🔄 Updating base branch '{base_branch}' with git pull...")
        _run_cmd(["git", "-C", str(repo_root), "pull", "origin", base_branch])

    code_local, _, _ = _run_cmd(
        ["git", "-C", str(repo_root), "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"]
    )
    code_remote, _, _ = _run_cmd(
        [
            "git",
            "-C",
            str(repo_root),
            "show-ref",
            "--verify",
            "--quiet",
            f"refs/remotes/origin/{branch}",
        ]
    )

    if code_local == 0:
        cmd = ["git", "-C", str(repo_root), "worktree", "add", str(worktree_dir), branch]
    elif code_remote == 0:
        cmd = [
            "git",
            "-C",
            str(repo_root),
            "worktree",
            "add",
            "--track",
            "-b",
            branch,
            str(worktree_dir),
            f"origin/{branch}",
        ]
    else:
        cmd = [
            "git",
            "-C",
            str(repo_root),
            "worktree",
            "add",
            "-b",
            branch,
            str(worktree_dir),
            base_branch,
        ]

    res, _, err = _run_cmd(cmd)
    if res != 0:
        log_error(f"Failed to create worktree: {err}")
        return res

    log_success(f"Worktree created at: {worktree_dir}")

    config_files = [
        "config/.env",
        "config/.env.secrets",
        ".specify/settings.local.json",
        ".specify/worktrees",
        "memory",
    ]

    for rel_path in config_files:
        src = repo_root / rel_path
        if src.exists():
            dest = worktree_dir / rel_path
            dest.parent.mkdir(parents=True, exist_ok=True)
            if src.is_dir():
                shutil.copytree(src, dest, dirs_exist_ok=True)
            else:
                shutil.copy2(src, dest)
            log_info(f"  copied: {rel_path}")

    return 0


def main(argv: list[str] | None = None) -> None:
    """Entry point for `ws worktree`.

    Accepts the documented `<repo> <target> <branch>` form forwarded by the `ws`
    dispatcher, and keeps the legacy single `<branch>` form for direct invocation.
    """
    parser = argparse.ArgumentParser(
        description="Creates an isolated Git worktree at ../workspace-<branch>"
    )
    parser.add_argument("repo", nargs="?", help="Base repository path or name")
    parser.add_argument("target", nargs="?", help="Target path for new worktree")
    parser.add_argument("branch", help="Branch name for the worktree")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    start_dir = Path(args.repo) if args.repo else None
    target_dir = Path(args.target) if args.target else None
    sys.exit(create_worktree(args.branch, start_dir=start_dir, target_dir=target_dir))


if __name__ == "__main__":
    main()
