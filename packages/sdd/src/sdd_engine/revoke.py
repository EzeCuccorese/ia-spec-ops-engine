"""
devscripts.sdd.revoke — Revoke and clean SDD configuration & AI adapters in repository.
"""

from __future__ import annotations

import datetime
import json
import os
from pathlib import Path
import shutil
import sys
from typing import Dict, List, Optional, Tuple, Union

from sdd_engine.utils import find_project_root



def backup_specify_dir(target_dir: Union[str, Path] = ".") -> Optional[Path]:
    td = Path(target_dir).resolve()
    specify_dir = td / ".specify"

    if not specify_dir.exists():
        return None

    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d-%H%M%S")
    backup_dir = td / f".specify-backup-{ts}"

    shutil.copytree(specify_dir, backup_dir, dirs_exist_ok=True)
    return backup_dir


def find_latest_backup(target_dir: Union[str, Path] = ".") -> Optional[Path]:
    td = Path(target_dir).resolve()
    backups = sorted(td.glob(".specify-backup-*"), reverse=True)
    for b in backups:
        if b.is_dir():
            return b
    return None


def restore_backup_specs(backup_dir: Path, target_dir: Union[str, Path] = ".") -> bool:
    td = Path(target_dir).resolve()
    specify_dir = td / ".specify"
    specify_dir.mkdir(parents=True, exist_ok=True)

    restored_any = False
    for sub in ["specs", "history", "memory.md", "agents.json"]:
        src = backup_dir / sub
        dst = specify_dir / sub
        if src.exists():
            if src.is_dir():
                shutil.copytree(src, dst, dirs_exist_ok=True)
            else:
                shutil.copy2(src, dst)
            restored_any = True

    return restored_any


def revoke_sdd_configuration(
    target_dir: Union[str, Path] = ".",
    create_backup: bool = True,
    force: bool = False,
) -> Tuple[bool, Optional[Path], List[str]]:
    """
    Revokes SDD configuration and AI adapters from the project directory.

    Returns:
        Tuple[bool, Optional[Path], List[str]]: (success, backup_path_if_created, list_of_removed_items)
    """
    td = Path(target_dir).resolve()

    if not force and sys.stdin and sys.stdin.isatty():
        try:
            ans = input(f"⚠️  Warning: Revoking SDD will remove all generated AI adapters and .specify config in '{td.name}'.\nProceed? [y/N]: ").strip().lower()
            if ans != "y":
                print("Operation cancelled by user.")
                return False, None, []
        except (EOFError, KeyboardInterrupt):
            print("\nOperation cancelled.")
            return False, None, []

    backup_path: Optional[Path] = None
    if create_backup:
        backup_path = backup_specify_dir(td)

    removed_items: List[str] = []

    # Paths / Directories to clean
    targets_to_remove = [
        td / ".specify",
        td / ".agents",
        td / ".claude",
        td / ".gemini",
        td / ".cursor",
        td / "CLAUDE.md",
        td / "AGENTS.md",
        td / "CHATGPT.md",
        td / ".cursorrules",
        td / ".windsurfrules",
        td / ".github" / "copilot-instructions.md",
        td / ".github" / "prompts",
        td / ".github" / "hooks",
    ]

    for item in targets_to_remove:
        if item.exists():
            if item.is_dir() and not item.is_symlink():
                shutil.rmtree(item, ignore_errors=True)
            else:
                item.unlink(missing_ok=True)
            removed_items.append(str(item.relative_to(td)))

    return True, backup_path, removed_items
