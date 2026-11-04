"""Writer leases and manually recorded rounds.

The engine never runs an agent, so a round is either dispatched to an Orca worker (see
``dispatch`` and ``collect``) or recorded by hand as context (``record_manual``). The
writer lease stays: it keeps two coordinating sessions from writing one branch at once.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from .models import JsonDict, now_iso
from .stamp import GitError, git
from .store import RoundSlot, TaskStore, atomic_write_text, fcntl


class LeaseError(RuntimeError):
    pass


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


LEASE_ENV = "AI_GOVERNANCE_LEASE_HOLDER"


def lease_identity(repo: Path) -> str:
    """Repository + branch, so every checkout of the same branch shares one lease."""
    try:
        common = Path(git(repo, "rev-parse", "--git-common-dir").strip())
        branch = git(repo, "branch", "--show-current").strip()
    except GitError:
        return str(repo.resolve())
    common = common if common.is_absolute() else (repo / common).resolve()
    return f"{common}@{branch}" if branch else str(repo.resolve())


def _lease_path(store: TaskStore, repo: Path) -> Path:
    leases = store.root / "leases"
    leases.mkdir(parents=True, exist_ok=True)
    return leases / (hashlib.sha256(lease_identity(repo).encode()).hexdigest()[:16] + ".json")


@contextmanager
def _leases_locked(store: TaskStore) -> Iterator[None]:
    """Serializes acquire and reclaim, so a dead lease is replaced by exactly one writer."""
    lock = store.root / "leases" / ".lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    with open(lock, "a", encoding="utf-8") as handle:
        if fcntl:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _read_lease(path: Path) -> JsonDict:
    try:
        return dict(json.loads(path.read_text(encoding="utf-8") or "{}"))
    except (OSError, ValueError):
        return {}


def active_lease(store: TaskStore, repo: Path) -> JsonDict | None:
    """The live writer lease on ``repo``'s branch held by someone else, if any.

    A session that holds the lease exports it in ``AI_GOVERNANCE_LEASE_HOLDER``, so its own
    edits are not refused."""
    current = _read_lease(_lease_path(store, repo))
    if not current or not _alive(int(current.get("pid", 0))):
        return None
    return None if current.get("holder") == os.environ.get(LEASE_ENV) else current


@contextmanager
def writer_lease(store: TaskStore, repo: Path, holder: str) -> Iterator[None]:
    """Exclusive writer per repository branch; a lease is reclaimed only when its process is dead."""
    path = _lease_path(store, repo)
    with _leases_locked(store):
        current = _read_lease(path)
        if current and _alive(int(current.get("pid", 0))):
            raise LeaseError(
                f"{repo} is being written by {current.get('holder')} (pid {current.get('pid')})"
            )
        record = {
            "holder": holder,
            "pid": os.getpid(),
            "repo": lease_identity(repo),
            "at": now_iso(),
        }
        atomic_write_text(path, json.dumps(record))
    previous = os.environ.get(LEASE_ENV)
    os.environ[LEASE_ENV] = holder
    try:
        yield
    finally:
        with _leases_locked(store):
            if _read_lease(path).get("holder") == holder:
                path.unlink(missing_ok=True)
        if previous is None:
            os.environ.pop(LEASE_ENV, None)
        else:
            os.environ[LEASE_ENV] = previous


def _render(record: JsonDict, body: str) -> str:
    focus = f" · {record['focus']}" if record["focus"] else ""
    return (
        f"# Round {record['n']:03d} · {record['phase']} · {record['role']}{focus} · "
        f"{record['agent']} {record['model']}\n\n"
        f"- Date: {record['at']}\n- Code stamp: {record['stamp']}\n"
        f"- Verdict: {record['verdict']} ({record['state']})\n\n"
        f"## Answer\n\n{body}\n"
    )


def record_manual(store: TaskStore, task_id: str, round_info: JsonDict, body: str) -> JsonDict:
    """A round run outside the engine: kept as context, never counted as a verdict."""
    number, path = store.reserve_round(
        task_id, RoundSlot(round_info["phase"], round_info["role"], round_info["agent"])
    )
    record = {
        **round_info,
        "n": number,
        "at": now_iso(),
        "source": "manual",
        "state": "context",
        "file": str(path),
    }
    atomic_write_text(path, _render({**record, "focus": round_info.get("focus", "")}, body))
    store.mutate(task_id, lambda task: task.rounds.append(record))
    return record
