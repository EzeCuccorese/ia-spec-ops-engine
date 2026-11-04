"""One store-wide cache of PR status: ``<store root>/pr-status.json``.

Live status never goes into a task's ``state.json`` (it would churn ``updated_at`` and let a
stale copy resurrect). Every holder of the same PR shares one entry. A sync takes a ``gen``
from a persisted counter under the cache lock when it starts, and an entry is replaced only by
a strictly newer ``gen``, so a clock regression or a slow older sync cannot overwrite fresher
data. The file holds facts about public PRs and the owner -> login map, never a token.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from ..store import atomic_write_text
from .snapshot import Snapshot, SyncError

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None  # type: ignore[assignment]

CACHE_FILE = "pr-status.json"
ACCOUNTS_FILE = "gh-accounts.json"
Entry = dict[str, Any]


def _gen(entry: Entry) -> int:
    value = entry.get("gen", 0)
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def make_entry(result: Snapshot | SyncError, synced_at: str) -> Entry:
    """The cache entry for a sync outcome (``gen`` is added by ``PrCache.store``/``store_many``)."""
    if isinstance(result, SyncError):
        return {"snapshot": None, "error": result.code, "synced_at": synced_at}
    return {"snapshot": result.to_dict(), "error": "", "synced_at": synced_at}


class PrCache:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.path = root / CACHE_FILE
        self.accounts_path = root / ACCOUNTS_FILE

    @contextmanager
    def _lock(self) -> Iterator[None]:
        self.root.mkdir(parents=True, exist_ok=True)
        with open(self.root / ".pr-status.lock", "a", encoding="utf-8") as handle:
            if fcntl:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                if fcntl:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _load(self) -> dict[str, Any]:
        """The file's content; a missing or corrupt file is an empty cache."""
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"gen": 0, "entries": {}}
        entries = data.get("entries") if isinstance(data, dict) else None
        gen = data.get("gen") if isinstance(data, dict) else None
        if not isinstance(entries, dict) or not isinstance(gen, int) or isinstance(gen, bool):
            return {"gen": 0, "entries": {}}
        return {"gen": gen, "entries": {k: v for k, v in entries.items() if isinstance(v, dict)}}

    def _save(self, data: dict[str, Any]) -> None:
        atomic_write_text(self.path, json.dumps(data, indent=2, sort_keys=True))

    def entries(self) -> dict[str, Entry]:
        return self._load()["entries"]

    def get(self, key: str) -> Entry | None:
        return self.entries().get(key.lower())

    def begin_sync(self) -> int:
        """Allocate the next ``gen`` (always above every stored one) for a sync that starts now."""
        with self._lock():
            data = self._load()
            highest = max([data["gen"], *(_gen(e) for e in data["entries"].values())])
            data["gen"] = highest + 1
            self._save(data)
            return int(data["gen"])

    def store_many(
        self, entries: Mapping[str, Entry] | Iterable[tuple[str, Entry]], gen: int
    ) -> int:
        """Replace entries whose ``gen`` is strictly newer in one write; returns stored count."""
        pairs = entries.items() if isinstance(entries, Mapping) else entries
        updated = 0
        with self._lock():
            data = self._load()
            for key, entry in pairs:
                current = data["entries"].get(key.lower())
                if current is None or gen > _gen(current):
                    data["entries"][key.lower()] = {**entry, "gen": gen}
                    updated += 1
            if updated:
                self._save(data)
        return updated

    def store(self, key: str, entry: Entry, gen: int) -> bool:
        """Replace ``key``'s entry if ``gen`` is strictly newer; False when it was older."""
        return bool(self.store_many([(key, entry)], gen))

    # -- owner -> login (non-secret) ------------------------------------------------------
    def accounts(self) -> dict[str, str]:
        try:
            data = json.loads(self.accounts_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        if not isinstance(data, dict):
            return {}
        return {str(k).lower(): v for k, v in data.items() if isinstance(v, str) and v}

    def remember_account(self, owner: str, login: str) -> None:
        with self._lock():
            known = self.accounts()
            known[owner.lower()] = login
            atomic_write_text(self.accounts_path, json.dumps(known, indent=2, sort_keys=True))
