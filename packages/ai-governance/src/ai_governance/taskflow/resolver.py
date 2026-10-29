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
    def root_of_target(target: Path) -> Path | None:
        """Repository a file path belongs to: symlinks followed, and a path that does not
        exist yet is looked up from its nearest existing ancestor."""
        probe = target.expanduser().resolve()
        while not probe.exists() and probe != probe.parent:
            probe = probe.parent
        return TaskResolver._git_root(probe if probe.is_dir() else probe.parent)

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
        except (OSError, subprocess.SubprocessError):
            return None  # no git, or a directory that does not exist: not a repository
        return res.stdout.strip() or None if res.returncode == 0 else None

    @staticmethod
    def resolve_from_git(repo_dir: Path | None = None) -> str | None:
        branch = TaskResolver._git_branch(repo_dir)
        match = JIRA_RE.search(branch or "")
        if match:
            return match.group(1).upper()
        return None

    @staticmethod
    def _matches_branch(task: TaskLike, key: str) -> bool:
        return task.id.upper() == key or any(
            ref.get("kind") == "jira" and str(ref.get("value", "")).upper() == key
            for ref in task.references
        )

    @staticmethod
    def resolve_from_context(tasks: Iterable[TaskLike], repo_dir: Path | None = None) -> str | None:
        """The task for this directory: bound open tasks narrowed first; the branch's Jira
        key then picks inside that pool, or among all open tasks when none is bound."""
        task_list = list(tasks)
        pool = TaskResolver._narrowed_bound(task_list, repo_dir)
        match = JIRA_RE.search(TaskResolver._git_branch(repo_dir) or "")
        if match:
            key = match.group(1).upper()
            candidates = pool or [
                t for t in task_list if getattr(t, "status", "active") != "closed"
            ]
            hits = [t.id for t in candidates if TaskResolver._matches_branch(t, key)]
            if len(hits) == 1:
                return hits[0]
        return pool[0].id if len(pool) == 1 else None

    @staticmethod
    def _binds(task: TaskLike, root: Path) -> bool:
        return any(Path(repo.get("path", "")).expanduser().resolve() == root for repo in task.repos)

    @staticmethod
    def bound_to(tasks: Iterable[TaskLike], repo_dir: Path | None = None) -> list[str]:
        """Open tasks bound to this repository, narrowed when several share it: active over
        paused, and a parent (or sibling) gives way to the subtask it switched to."""
        return [t.id for t in TaskResolver._narrowed_bound(list(tasks), repo_dir)]

    @staticmethod
    def _narrowed_bound(tasks: list[TaskLike], repo_dir: Path | None) -> list[TaskLike]:
        root = TaskResolver._git_root(repo_dir)
        if root is None:
            return []
        bound = [
            t
            for t in tasks
            if getattr(t, "status", "active") != "closed" and TaskResolver._binds(t, root)
        ]
        return TaskResolver._narrow(bound, {t.id: t for t in tasks})

    @staticmethod
    def _narrow(bound: list[TaskLike], everyone: dict[str, TaskLike]) -> list[TaskLike]:
        active = [t for t in bound if getattr(t, "status", "active") == "active"]
        pool = active or bound
        ids = {t.id for t in pool}

        def gives_way(task: TaskLike) -> bool:
            if getattr(task, "active_subtask", "") in ids:
                return True
            parent = everyone.get(getattr(task, "parent", ""))
            chosen = getattr(parent, "active_subtask", "")
            return chosen in ids and chosen != task.id

        return [t for t in pool if not gives_way(t)] or pool
