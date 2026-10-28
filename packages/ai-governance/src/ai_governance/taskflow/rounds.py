"""One round = one agent call with its prompt, command, code stamp and full answer on disk.

Reader roles that change the tree invalidate their round; the changes are kept and
reported, never discarded. A writer round holds a lease on the repository so two agents
never write the same checkout at once.
"""

from __future__ import annotations

import hashlib
import json
import os
import shlex
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from .adapters import (
    READ_ONLY_LIMIT,
    VERDICT_INSTRUCTION,
    AgentRun,
    RunResult,
    parse_verdict,
    run_agent,
)
from .models import READER_ROLES, JsonDict, now_iso
from .stamp import GitError, changed_paths, git, tree_fingerprint
from .store import TaskStore, atomic_write_text, fcntl


class LeaseError(RuntimeError):
    pass


@dataclass(frozen=True)
class RoundRequest:
    task_id: str
    phase: str
    role: str
    prompt: str
    repo: Path
    agent: JsonDict
    focus: str = ""
    timeout: int = 1800
    watch: tuple[Path, ...] = ()  # other trees a reader must not change


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

    The agent a round launches inherits the holder in ``AI_GOVERNANCE_LEASE_HOLDER``, so
    its own edits are not refused."""
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


def _fingerprints(paths: tuple[Path, ...]) -> dict[Path, str]:
    return {path: tree_fingerprint(path) for path in paths}


def run_round(store: TaskStore, request: RoundRequest, stamp_key: str) -> JsonDict:
    agent_name = str(request.agent.get("agent", ""))
    reader = request.role in READER_ROLES
    prompt = (READ_ONLY_LIMIT if reader else "") + request.prompt
    if request.role in ("validator", "judge"):
        prompt += VERDICT_INSTRUCTION
    number, path = store.reserve_round(request.task_id, request.phase, request.role, agent_name)
    workdir = store.task_dir(request.task_id) / "runs" / f"{number:03d}"
    workdir.mkdir(parents=True, exist_ok=True)
    watched = (request.repo, *request.watch)
    before = _fingerprints(watched)
    holder = f"{request.task_id}#{number:03d}"
    with writer_lease(store, request.repo, holder) if not reader else _no_lease():
        # The judge runs tests in its disposable copy, so it gets write access there.
        writes = not reader or request.role == "judge"
        run = AgentRun(request.repo, writes, workdir / "answer.txt")
        result = run_agent(request.agent, prompt, run, request.timeout)
    atomic_write_text(workdir / "raw.log", result.raw_log)
    changed = (
        [p for p, value in _fingerprints(watched).items() if value != before[p]] if reader else []
    )
    record = _record(request, (number, path, stamp_key), result, changed)
    atomic_write_text(path, _render(record, prompt, result.command, result.answer))
    store.mutate(request.task_id, lambda task: task.rounds.append(record))
    return record


def _record(
    request: RoundRequest, slot: tuple[int, Path, str], result: RunResult, changed: list[Path]
) -> JsonDict:
    number, path, stamp_key = slot
    state = "invalid" if changed or result.timed_out or result.exit_code != 0 else "valid"
    verdict = parse_verdict(result.answer) if request.role in ("validator", "judge") else "info"
    return {
        "n": number,
        "at": now_iso(),
        "phase": request.phase,
        "role": request.role,
        "focus": request.focus,
        "agent": str(request.agent.get("agent", "")),
        "model": str(request.agent.get("model", "")),
        "stamp": stamp_key,
        "verdict": verdict if state == "valid" else "block",
        "state": state,
        "source": "engine",
        "file": str(path),
        "reason": _invalid_reason(result, changed),
    }


@contextmanager
def _no_lease() -> Iterator[None]:
    yield


def _invalid_reason(result: RunResult, changed: list[Path]) -> str:
    if result.timed_out:
        return "timeout"
    if result.exit_code != 0:
        return f"exit code {result.exit_code}"
    if changed:
        paths = [f"{repo}: {', '.join(changed_paths(repo)[:10])}" for repo in changed]
        return "reader changed the tree (kept, not discarded) — " + "; ".join(paths)
    return ""


def _render(record: JsonDict, prompt: str, command: list[str], answer: str) -> str:
    shown = shlex.join([part if len(part) < 200 else "<prompt>" for part in command])
    focus = f" · {record['focus']}" if record["focus"] else ""
    return (
        f"# Round {record['n']:03d} · {record['phase']} · {record['role']}{focus} · "
        f"{record['agent']} {record['model']}\n\n"
        f"- Date: {record['at']}\n- Code stamp: {record['stamp']}\n- Command: `{shown}`\n"
        f"- Verdict: {record['verdict']} ({record['state']}{': ' + record['reason'] if record['reason'] else ''})\n\n"
        f"## Request\n\n{prompt}\n\n## Answer\n\n{answer}\n"
    )


def record_manual(store: TaskStore, task_id: str, round_info: JsonDict, body: str) -> JsonDict:
    """A round run outside the engine: kept as context, never counted as a verdict."""
    number, path = store.reserve_round(
        task_id, round_info["phase"], round_info["role"], round_info["agent"]
    )
    record = {
        **round_info,
        "n": number,
        "at": now_iso(),
        "source": "manual",
        "state": "context",
        "file": str(path),
    }
    atomic_write_text(
        path, _render({**record, "focus": round_info.get("focus", ""), "reason": ""}, "", [], body)
    )
    store.mutate(task_id, lambda task: task.rounds.append(record))
    return record
