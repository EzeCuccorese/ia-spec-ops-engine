"""Full-output log store: private (0600), bounded (age + count), addressable by id."""

from __future__ import annotations

import contextlib
import hashlib
import os
import re
import time
from pathlib import Path

from workspace_engine._config_core import ConfigError, xdg_dir
from workspace_engine.settings import SETTINGS, effective

RETENTION_DAYS: int | None = None  # None: the `logs.retention_days` setting (default 7)
MAX_LOGS: int | None = None  # None: `logs.max_entries` (default 200)


def _setting(key: str) -> int:
    try:
        return int(effective()[key].value)  # type: ignore[call-overload]
    except ConfigError:
        return int(next(s.default for s in SETTINGS if s.key == key))  # type: ignore[call-overload]


def logs_dir() -> Path:
    return Path(os.environ.get("WORKSPACE_LOG_DIR") or xdg_dir("state", "workspace") / "logs")


def save(text: str, command: str) -> str:
    """Stores ``text`` and returns its id (short content hash)."""
    directory = logs_dir()
    directory.mkdir(parents=True, exist_ok=True)
    log_id = hashlib.sha256(f"{time.time_ns()}{command}".encode()).hexdigest()[:10]
    path = directory / f"{log_id}.log"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(f"$ {command}\n{text}")
    prune(directory)
    return log_id


def prune(directory: Path) -> None:
    files = sorted(directory.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
    retention = RETENTION_DAYS if RETENTION_DAYS is not None else _setting("logs.retention_days")
    max_logs = MAX_LOGS if MAX_LOGS is not None else _setting("logs.max_entries")
    cutoff = time.time() - retention * 86400
    for index, path in enumerate(files):
        with contextlib.suppress(OSError):
            if index >= max_logs or path.stat().st_mtime < cutoff:
                path.unlink()


def latest() -> str:
    """Id of the most recently saved log."""
    files = sorted(logs_dir().glob("*.log"), key=lambda p: p.stat().st_mtime)
    if not files:
        raise FileNotFoundError("No saved logs yet")
    return files[-1].stem


def _filter_lines(numbered: list[tuple[int, str]], lines: str) -> list[tuple[int, str]]:
    start, _, end = lines.partition("-")
    low, high = int(start), int(end or start)
    return [(n, line) for n, line in numbered if low <= n <= high]


def _filter_grep(numbered: list[tuple[int, str]], grep: str) -> list[tuple[int, str]]:
    pattern = re.compile(grep, re.IGNORECASE)
    return [(n, line) for n, line in numbered if pattern.search(line)]


def read(log_id: str, *, grep: str | None = None, lines: str | None = None) -> str:
    if log_id == "--last":
        log_id = latest()
    if not re.fullmatch(r"[0-9a-f]{6,64}", log_id):
        raise ValueError(f"Invalid log id: {log_id}")
    content = (logs_dir() / f"{log_id}.log").read_text(encoding="utf-8").splitlines()
    numbered = list(enumerate(content, 1))
    if lines:
        numbered = _filter_lines(numbered, lines)
    if grep:
        numbered = _filter_grep(numbered, grep)
    return "\n".join(f"{n}: {line}" for n, line in numbered)
