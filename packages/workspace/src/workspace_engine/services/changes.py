"""
workspace_engine.services.changes — Changed files and a cheap tree fingerprint.

``ws changed`` lists files changed against the base branch plus uncommitted work;
``ws check`` uses the fingerprint to skip re-running gates on an unchanged tree.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from workspace_engine.common import run_command_safe

SCHEMA_VERSION = 1


def _git(root: Path, *args: str) -> str:
    code, out, _ = run_command_safe(["git", *args], cwd=root, isolated_git=True)
    return out if code == 0 else ""


def base_ref(root: Path) -> str | None:
    """Merge-base with the default branch (origin/HEAD, main or master)."""
    candidates = [_git(root, "symbolic-ref", "--quiet", "refs/remotes/origin/HEAD").strip()]
    candidates += ["origin/main", "origin/master", "main", "master"]
    for candidate in filter(None, candidates):
        merge_base = _git(root, "merge-base", "HEAD", candidate).strip()
        if merge_base:
            return merge_base
    return None


def changed_files(root: Path) -> list[str]:
    """Committed changes since the base plus staged, unstaged and untracked files."""
    files: set[str] = set()
    base = base_ref(root)
    if base:
        files.update(_git(root, "diff", "--name-only", f"{base}...HEAD").split())
    for line in _git(root, "status", "--porcelain", "--untracked-files=all").splitlines():
        path = line[3:].split(" -> ")[-1].strip()
        if path:
            files.add(path)
    return sorted(files)


def tree_fingerprint(root: Path) -> str:
    """Changes whenever HEAD or any tracked/untracked working-tree content changes."""
    head = _git(root, "rev-parse", "HEAD").strip()
    status = _git(root, "status", "--porcelain", "--untracked-files=all")
    diff = _git(root, "diff", "HEAD")
    digest = hashlib.sha256()
    for part in (head, status, diff):
        digest.update(part.encode("utf-8", "replace"))
    for line in status.splitlines():
        if line.startswith("??"):
            path = root / line[3:].strip()
            if path.is_file():
                digest.update(path.read_bytes())
    return digest.hexdigest()[:16]
