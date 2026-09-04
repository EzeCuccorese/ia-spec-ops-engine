"""
tracker.py — Lightweight cross-session task state manager.
Persists compact state (~300 tokens) in JSON and append-only notes in Markdown.
Enables agents to resume complex multi-repo work with minimum token overhead.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
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
    repos: list[dict[str, Any]] = field(default_factory=list)  # [{"path": "...", "branch": "...", "pr": "..."}]
    links: list[dict[str, str]] = field(default_factory=list)  # [{"title": "...", "url": "..."}]
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

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


class SessionTracker:
    def __init__(self, root_dir: Path | None = None) -> None:
        custom = os.environ.get("CLAUDE_PROGRESS_DIR")
        self.root_dir = root_dir or (Path(custom) if custom else Path.home() / ".claude" / "progress")
        
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
        return self.tasks_dir / f"{task_id}.json"

    def _md_path(self, task_id: str) -> Path:
        return self.tasks_dir / f"{task_id}.md"

    def get_task(self, task_id: str) -> TaskState | None:
        p = self._json_path(task_id)
        if not p.exists():
            return None
        try:
            return TaskState.from_dict(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            return None

    def save_task(self, task: TaskState) -> None:
        task.updated_at = datetime.now(timezone.utc).isoformat()
        p = self._json_path(task.id)
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(task.to_dict(), indent=2), encoding="utf-8")
        except OSError:
            pass

    def append_log(self, task_id: str, entry: str) -> None:
        md_file = self._md_path(task_id)
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        try:
            md_file.parent.mkdir(parents=True, exist_ok=True)
            with open(md_file, "a", encoding="utf-8") as f:
                f.write(f"\n### {ts}\n\n{entry.strip()}\n")
        except OSError:
            pass

    def read_log(self, task_id: str) -> str:
        md_file = self._md_path(task_id)
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
