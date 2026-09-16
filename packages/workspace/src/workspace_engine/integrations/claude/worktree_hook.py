"""Fail-open Claude WorktreeCreate destination suggestion hook."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any


def _slug(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return normalized[:80]


def suggest_worktree_path(payload: dict[str, Any], base_dir: Path) -> Path | None:
    root_value = payload.get("root_path")
    worktree_value = payload.get("worktree_base")
    if not isinstance(root_value, str) or not isinstance(worktree_value, str):
        return None
    if not root_value.strip() or not worktree_value.strip() or ".." in Path(worktree_value).parts:
        return None
    repository = _slug(Path(root_value.rstrip("/")).name)
    requested = _slug(Path(worktree_value.rstrip("/")).name)
    if not repository or not requested:
        return None
    resolved_base = base_dir.expanduser().resolve()
    candidate = (resolved_base / f"{repository}-{requested}").resolve()
    if not candidate.is_relative_to(resolved_base):
        return None
    if candidate.exists():
        suffix = hashlib.sha256(f"{root_value}\0{worktree_value}".encode()).hexdigest()[:8]
        candidate = (resolved_base / f"{repository}-{requested}-{suffix}").resolve()
        if not candidate.is_relative_to(resolved_base) or candidate.exists():
            return None
    return candidate


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--base-dir", type=Path)
    try:
        args, _unknown = parser.parse_known_args(argv)
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            return 0
        base = args.base_dir or Path(
            os.environ.get("SPECOPS_WORKTREES_DIR") or Path.home() / "projects" / "worktree"
        )
        destination = suggest_worktree_path(payload, base)
        if destination is None:
            return 0
        print(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "WorktreeCreate",
                        "workTreePath": str(destination),
                    }
                }
            )
        )
    except Exception as exc:
        # Fail-open by design (see module docstring): this hook must never
        # crash or block the caller, so any unexpected error is reported to
        # stderr and swallowed rather than propagated.
        print(f"worktree_hook: ignoring unexpected error: {exc}", file=sys.stderr)
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
