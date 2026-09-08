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
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

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
    updated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TaskState:
        if not isinstance(data, dict):
            raise CorruptTaskError(f"Task data must be a dictionary, got {type(data).__name__}")
        raw_status = data.get("status", "active")
        normalized_status = STATUS_MAP.get(str(raw_status).lower(), raw_status)
        return cls(
            id=data.get("id", "task"),
            title=data.get("title", ""),
            status=normalized_status,
            summary=data.get("summary", ""),
            steps=data.get("steps", []),
            repos=data.get("repos", []),
            links=data.get("links", []),
            updated_at=data.get("updated_at", ""),
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
    except Exception:
        if temp_path and temp_path.exists():
            temp_path.unlink(missing_ok=True)
        raise


class SessionTracker:
    _validate_task_id = staticmethod(_validate_task_id)
    _sanitize_task_id = staticmethod(_validate_task_id)

    def __init__(self, root_dir: Path | None = None) -> None:
        if root_dir is not None:
            self.root_dir = root_dir
        else:
            env_dir = os.environ.get("SPECOPS_PROGRESS_DIR") or os.environ.get(
                "CLAUDE_PROGRESS_DIR"
            )
            if env_dir:
                self.root_dir = Path(env_dir)
            else:
                specops_dir = Path.home() / ".specops" / "progress"
                claude_dir = Path.home() / ".claude" / "progress"
                if claude_dir.exists() and not specops_dir.exists():
                    self.root_dir = claude_dir
                else:
                    self.root_dir = specops_dir

        legacy_dir = self.root_dir / "tareas"
        self.tasks_dir = self.root_dir / "tasks"
        if legacy_dir.exists() and not self.tasks_dir.exists():
            self.tasks_dir = legacy_dir

        legacy_archive = self.root_dir / "archivadas"
        self.archive_dir = self.root_dir / "archived"
        if legacy_archive.exists() and not self.archive_dir.exists():
            self.archive_dir = legacy_archive

        try:
            self.tasks_dir.mkdir(parents=True, exist_ok=True)
            self.archive_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise OSError(
                f"Configured progress directory {self.root_dir} is inaccessible or cannot be created: {e}"
            ) from e

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

    def create_task(self, task: TaskState) -> TaskState:
        p = self._json_path(task.id)
        if p.exists():
            raise FileExistsError(f"Task '{task.id}' already exists")
        return self.save_task(task)

    def update_task(self, task: TaskState) -> TaskState:
        p = self._json_path(task.id)
        if not p.exists():
            raise FileNotFoundError(f"Task '{task.id}' does not exist")
        return self.save_task(task)

    def save_task(self, task: TaskState) -> TaskState:
        task.updated_at = datetime.now(UTC).isoformat()
        p = self._json_path(task.id)
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            lock_file = p.with_suffix(".lock")
            with open(lock_file, "a", encoding="utf-8") as lf:
                if fcntl:
                    fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
                try:
                    payload = json.dumps(task.to_dict(), indent=2)
                    _atomic_write_text(p, payload)
                finally:
                    if fcntl:
                        fcntl.flock(lf.fileno(), fcntl.LOCK_UN)
        except OSError as e:
            raise OSError(f"Failed to save task '{task.id}' to {p}: {e}") from e
        return task

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
        task = self.get_task(task_id)
        if task is None:
            raise FileNotFoundError(f"Task '{task_id}' does not exist")
        task.status = "closed"
        if reason:
            self.append_log(task_id, f"Closed task: {reason}")
        return self.save_task(task)

    def reopen_task(self, task_id: str, reason: str = "") -> TaskState:
        task = self.get_task(task_id)
        if task is None:
            raise FileNotFoundError(f"Task '{task_id}' does not exist")
        task.status = "active"
        if reason:
            self.append_log(task_id, f"Reopened task: {reason}")
        return self.save_task(task)

    def pause_task(self, task_id: str, reason: str = "") -> TaskState:
        task = self.get_task(task_id)
        if task is None:
            raise FileNotFoundError(f"Task '{task_id}' does not exist")
        task.status = "paused"
        if reason:
            self.append_log(task_id, f"Paused task: {reason}")
        return self.save_task(task)

    def resume_task(self, task_id: str) -> TaskState:
        task = self.get_task(task_id)
        if task is None:
            raise FileNotFoundError(f"Task '{task_id}' does not exist")
        if task.status == "paused":
            task.status = "active"
            self.save_task(task)
        return task

    def list_active_tasks(self) -> list[TaskState]:
        res = []
        if not self.tasks_dir.exists():
            return res
        for p in sorted(self.tasks_dir.glob("*.json")):
            try:
                task = TaskState.from_dict(json.loads(p.read_text(encoding="utf-8")))
                if task.status not in ("closed", "cerrado"):
                    res.append(task)
            except Exception:
                continue
        return res
