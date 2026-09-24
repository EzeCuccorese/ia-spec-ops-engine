"""Full-output log store: private (0600), bounded (age + count), addressable by id."""

from __future__ import annotations

import contextlib
import hashlib
import os
import re
import time
from pathlib import Path

RETENTION_DAYS = 7
MAX_LOGS = 200


def logs_dir() -> Path:
    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(os.environ.get("WORKSPACE_LOG_DIR") or Path(base) / "workspace" / "logs")


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
    cutoff = time.time() - RETENTION_DAYS * 86400
    for index, path in enumerate(files):
        with contextlib.suppress(OSError):
            if index >= MAX_LOGS or path.stat().st_mtime < cutoff:
                path.unlink()


def latest() -> str:
    """Id of the most recently saved log."""
    files = sorted(logs_dir().glob("*.log"), key=lambda p: p.stat().st_mtime)
    if not files:
        raise FileNotFoundError("No saved logs yet")
    return files[-1].stem


def read(log_id: str, *, grep: str | None = None, lines: str | None = None) -> str:
    if log_id == "--last":
        log_id = latest()
    if not re.fullmatch(r"[0-9a-f]{6,64}", log_id):
        raise ValueError(f"Invalid log id: {log_id}")
    content = (logs_dir() / f"{log_id}.log").read_text(encoding="utf-8").splitlines()
    numbered = list(enumerate(content, 1))
    if lines:
        start, _, end = lines.partition("-")
        low, high = int(start), int(end or start)
        numbered = [(n, line) for n, line in numbered if low <= n <= high]
    if grep:
        pattern = re.compile(grep, re.IGNORECASE)
        numbered = [(n, line) for n, line in numbered if pattern.search(line)]
    return "\n".join(f"{n}: {line}" for n, line in numbered)
