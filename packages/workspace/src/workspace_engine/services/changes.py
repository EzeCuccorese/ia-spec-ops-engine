"""
workspace_engine.services.changes — Changed files and a cheap tree fingerprint.

``ws changed`` lists files changed against the base branch plus uncommitted work;
``ws check`` uses the fingerprint to skip re-running gates on an unchanged tree.
"""

from __future__ import annotations

import hashlib
import stat
from pathlib import Path
from typing import Protocol

from workspace_engine.common import run_command_safe

SCHEMA_VERSION = 1
_HASH_CHUNK_BYTES = 64 * 1024
_MAX_CONTENT_HASH_BYTES = 10 * 1024 * 1024


class _Hasher(Protocol):
    def update(self, data: bytes, /) -> object: ...


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


def _parse_porcelain_z(status_out: str) -> list[tuple[str, str]]:
    """Returns ``(xy_status, path)`` pairs from ``git status --porcelain -z`` output."""
    tokens = status_out.split("\0")
    result: list[tuple[str, str]] = []
    i = 0
    while i < len(tokens):
        entry = tokens[i]
        if len(entry) > 3:
            xy, path = entry[:2], entry[3:]
            result.append((xy, path))
            if "R" in xy or "C" in xy:
                i += 1  # in -z mode, the original path follows the new path
        i += 1
    return result


def changed_files(root: Path) -> list[str]:
    """Committed changes since the base plus staged, unstaged and untracked files."""
    files: set[str] = set()
    base = base_ref(root)
    if base:
        diff_out = _git(root, "diff", "--name-only", "-z", f"{base}...HEAD")
        files.update(path for path in diff_out.split("\0") if path)
    status_out = _git(root, "status", "--porcelain", "-z", "--untracked-files=all")
    for _, path in _parse_porcelain_z(status_out):
        if path:
            files.add(path)
    return sorted(files)


def _hash_untracked_file(digest: _Hasher, path: Path, rel_path: str) -> None:
    try:
        st = path.stat()
    except OSError:
        return
    if not stat.S_ISREG(st.st_mode):
        return
    if st.st_size > _MAX_CONTENT_HASH_BYTES:
        meta = f"{rel_path}\0{st.st_size}\0{st.st_mtime_ns}".encode("utf-8", "replace")
        digest.update(meta)
        return
    try:
        with path.open("rb") as handle:
            digest.update(f"{rel_path}\0".encode("utf-8", "replace"))
            while chunk := handle.read(_HASH_CHUNK_BYTES):
                digest.update(chunk)
    except OSError:
        return


def tree_fingerprint(root: Path) -> str:
    """Changes whenever HEAD or any tracked/untracked working-tree content changes."""
    head = _git(root, "rev-parse", "HEAD").strip()
    status = _git(root, "status", "--porcelain", "-z", "--untracked-files=all")
    diff = _git(root, "diff", "HEAD")
    digest = hashlib.sha256()
    for part in (head, status, diff):
        digest.update(part.encode("utf-8", "replace"))
    for xy, rel_path in _parse_porcelain_z(status):
        if xy == "??":
            _hash_untracked_file(digest, root / rel_path, rel_path)
    return digest.hexdigest()[:16]
