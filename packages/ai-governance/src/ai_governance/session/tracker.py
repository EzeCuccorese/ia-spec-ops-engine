"""
tracker.py — Lightweight cross-session task state manager.
Persists compact state (~300 tokens) in JSON and append-only notes in Markdown.
Enables agents to resume complex multi-repo work with minimum token overhead.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..paths import state_dir

try:
    import fcntl
except ImportError:
    fcntl = None  # type: ignore

STATUS_MAP = {
    "activo": "active",
    "pausado": "paused",
    "cerrado": "closed",
    "active": "active",
    "paused": "paused",
    "closed": "closed",
}


class CorruptTaskError(ValueError):
    """Raised when task state file exists but contains corrupted or unparseable data."""

    pass


@dataclass
class TaskState:
    id: str
    title: str
    status: str = "active"  # active, paused, closed
    summary: str = ""
    steps: list[dict[str, Any]] = field(default_factory=list)  # [{"text": "...", "done": bool}]
    repos: list[dict[str, Any]] = field(
        default_factory=list
    )  # [{"path": "...", "branch": "...", "pr": "..."}]
    links: list[dict[str, str]] = field(default_factory=list)  # [{"title": "...", "url": "..."}]
    facts: list[dict[str, str]] = field(default_factory=list)
    references: list[dict[str, str]] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TaskState:
        if not isinstance(data, dict):
            raise CorruptTaskError(f"Task data must be a dictionary, got {type(data).__name__}")
        raw_status = data.get("status", "active")
        normalized_status = str(STATUS_MAP.get(str(raw_status).lower(), raw_status))
        facts = data.get("facts", data.get("done", []))
        created_at = data.get("created_at", data.get("created", "")) or ""
        updated_at = data.get("updated_at", data.get("updated", "")) or ""
        return cls(
            id=data.get("id", "task"),
            title=data.get("title", ""),
            status=normalized_status,
            summary=data.get("summary", ""),
            steps=data.get("steps", []),
            repos=data.get("repos", []),
            links=data.get("links", []),
            facts=facts if isinstance(facts, list) else [],
            references=data.get(
                "references",
                [
                    {"kind": "jira", "value": str(value), "url": ""}
                    for value in data.get("jira", [])
                ],
            ),
            created_at=str(created_at),
            updated_at=str(updated_at),
        )


def _validate_task_id(task_id: str) -> str:
    """Validate task ID strictly to prevent directory traversal, aliasing, and unsafe characters.

    Allows only [a-zA-Z0-9_.-] and disallows path separators, spaces, '..', and leading dots.
    """
    if not isinstance(task_id, str) or not task_id.strip():
        raise ValueError(f"Task ID must be a non-empty string, got {task_id!r}")
    if "/" in task_id or "\\" in task_id or ".." in task_id or re.search(r"\s", task_id):
        raise ValueError(
            f"Invalid task ID {task_id!r}: contains path separators, spaces, or traversal sequences"
        )
    if not re.fullmatch(r"[a-zA-Z0-9_.-]+", task_id):
        raise ValueError(f"Invalid characters in task ID {task_id!r}")
    if task_id.startswith("."):
        raise ValueError(f"Task ID cannot start with a dot: {task_id!r}")
    return task_id


_sanitize_task_id = _validate_task_id


def _atomic_write_text(path: Path, content: str) -> None:
    """Write text atomically to destination path using a temporary file and os.replace."""
    temp_dir = path.parent
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=temp_dir,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as tf:
            tf.write(content)
            tf.flush()
            os.fsync(tf.fileno())
            temp_path = Path(tf.name)
        temp_path.replace(path)
    except OSError:
        if temp_path and temp_path.exists():
            temp_path.unlink(missing_ok=True)
        raise


class SessionTracker:
    _validate_task_id = staticmethod(_validate_task_id)
    _sanitize_task_id = staticmethod(_validate_task_id)

    DEFAULT_COMPACT_LIMITS = {
        "steps": 8,
        "facts": 12,
        "links": 10,
        "references": 10,
        "repos": 10,
    }

    def __init__(
        self, root_dir: Path | None = None, compact_limits: dict[str, int] | None = None
    ) -> None:
        self.root_dir = root_dir if root_dir is not None else state_dir() / "progress"
        self.tasks_dir = self.root_dir / "tasks"

        try:
            self.tasks_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise OSError(
                f"Configured progress directory {self.root_dir} is inaccessible or cannot be created: {e}"
            ) from e
        self.compact_limits = dict(self.DEFAULT_COMPACT_LIMITS)
        if compact_limits:
            self.compact_limits.update(compact_limits)

    def _json_path(self, task_id: str) -> Path:
        safe_id = self._validate_task_id(task_id)
        raw_path = self.tasks_dir / f"{safe_id}.json"
        resolved_tasks = self.tasks_dir.resolve()
        resolved_path = raw_path.resolve()
        if not resolved_path.is_relative_to(resolved_tasks):
            raise ValueError(
                f"Task path {resolved_path} traverses outside tasks directory {self.tasks_dir}"
            )
        if raw_path.is_symlink():
            target = raw_path.resolve()
            if not target.is_relative_to(resolved_tasks):
                raise ValueError(f"Symlink {raw_path} targets outside tasks directory: {target}")
        return raw_path

    def _md_path(self, task_id: str) -> Path:
        safe_id = self._validate_task_id(task_id)
        raw_path = self.tasks_dir / f"{safe_id}.md"
        resolved_tasks = self.tasks_dir.resolve()
        resolved_path = raw_path.resolve()
        if not resolved_path.is_relative_to(resolved_tasks):
            raise ValueError(
                f"Task path {resolved_path} traverses outside tasks directory {self.tasks_dir}"
            )
        if raw_path.is_symlink():
            target = raw_path.resolve()
            if not target.is_relative_to(resolved_tasks):
                raise ValueError(f"Symlink {raw_path} targets outside tasks directory: {target}")
        return raw_path

    def get_task(self, task_id: str) -> TaskState | None:
        p = self._json_path(task_id)
        if not p.exists():
            return None
        try:
            content = p.read_text(encoding="utf-8")
            data = json.loads(content)
            return TaskState.from_dict(data)
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError, TypeError) as e:
            raise CorruptTaskError(f"Task state file for '{task_id}' is corrupted: {e}") from e
        except OSError as e:
            raise OSError(f"Failed to read task '{task_id}' from {p}: {e}") from e

    @contextmanager
    def _task_lock(self, task_id: str) -> Iterator[Path]:
        p = self._json_path(task_id)
        lock_file = p.with_suffix(".lock")
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(lock_file, "a", encoding="utf-8") as lf:
            if fcntl:
                fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
            try:
                yield p
            finally:
                if fcntl:
                    fcntl.flock(lf.fileno(), fcntl.LOCK_UN)

    @staticmethod
    def _read_task_path(path: Path, task_id: str) -> TaskState:
        if not path.exists():
            raise FileNotFoundError(f"Task '{task_id}' does not exist")
        try:
            return TaskState.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError, TypeError) as e:
            raise CorruptTaskError(f"Task state file for '{task_id}' is corrupted: {e}") from e

    @staticmethod
    def _write_task_path(path: Path, task: TaskState) -> TaskState:
        task.updated_at = datetime.now(UTC).isoformat()
        _atomic_write_text(path, json.dumps(task.to_dict(), indent=2, ensure_ascii=False))
        return task

    def create_task(self, task: TaskState) -> TaskState:
        with self._task_lock(task.id) as p:
            if p.exists():
                raise FileExistsError(f"Task '{task.id}' already exists")
            return self._write_task_path(p, task)

    def update_task(self, task: TaskState) -> TaskState:
        p = self._json_path(task.id)
        if not p.exists():
            raise FileNotFoundError(f"Task '{task.id}' does not exist")
        return self.save_task(task)

    def save_task(self, task: TaskState) -> TaskState:
        try:
            with self._task_lock(task.id) as p:
                return self._write_task_path(p, task)
        except OSError as e:
            raise OSError(f"Failed to save task '{task.id}': {e}") from e

    def _mutate_task(
        self,
        task_id: str,
        mutation: Callable[[TaskState], None],
        *,
        log_entry: str | None = None,
    ) -> TaskState:
        archived: list[str] = []
        try:
            with self._task_lock(task_id) as p:
                task = self._read_task_path(p, task_id)
                mutation(task)
                for field_name, limit in self.compact_limits.items():
                    values = getattr(task, field_name)
                    while limit >= 0 and len(values) > limit:
                        old = values.pop(0)
                        text = (
                            old.get("text")
                            or old.get("title")
                            or old.get("value")
                            or old.get("path")
                        )
                        archived.append(f"Archived {field_name}: {text}")
                self._write_task_path(p, task)
        except OSError as e:
            raise OSError(f"Failed to update task '{task_id}': {e}") from e
        for entry in archived:
            self.append_log(task_id, entry)
        if log_entry:
            self.append_log(task_id, log_entry)
        return task

    def update_summary(self, task_id: str, summary: str) -> TaskState:
        return self._mutate_task(task_id, lambda task: setattr(task, "summary", summary[:500]))

    def add_step(self, task_id: str, text: str) -> TaskState:
        if not text.strip():
            raise ValueError("Step text must not be empty")
        return self._mutate_task(
            task_id,
            lambda task: task.steps.append({"text": text.strip(), "done": False}),
        )

    @staticmethod
    def _find_item(items: list[dict[str, Any]], selector: str | int) -> int:
        if isinstance(selector, int) or str(selector).isdigit():
            index = int(selector) - 1
            if 0 <= index < len(items):
                return index
        else:
            for index, item in enumerate(items):
                if item.get("text") == selector:
                    return index
        raise ValueError(f"Item not found: {selector}")

    def complete_step(self, task_id: str, selector: str | int) -> TaskState:
        def mutate(task: TaskState) -> None:
            task.steps[self._find_item(task.steps, selector)]["done"] = True

        return self._mutate_task(task_id, mutate)

    def remove_step(self, task_id: str, selector: str | int) -> TaskState:
        def mutate(task: TaskState) -> None:
            task.steps.pop(self._find_item(task.steps, selector))

        return self._mutate_task(task_id, mutate)

    def add_fact(self, task_id: str, text: str) -> TaskState:
        if not text.strip():
            raise ValueError("Fact text must not be empty")
        return self._mutate_task(task_id, lambda task: task.facts.append({"text": text.strip()}))

    def add_link(self, task_id: str, title: str, url: str) -> TaskState:
        if not title.strip() or not url.strip():
            raise ValueError("Link title and URL must not be empty")
        return self._mutate_task(
            task_id, lambda task: task.links.append({"title": title.strip(), "url": url.strip()})
        )

    def add_reference(self, task_id: str, kind: str, value: str, url: str = "") -> TaskState:
        if not kind.strip() or not value.strip():
            raise ValueError("Reference kind and value must not be empty")
        reference = {"kind": kind.strip(), "value": value.strip(), "url": url.strip()}
        return self._mutate_task(task_id, lambda task: task.references.append(reference))

    def add_repository(
        self,
        task_id: str,
        path: Path,
        *,
        branch: str = "",
        pr: str = "",
        worktree: str = "",
    ) -> TaskState:
        normalized = str(path.expanduser().resolve())

        def mutate(task: TaskState) -> None:
            existing = next((repo for repo in task.repos if repo.get("path") == normalized), None)
            value = existing if existing is not None else {"path": normalized}
            if branch:
                value["branch"] = branch
            if pr:
                value["pr"] = str(pr)
            if worktree:
                value["worktree"] = worktree
            if existing is None:
                task.repos.append(value)

        return self._mutate_task(task_id, mutate)

    def remove_repository(self, task_id: str, path: Path) -> TaskState:
        normalized = str(path.expanduser().resolve())

        def mutate(task: TaskState) -> None:
            original = len(task.repos)
            task.repos = [repo for repo in task.repos if repo.get("path") != normalized]
            if len(task.repos) == original:
                raise ValueError(f"Repository not found: {normalized}")

        return self._mutate_task(task_id, mutate)

    def sync_repositories(
        self, task_id: str, branch_resolver: Callable[[Path], str | None]
    ) -> TaskState:
        def mutate(task: TaskState) -> None:
            for repository in task.repos:
                path = Path(repository.get("path", ""))
                branch = branch_resolver(path) if path.is_dir() else None
                if branch:
                    repository["branch"] = branch

        return self._mutate_task(task_id, mutate)

    def add_note(self, task_id: str, text: str) -> TaskState:
        if not text.strip():
            raise ValueError("Note text must not be empty")
        return self._mutate_task(task_id, lambda _task: None, log_entry=text.strip())

    def append_log(self, task_id: str, entry: str) -> None:
        md_file = self._md_path(task_id)
        ts = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
        formatted_entry = f"\n### {ts}\n\n{entry.strip()}\n"
        try:
            md_file.parent.mkdir(parents=True, exist_ok=True)
            with open(md_file, "a+", encoding="utf-8") as f:
                if fcntl:
                    fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                try:
                    f.seek(0, os.SEEK_END)
                    f.write(formatted_entry)
                    f.flush()
                    os.fsync(f.fileno())
                finally:
                    if fcntl:
                        fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        except OSError as e:
            raise OSError(f"Failed to append log for task '{task_id}' to {md_file}: {e}") from e

    def read_log(self, task_id: str) -> str:
        md_file = self._md_path(task_id)
        if not md_file.exists():
            return ""
        try:
            with open(md_file, encoding="utf-8") as f:
                if fcntl:
                    fcntl.flock(f.fileno(), fcntl.LOCK_SH)
                try:
                    return f.read()
                finally:
                    if fcntl:
                        fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        except OSError as e:
            raise OSError(f"Failed to read log for task '{task_id}' from {md_file}: {e}") from e

    def close_task(self, task_id: str, reason: str = "") -> TaskState:
        return self._mutate_task(
            task_id,
            lambda task: setattr(task, "status", "closed"),
            log_entry=f"Closed task: {reason}" if reason else None,
        )

    def reopen_task(self, task_id: str, reason: str = "") -> TaskState:
        return self._mutate_task(
            task_id,
            lambda task: setattr(task, "status", "active"),
            log_entry=f"Reopened task: {reason}" if reason else None,
        )

    def pause_task(self, task_id: str, reason: str = "") -> TaskState:
        return self._mutate_task(
            task_id,
            lambda task: setattr(task, "status", "paused"),
            log_entry=f"Paused task: {reason}" if reason else None,
        )

    def resume_task(self, task_id: str) -> TaskState:
        return self._mutate_task(
            task_id,
            lambda task: setattr(task, "status", "active") if task.status == "paused" else None,
        )

    def list_active_tasks(self) -> list[TaskState]:
        return self.list_tasks()

    def list_tasks(self, include_closed: bool = False) -> list[TaskState]:
        res: list[TaskState] = []
        if not self.tasks_dir.exists():
            return res
        for p in sorted(self.tasks_dir.glob("*.json")):
            try:
                task = TaskState.from_dict(json.loads(p.read_text(encoding="utf-8")))
                if include_closed or task.status not in ("closed", "cerrado"):
                    res.append(task)
            except (json.JSONDecodeError, UnicodeDecodeError, OSError, ValueError, TypeError):
                continue
        return sorted(res, key=lambda task: task.updated_at, reverse=True)

    def digest(self, focus_id: str | None = None, max_chars: int = 1600) -> str:
        tasks = self.list_tasks()
        focus = next((task for task in tasks if task.id == focus_id), None) if focus_id else None
        if focus is None and tasks:
            focus = tasks[0]
        lines = [f"PROGRESS ({len(tasks)} open)"]
        if focus:
            lines.append(f"- {focus.id} [{focus.status}]: {focus.summary or focus.title}")
            pending = [step["text"] for step in focus.steps if not step.get("done")][:5]
            if pending:
                lines.append("  next: " + "; ".join(pending))
        others = [task.id for task in tasks if focus is None or task.id != focus.id]
        if others:
            lines.append("  others: " + ", ".join(others[:8]))
        text = "\n".join(lines)
        if max_chars > 0 and len(text) > max_chars:
            return text[: max(0, max_chars - 1)].rstrip() + "…"
        return text
