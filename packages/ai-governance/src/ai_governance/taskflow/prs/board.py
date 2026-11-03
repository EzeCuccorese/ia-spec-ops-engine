"""A task's pull request board: its registrations and its subtasks' joined with the cache.

``board`` and ``summary_for`` read the cache only (no network, no subprocess); ``sync`` is the
one function that talks to GitHub, and it only ever writes the cache, never a task.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from ..models import now_iso
from ..store import TaskStore
from .cache import PrCache, make_entry
from .github import PrReader
from .registry import Registration, registrations
from .snapshot import SyncError
from .status import Evaluation, evaluate, summarize
from .text import safe_text

POOL = 8


@dataclass(frozen=True)
class Item:
    holder: str
    reg: Registration
    evaluation: Evaluation


@dataclass(frozen=True)
class Board:
    items: list[Item]
    bare_skipped: int


def holders(store: TaskStore, task_id: str) -> tuple[list[tuple[str, Registration]], int]:
    """(holder task id, registration) over the task and every descendant, one per PR key.

    Cycle-safe (visited set); missing subtask ids are skipped. Also returns how many bare
    ``#N`` of legacy sources had to be skipped for lack of a repository."""
    found: list[tuple[str, Registration]] = []
    seen: set[str] = set()
    visited: set[str] = set()
    skipped = 0
    queue = [task_id]
    while queue:
        current = queue.pop(0)
        if current in visited or not store.exists(current):
            continue
        visited.add(current)
        task = store.get(current)
        regs, bare = registrations(task)
        skipped += bare
        for reg in regs:
            if reg.ref.key not in seen:
                seen.add(reg.ref.key)
                found.append((current, reg))
        queue.extend(task.subtasks)
    return found, skipped


def board(store: TaskStore, task_id: str, now: datetime | None = None) -> Board:
    """The task's PRs with their cached evaluation (reads the cache file once)."""
    entries = PrCache(store.root).entries()
    pairs, skipped = holders(store, task_id)
    items = [Item(h, r, evaluate(entries.get(r.ref.key), now)) for h, r in pairs]
    return Board(items, skipped)


def sync(store: TaskStore, task_id: str, reader: PrReader | None = None) -> int:
    """Refresh the cache for every PR of the board; returns how many ended in a sync error.

    The reader never raises; an entry is replaced only by a newer ``gen`` (see ``PrCache``)."""
    refs = [reg.ref for _, reg in holders(store, task_id)[0]]
    cache = PrCache(store.root)
    reader = reader or PrReader(cache=cache)
    gen = cache.begin_sync()
    with ThreadPoolExecutor(max_workers=POOL) as pool:
        results = list(pool.map(reader.fetch, refs))
    stamp = now_iso()
    for ref, result in zip(refs, results, strict=True):
        cache.store(ref.key, make_entry(result, stamp), gen)
    return sum(isinstance(result, SyncError) for result in results)


def summary_for(store: TaskStore, task_id: str) -> str:
    """The one-line summary from the cache only; '' without PRs or on any read failure."""
    try:
        return summarize([item.evaluation for item in board(store, task_id).items])
    except (OSError, ValueError, KeyError):
        return ""


def as_json(item: Item) -> dict[str, Any]:
    """One machine-readable row; titles and groups are cleaned, never trusted."""
    ev, snap = item.evaluation, item.evaluation.snapshot
    return {
        "task": item.holder,
        "repo": item.reg.ref.repo,
        "number": item.reg.ref.number,
        "url": item.reg.ref.url,
        "group": safe_text(item.reg.group, 40),
        "state": ev.state,
        "blockers": list(ev.blockers),
        "ready": ev.ready,
        "stale": ev.stale,
        "age_s": ev.age_s,
        "synced_at": ev.synced_at,
        "error": safe_text(ev.error, 80),
        "title": safe_text(snap.title) if snap else "",
        "snapshot": snap.to_dict() if snap else None,
    }
