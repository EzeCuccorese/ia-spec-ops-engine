"""
workspace_engine.design.changes — New vs. legacy line classification for ``ws design``.

Reuses ``services.changes.base_ref`` to find the merge-base, then diffs the working
tree against it (so committed, staged, and unstaged changes on this branch all count).
Untracked files are reported as wholly new (``None``) rather than a line set.
"""

from __future__ import annotations

import re
from pathlib import Path

from workspace_engine.common import run_command_safe
from workspace_engine.services.changes import base_ref

_HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


def _git(root: Path, *args: str) -> str:
    code, out, _ = run_command_safe(["git", *args], cwd=root, isolated_git=True)
    return out if code == 0 else ""


def _parse_unified_diff(diff_text: str) -> dict[str, set[int]]:
    """Parses ``git diff --unified=0`` output into path -> added/modified line numbers."""
    result: dict[str, set[int]] = {}
    current: str | None = None
    for line in diff_text.splitlines():
        if line.startswith("+++ "):
            target = line[4:].strip()
            if target == "/dev/null":
                current = None
                continue
            current = target[2:] if target.startswith("b/") else target
            result.setdefault(current, set())
        elif line.startswith("@@") and current is not None:
            match = _HUNK_RE.match(line)
            if not match:
                continue
            start = int(match.group(1))
            count = int(match.group(2)) if match.group(2) is not None else 1
            result[current].update(range(start, start + count))
    return result


def changed_lines(root: Path) -> dict[str, set[int] | None]:
    """Lines added/modified vs. the merge-base, including uncommitted work.

    ``None`` for a path means the whole file is new (untracked). A path absent from the
    result was not touched relative to the merge-base.
    """
    result: dict[str, set[int] | None] = {}
    base = base_ref(root)
    if base:
        diff = _git(root, "diff", "--unified=0", base)
        for path, lines in _parse_unified_diff(diff).items():
            result[path] = lines
    for line in _git(root, "status", "--porcelain", "--untracked-files=all").splitlines():
        status = line[:2]
        path = line[3:].split(" -> ")[-1].strip()
        if path and status.strip() == "??":
            result[path] = None
    return result
