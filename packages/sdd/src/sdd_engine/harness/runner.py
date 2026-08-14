"""
devscripts.sdd.runner — Isolated Git Worktree task execution runner for SDD.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import shutil
import subprocess
import sys
from typing import List, Optional, Union

from sdd_engine.core.exceptions import RunnerError



def run_in_worktree(
    cmd_args: List[str],
    repo: Optional[Union[str, Path]] = None,
    branch: Optional[str] = None,
    cleanup: bool = False,
) -> int:
    target_repo = Path(repo).resolve() if repo else Path.cwd()
    try:
        main_git_root = Path(
            subprocess.check_output(
                ["git", "-C", str(target_repo), "rev-parse", "--show-toplevel"],
                stderr=subprocess.DEVNULL,
            )
            .decode()
            .strip()
        )
    except (subprocess.CalledProcessError, subprocess.SubprocessError, OSError):
        raise RunnerError(f"Target path '{target_repo}' is not inside a git repository.")

    repo_name = main_git_root.name
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    branch_name = branch or f"sdd-wt-{ts}"

    wt_base = Path.home() / ".sdd" / "worktrees"
    try:
        wt_base.mkdir(parents=True, exist_ok=True)
    except OSError:
        wt_base = main_git_root / ".worktrees"
        wt_base.mkdir(parents=True, exist_ok=True)

    wt_dir = wt_base / f"{repo_name}-{ts}"

    print("==> Creating isolated Git Worktree")
    print(f"    Repo:     {main_git_root}")
    print(f"    Worktree: {wt_dir}")
    print(f"    Branch:   {branch_name}")

    subprocess.run(
        ["git", "-C", str(main_git_root), "worktree", "add", "-b", branch_name, str(wt_dir), "HEAD", "--quiet"],
        check=True,
    )

    for src_rel in ["config/.env", ".env", ".claude/settings.local.json", ".specify/memory.md"]:
        src = main_git_root / src_rel
        if src.exists():
            dest = wt_dir / src_rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            if src.is_dir():
                shutil.copytree(src, dest, dirs_exist_ok=True)
            else:
                shutil.copy2(src, dest)

    print("==> Executing task in isolated environment...")
    print("-" * 56)

    res = subprocess.run(cmd_args, cwd=str(wt_dir))

    print("-" * 56)
    if res.returncode == 0:
        print("==> Task completed successfully (exit code 0).")
        if cleanup:
            print(f"==> Cleaning up worktree: {wt_dir}")
            subprocess.run(
                ["git", "-C", str(main_git_root), "worktree", "remove", "--force", str(wt_dir), "--quiet"],
                stderr=subprocess.DEVNULL,
            )
            subprocess.run(
                ["git", "-C", str(main_git_root), "branch", "-D", branch_name, "--quiet"],
                stderr=subprocess.DEVNULL,
            )
        else:
            print(f"==> Worktree preserved at: {wt_dir}")
            print(f'    To merge changes: git -C "{main_git_root}" merge "{branch_name}"')
    else:
        print(f"==> Task failed with exit code {res.returncode}.", file=sys.stderr)
        print(f"    Worktree preserved for debugging at: {wt_dir}", file=sys.stderr)

    return res.returncode
