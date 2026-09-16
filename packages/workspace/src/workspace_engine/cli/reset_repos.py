#!/usr/bin/env python3
"""
workspace_engine.cli.reset_repos — Deterministic reset of Git repositories to the base commit or a clean HEAD.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from workspace_engine.utils import (
    Color,
    find_project_root,
    log_error,
    log_success,
    log_warning,
    run_git,
)


def _git(repo_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return run_git(repo_path, *args)


def _parent_branch(workspace_dir: Path, repo_name: str) -> str | None:
    manifest = workspace_dir / ".ai-toolkit" / "workspace.json"
    if not manifest.is_file():
        return None
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
        for r in data.get("repositories", []):
            if r.get("name") == repo_name:
                return r.get("parent_branch")
    except (OSError, json.JSONDecodeError, KeyError):
        pass
    return None


def _branch_point(repo_path: Path, parent: str | None) -> str | None:
    if not parent:
        return None
    remote_check = _git(repo_path, "rev-parse", "--verify", "--quiet", f"origin/{parent}")
    if remote_check.returncode == 0:
        base = f"origin/{parent}"
    else:
        local_check = _git(repo_path, "rev-parse", "--verify", "--quiet", parent)
        if local_check.returncode == 0:
            base = parent
        else:
            return None
    res = _git(repo_path, "merge-base", "HEAD", base)
    if res.returncode == 0 and res.stdout.strip():
        return res.stdout.strip()
    return None


def reset_repositories(
    force: bool = False,
    dry_run: bool = False,
    repo_filter: list[str] | None = None,
    start_dir: Path | None = None,
) -> int:
    workspace_dir = find_project_root(start_dir)
    repos_dir = workspace_dir / "repositories"
    if not repos_dir.is_dir():
        log_error(f"repositories/ directory not found in {workspace_dir}")
        return 1

    repos: list[Path] = []
    if repo_filter:
        for name in repo_filter:
            p = repos_dir / name
            if not p.is_dir() or not ((p / ".git").exists() or (p / ".git").is_file()):
                log_error(f"Not a git repository: {name}")
                return 1
            repos.append(p)
    else:
        for p in sorted(repos_dir.iterdir()):
            if p.is_dir() and ((p / ".git").exists() or (p / ".git").is_file()):
                repos.append(p)

    if not repos:
        log_warning(f"No git repositories found in {repos_dir}")
        return 0

    print(f"\n{Color.BOLD}Workspace:{Color.RESET} {workspace_dir}")
    if dry_run:
        print(f"{Color.YELLOW}[DRY RUN — no changes will be made]{Color.RESET}")
    print("")

    dirty_repos: list[tuple[Path, str | None]] = []
    for r in repos:
        repo_name = r.name
        branch_res = _git(r, "branch", "--show-current")
        branch = branch_res.stdout.strip() or "(detached)"
        parent = _parent_branch(workspace_dir, repo_name)
        b_point = _branch_point(r, parent)

        local_commits = []
        if b_point:
            log_res = _git(r, "log", "--oneline", f"{b_point}..HEAD")
            if log_res.returncode == 0 and log_res.stdout.strip():
                local_commits = log_res.stdout.strip().splitlines()

        status_res = _git(r, "status", "--porcelain")
        dirty = [line for line in status_res.stdout.splitlines() if line.strip()]
        tracked_dirty = [line for line in dirty if not line.startswith("??")]
        untracked = [line for line in dirty if line.startswith("??")]

        has_changes = bool(local_commits or tracked_dirty)
        print(f"{Color.BOLD}{repo_name}{Color.RESET} {Color.DIM}({branch}){Color.RESET}")

        if not has_changes:
            print(f"  {Color.DIM}clean — nothing to reset{Color.RESET}")
            continue

        if local_commits:
            short = b_point[:7] if b_point else ""
            print(
                f"  {Color.DIM}{len(local_commits)} local commit(s) will be discarded (-> {short}):{Color.RESET}"
            )
            for c in local_commits[:5]:
                print(f"    {Color.DIM}{c}{Color.RESET}")
        if tracked_dirty:
            print(
                f"  {Color.DIM}{len(tracked_dirty)} modified file(s) will be restored{Color.RESET}"
            )
        if untracked:
            print(f"  {Color.DIM}{len(untracked)} untracked file(s) (kept){Color.RESET}")

        dirty_repos.append((r, b_point))
        print("")

    if not dirty_repos:
        log_success("All repositories are clean.")
        return 0

    if dry_run:
        return 0

    if not force:
        print(
            f"{Color.RED}{Color.BOLD}Changes in {len(dirty_repos)} repository(ies) will be permanently discarded.{Color.RESET}"
        )
        resp = input(f"{Color.BOLD}Continue? [y/N]: {Color.RESET}").strip().lower()
        if resp not in ("y", "yes"):
            log_warning("Operation cancelled.")
            return 0

    failed = False
    for r, b_point in dirty_repos:
        print(f"{Color.BOLD}[{r.name}]{Color.RESET} resetting...")
        target_ref = b_point if b_point else "HEAD"
        res = _git(r, "reset", "--hard", target_ref)
        if res.returncode == 0:
            log_success(f"[{r.name}] reset successfully.")
        else:
            log_error(f"[{r.name}] error resetting: {res.stderr}")
            failed = True

    return 1 if failed else 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Resets the workspace repositories to the source commit or a clean HEAD."
    )
    parser.add_argument("--force", action="store_true", help="Skip interactive confirmation")
    parser.add_argument("--dry-run", action="store_true", help="Simulate without modifying files")
    parser.add_argument("repos", nargs="*", help="Specific repositories to reset")
    args = parser.parse_args()

    sys.exit(reset_repositories(force=args.force, dry_run=args.dry_run, repo_filter=args.repos))


if __name__ == "__main__":
    main()
