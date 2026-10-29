"""Single task store: ``<state>/taskflow/tasks/<ID>/`` holds state, log, rounds and evidence.

Every mutation runs under an exclusive ``flock`` on the task's ``.lock`` and replaces
``state.json`` atomically. The round index is regenerated from ``state.json``, so a
process that dies between writing a round file and the index leaves nothing to repair.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from ..paths import state_dir
from .models import Task, now_iso

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None  # type: ignore[assignment]

TASK_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*")
STATE_FILE = "state.json"
LOG_FILE = "log.md"
FRICTION_FILE = "friction.md"
INDEX_HEADER = "| n | date | phase | role | agent/model | stamp | verdict | status |\n|---|---|---|---|---|---|---|---|\n"


def validate_task_id(task_id: str) -> str:
    if not isinstance(task_id, str) or not TASK_ID.fullmatch(task_id) or ".." in task_id:
        raise ValueError(f"Invalid task id {task_id!r}: use letters, digits, '_', '.', '-'")
    return task_id


def atomic_write_text(path: Path, content: str) -> None:
    """Write ``content`` through a temporary file and ``os.replace``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    except OSError:
        Path(temp).unlink(missing_ok=True)
        raise


class TaskStore:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root if root is not None else state_dir() / "taskflow"
        self.tasks_dir = self.root / "tasks"
        self.tasks_dir.mkdir(parents=True, exist_ok=True)

    # -- paths ---------------------------------------------------------------------------
    def task_dir(self, task_id: str) -> Path:
        path = self.tasks_dir / validate_task_id(task_id)
        if not path.resolve().is_relative_to(self.tasks_dir.resolve()):
            raise ValueError(f"Task path escapes the store: {path}")
        return path

    def rounds_dir(self, task_id: str) -> Path:
        return self.task_dir(task_id) / "rounds"

    def evidence_dir(self, task_id: str) -> Path:
        return self.task_dir(task_id) / "evidence"

    # -- locking and persistence -----------------------------------------------------------
    @contextmanager
    def _lock(self, task_id: str) -> Iterator[Path]:
        directory = self.task_dir(task_id)
        directory.mkdir(parents=True, exist_ok=True)
        with open(directory / ".lock", "a", encoding="utf-8") as handle:
            if fcntl:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield directory
            finally:
                if fcntl:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    @staticmethod
    def _read(directory: Path) -> Task:
        path = directory / STATE_FILE
        if not path.exists():
            raise FileNotFoundError(f"Task '{directory.name}' does not exist")
        try:
            return Task.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, UnicodeDecodeError, TypeError) as exc:
            raise ValueError(f"Task '{directory.name}' state is corrupted: {exc}") from exc

    def _write(self, directory: Path, task: Task) -> Task:
        task.updated_at = now_iso()
        atomic_write_text(
            directory / STATE_FILE, json.dumps(task.to_dict(), indent=2, ensure_ascii=False)
        )
        atomic_write_text(directory / "rounds" / "index.md", render_index(task))
        return task

    def exists(self, task_id: str) -> bool:
        return (self.task_dir(task_id) / STATE_FILE).exists()

    def get(self, task_id: str) -> Task:
        return self._read(self.task_dir(task_id))

    def create(self, task: Task) -> Task:
        with self._lock(task.id) as directory:
            if (directory / STATE_FILE).exists():
                raise FileExistsError(f"Task '{task.id}' already exists")
            return self._write(directory, task)

    def mutate(self, task_id: str, change: Callable[[Task], None], log: str = "") -> Task:
        with self._lock(task_id) as directory:
            task = self._read(directory)
            change(task)
            self._write(directory, task)
        if log:
            self.append_log(task_id, log)
        return task

    def list(self, include_closed: bool = False) -> list[Task]:
        tasks: list[Task] = []
        for path in sorted(self.tasks_dir.glob(f"*/{STATE_FILE}")):
            try:
                task = Task.from_dict(json.loads(path.read_text(encoding="utf-8")))
            except (ValueError, TypeError, OSError):
                continue
            if include_closed or task.is_open():
                tasks.append(task)
        return sorted(tasks, key=lambda task: task.updated_at, reverse=True)

    # -- rounds ----------------------------------------------------------------------------
    def reserve_round(self, task_id: str, phase: str, role: str, agent: str) -> tuple[int, Path]:
        """Reserve the next round number and create its (empty) file under the task lock."""
        with self._lock(task_id) as directory:
            task = self._read(directory)
            rounds = directory / "rounds"
            rounds.mkdir(parents=True, exist_ok=True)
            taken = [int(p.name[:3]) for p in rounds.glob("[0-9][0-9][0-9]-*.md")]
            recorded = [int(r.get("n", 0)) for r in task.rounds]
            number = max([0, *taken, *recorded]) + 1
            path = rounds / f"{number:03d}-{phase}-{role}-{_slug(agent)}.md"
            path.touch(exist_ok=False)
            return number, path

    # -- log -----------------------------------------------------------------------------
    def append_log(self, task_id: str, entry: str) -> None:
        stamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
        path = self.task_dir(task_id) / LOG_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(f"\n### {stamp}\n\n{entry.strip()}\n")

    def read_log(self, task_id: str) -> str:
        path = self.task_dir(task_id) / LOG_FILE
        return path.read_text(encoding="utf-8") if path.exists() else ""


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9.-]+", "-", text).strip("-").lower() or "agent"


def render_index(task: Task) -> str:
    rows = [
        f"| {r['n']:03d} | {r.get('at', '')[:10]} | {r.get('phase', '')} | {r.get('role', '')}"
        f"{'/' + r['focus'] if r.get('focus') else ''} | {r.get('agent', '')} {r.get('model', '')}"
        f" | {str(r.get('stamp', ''))[:12]} | {r.get('verdict', '')} | {r.get('state', '')} |"
        for r in sorted(task.rounds, key=lambda r: int(r["n"]))
    ]
    return INDEX_HEADER + "".join(row + "\n" for row in rows)
