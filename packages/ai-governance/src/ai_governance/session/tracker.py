"""
tracker.py — Lightweight cross-session task state manager.
Persists compact state (~300 tokens) in JSON and append-only notes in Markdown.
Enables agents to resume complex multi-repo work with minimum token overhead.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

STATUS_MAP = {
    "activo": "active",
    "pausado": "paused",
    "cerrado": "closed",
    "active": "active",
    "paused": "paused",
    "closed": "closed",
}


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
        raw_status = data.get("status", "active")
        normalized_status = STATUS_MAP.get(raw_status.lower(), raw_status)
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


def _sanitize_task_id(task_id: str) -> str:
    """Sanitize task ID to prevent directory traversal and unsafe characters.

    Allows only [a-zA-Z0-9_.-], strips path separators and leading dots/slashes.
    """
    if not isinstance(task_id, str):
        raise ValueError(f"Task ID must be a string, got {type(task_id).__name__}")
    cleaned = task_id.replace("/", "").replace("\\", "")
    cleaned = re.sub(r"[^a-zA-Z0-9_.-]", "", cleaned)
    cleaned = cleaned.lstrip("./\\")
    if not cleaned:
        raise ValueError(f"Invalid or unsafe task ID: {task_id!r}")
    return cleaned


class SessionTracker:
    _sanitize_task_id = staticmethod(_sanitize_task_id)

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
        except OSError:
            # Fallback for sandbox, CI, or restricted filesystems
            fallback = Path.cwd() / ".specops" / "progress"
            self.tasks_dir = fallback / "tasks"
            self.archive_dir = fallback / "archived"
            try:
                self.tasks_dir.mkdir(parents=True, exist_ok=True)
                self.archive_dir.mkdir(parents=True, exist_ok=True)
            except OSError:
                pass

    def _json_path(self, task_id: str) -> Path:
        safe_id = self._sanitize_task_id(task_id)
        resolved_tasks = self.tasks_dir.resolve()
        path = (self.tasks_dir / f"{safe_id}.json").resolve()
        if not path.is_relative_to(resolved_tasks):
            raise ValueError(f"Task path {path} traverses outside tasks directory {self.tasks_dir}")
        return path

    def _md_path(self, task_id: str) -> Path:
        safe_id = self._sanitize_task_id(task_id)
        resolved_tasks = self.tasks_dir.resolve()
        path = (self.tasks_dir / f"{safe_id}.md").resolve()
        if not path.is_relative_to(resolved_tasks):
            raise ValueError(f"Task path {path} traverses outside tasks directory {self.tasks_dir}")
        return path

    def get_task(self, task_id: str) -> TaskState | None:
        try:
            p = self._json_path(task_id)
        except ValueError:
            return None
        if not p.exists():
            return None
        try:
            return TaskState.from_dict(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            return None

    def save_task(self, task: TaskState) -> None:
        task.updated_at = datetime.now(UTC).isoformat()
        p = self._json_path(task.id)
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(task.to_dict(), indent=2), encoding="utf-8")
        except OSError as e:
            raise OSError(f"Failed to save task '{task.id}' to {p}: {e}") from e

    def append_log(self, task_id: str, entry: str) -> None:
        md_file = self._md_path(task_id)
        ts = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
        try:
            md_file.parent.mkdir(parents=True, exist_ok=True)
            with open(md_file, "a", encoding="utf-8") as f:
                f.write(f"\n### {ts}\n\n{entry.strip()}\n")
        except OSError as e:
            raise OSError(f"Failed to append log for task '{task_id}' to {md_file}: {e}") from e

    def read_log(self, task_id: str) -> str:
        try:
            md_file = self._md_path(task_id)
        except ValueError:
            return ""
        if not md_file.exists():
            return ""
        return md_file.read_text(encoding="utf-8")

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
