"""
Resolves the task bound to the current branch (Jira key) or repository.
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Iterable
from pathlib import Path
from typing import Protocol

# Match standard Jira keys like ONB-1234, PROJ-56, etc.
JIRA_RE = re.compile(r"([A-Z]{2,10}-\d+)", re.IGNORECASE)


class TaskLike(Protocol):
    id: str
    repos: list[dict]
    references: list[dict]


class TaskResolver:
    @staticmethod
    def _git_branch(repo_dir: Path | None = None) -> str | None:
        return TaskResolver._git_value(["git", "branch", "--show-current"], repo_dir)

    @staticmethod
    def _git_root(repo_dir: Path | None = None) -> Path | None:
        value = TaskResolver._git_value(["git", "rev-parse", "--show-toplevel"], repo_dir)
        return Path(value).resolve() if value else None

    @staticmethod
    def _git_value(command: list[str], repo_dir: Path | None = None) -> str | None:
        try:
            res = subprocess.run(
                command,
                cwd=str(repo_dir) if repo_dir else None,
                capture_output=True,
                text=True,
                timeout=2,
            )
            if res.returncode == 0 and res.stdout.strip():
                return res.stdout.strip()
        except (OSError, subprocess.SubprocessError):
            pass
        return None

    @staticmethod
    def resolve_from_git(repo_dir: Path | None = None) -> str | None:
        branch = TaskResolver._git_branch(repo_dir)
        match = JIRA_RE.search(branch or "")
        if match:
            return match.group(1).upper()
        return None

    @staticmethod
    def resolve_from_context(tasks: Iterable[TaskLike], repo_dir: Path | None = None) -> str | None:
        task_list = list(tasks)
        branch = TaskResolver._git_branch(repo_dir)
        match = JIRA_RE.search(branch or "")
        if match:
            key = match.group(1).upper()
            matches = [
                task.id
                for task in task_list
                if task.id.upper() == key
                or any(
                    ref.get("kind") == "jira" and str(ref.get("value", "")).upper() == key
                    for ref in task.references
                )
            ]
            if len(matches) == 1:
                return matches[0]

        candidates = TaskResolver.bound_to(task_list, repo_dir)
        return candidates[0] if len(candidates) == 1 else None

    @staticmethod
    def _binds(task: TaskLike, root: Path) -> bool:
        return any(Path(repo.get("path", "")).expanduser().resolve() == root for repo in task.repos)

    @staticmethod
    def bound_to(tasks: Iterable[TaskLike], repo_dir: Path | None = None) -> list[str]:
        """Tasks bound to this repository, narrowed when several share it: active over
        paused, and a parent gives way to the subtask it has switched to."""
        root = TaskResolver._git_root(repo_dir)
        if root is None:
            return []
        bound = [task for task in tasks if TaskResolver._binds(task, root)]
        return TaskResolver._narrow(bound)

    @staticmethod
    def _narrow(bound: list[TaskLike]) -> list[str]:
        active = [task for task in bound if getattr(task, "status", "active") == "active"]
        pool = active or bound
        ids = {task.id for task in pool}
        leaves = [task.id for task in pool if getattr(task, "active_subtask", "") not in ids]
        return leaves or [task.id for task in pool]
