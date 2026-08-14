"""
devscripts.sdd.reset — Global environment and worktree cleanup utility for SDD.
"""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Union


def clean_path(p: Union[str, Path], desc: str, dry_run: bool) -> None:
    path = Path(p)
    if path.exists():
        if dry_run:
            print(f"  [dry-run] Would remove: {path} ({desc})")
        else:
            if path.is_dir() and not path.is_symlink():
                shutil.rmtree(path, ignore_errors=True)
            else:
                path.unlink(missing_ok=True)
            print(f"  Removed: {path} ({desc})")


def reset(target: str = "all", force: bool = False, dry_run: bool = False) -> None:
    print("=== SDD Global Environment Reset ===")
    print(f"Target Scope: {target}")
    if dry_run:
        print("[DRY RUN MODE — No actual deletions will occur]")

    if not force and not dry_run:
        ans = input(
            "Warning: This operation will clean temporary files, logs, worktrees, and reset state.\n"
            "Are you sure you want to proceed? [y/N] "
        )
        if ans.lower() != "y":
            print("Reset cancelled by user.")
            return

    home = Path.home()
    if target in ["all", "cache"]:
        print("==> Cleaning ~/.gemini temporary state...")
        gemini = home / ".gemini" / "antigravity"
        clean_path(gemini / "tmp", "Antigravity temporary directory", dry_run)
        clean_path(gemini / "scratch", "Scratch execution files", dry_run)
        clean_path(gemini / "cache", "Antigravity cache", dry_run)
        brain = gemini / "brain"
        if brain.is_dir():
            for ldir in brain.rglob("logs"):
                if ldir.is_dir():
                    clean_path(ldir, "Brain session log directory", dry_run)

        print("==> Cleaning ~/.antigravity-ide state...")
        ide = home / ".antigravity-ide"
        clean_path(ide / "logs", "IDE logs", dry_run)
        clean_path(ide / "cache", "IDE cache", dry_run)
        clean_path(ide / "tmp", "IDE temporary files", dry_run)

    if target in ["all", "worktrees", "cache"]:
        print("==> Cleaning ~/.config/sdd and ~/.sdd...")
        clean_path(home / ".config/sdd/cache", "SDD config cache", dry_run)
        clean_path(home / ".config/sdd/tmp", "SDD temp files", dry_run)
        clean_path(home / ".sdd/worktrees", "SDD Worktrees directory", dry_run)

    if target in ["all", "worktrees", "repos"]:
        proj = home / "projects"
        print(f"==> Scanning repositories in {proj}...")
        if proj.is_dir():
            for rdir in proj.iterdir():
                if rdir.is_dir() and (rdir / ".git").exists():
                    print(f"Checking repository: {rdir.name}")
                    if dry_run:
                        print(f"  [dry-run] Would prune worktrees in {rdir.name}")
                    else:
                        subprocess.run(["git", "-C", str(rdir), "worktree", "prune"], stderr=subprocess.DEVNULL)

                    try:
                        branches = (
                            subprocess.check_output(["git", "-C", str(rdir), "branch", "--list", "sdd-wt-*"])
                            .decode()
                            .splitlines()
                        )
                        for b in branches:
                            b = b.replace("*", "").strip()
                            if b:
                                if dry_run:
                                    print(f"  [dry-run] Would delete stale branch '{b}' in {rdir.name}")
                                else:
                                    subprocess.run(
                                        ["git", "-C", str(rdir), "branch", "-D", b, "--quiet"],
                                        stderr=subprocess.DEVNULL,
                                    )
                                    print(f"  Deleted stale branch '{b}' in {rdir.name}")
                    except Exception:
                        pass

                    clean_path(rdir / ".worktrees", "Repository local worktrees directory", dry_run)

    print("\n=== SDD Global Reset Completed Successfully ===")
