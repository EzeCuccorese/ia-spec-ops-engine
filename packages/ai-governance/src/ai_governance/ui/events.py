"""Server-Sent Events (SSE) store change stream for Taskflow and Second Brain."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import stat as stat_mod
from collections.abc import AsyncIterator, Mapping
from pathlib import Path

_STORE_SUFFIXES = (".json", ".md")


def _stat_entry(root: Path, full: Path) -> tuple[str, int, int] | None:
    if full.suffix not in _STORE_SUFFIXES:
        return None
    try:
        st = full.stat()
        if not stat_mod.S_ISREG(st.st_mode):
            return None
        return (full.relative_to(root).as_posix(), st.st_mtime_ns, st.st_size)
    except OSError:
        return None


def _collect_entries(root: Path) -> list[tuple[str, int, int]]:
    entries: list[tuple[str, int, int]] = []
    for dirpath, _dirnames, filenames in os.walk(root, onerror=lambda _err: None):
        base = Path(dirpath)
        for name in filenames:
            entry = _stat_entry(root, base / name)
            if entry is not None:
                entries.append(entry)
    entries.sort()
    return entries


def compute_dir_signature(root: Path) -> str:
    """Return a sha256 signature of ``.json`` and ``.md`` files under ``root``, or ``''``."""
    if not root.is_dir():
        return ""
    digest = hashlib.sha256()
    for rel, mtime_ns, size in _collect_entries(root):
        digest.update(f"{rel}:{mtime_ns}:{size}\n".encode())
    return digest.hexdigest()


def _format_sse(event: str, payload: Mapping[str, object]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload)}\n\n"


async def stream_store_events(
    task_root: Path,
    brain_root: Path,
    *,
    poll_interval: float = 1.5,
    max_events: int | None = None,
) -> AsyncIterator[str]:
    """Yield SSE ``snapshot``, ``changed``, and keepalive ping frames for both stores."""
    sigs = {
        "taskflow": compute_dir_signature(task_root),
        "brain": compute_dir_signature(brain_root),
    }
    yield _format_sse("snapshot", sigs)
    yielded, idle_ticks = 1, 0
    while max_events is None or yielded < max_events:
        await asyncio.sleep(poll_interval)
        next_sigs = {
            "taskflow": compute_dir_signature(task_root),
            "brain": compute_dir_signature(brain_root),
        }
        changed = [k for k in ("taskflow", "brain") if next_sigs[k] != sigs[k]]
        if changed:
            sigs = next_sigs
            idle_ticks = 0
            yielded += 1
            yield _format_sse("changed", {"changed": changed})
            continue
        idle_ticks += 1
        if idle_ticks >= 10:
            idle_ticks = 0
            yielded += 1
            yield ": ping\n\n"
