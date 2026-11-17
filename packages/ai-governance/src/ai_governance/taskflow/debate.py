"""Design debate orchestration: multi-provider thesis and cross-examination rounds.

A debate is a set of ordinary ``debater`` rounds stored alongside a lightweight
``debate.json`` file in the task directory. ``debate.json`` stays outside
``control.baseline``, so opening, crossing or closing a debate never triggers
control-plane drift.
"""

from __future__ import annotations

import errno
import hashlib
import json
import os
import shutil
import stat
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from . import orca
from .agents import DEFAULT_MODELS, HUMAN, provider, read_regular_text
from .config import FlowConfig
from .control import DispatchError, digest_text, seal_path
from .dispatch import Dispatched, DispatchRequest, plan_dispatch, run_dir
from .models import JsonDict, Task
from .prompts import THESIS_INSTRUCTION
from .refresh import refresh
from .repos import partition
from .store import TaskStore, atomic_write_text

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None  # type: ignore[assignment]

DEBATE_FILE = "debate.json"
TOPIC_MAX_BYTES = 262_144
PREVIEW_LINES = 5


@dataclass(frozen=True)
class OpenDebateOptions:
    """Input options for opening a new design debate."""

    topic_file: Path
    agents: tuple[str, ...]
    models: dict[str, str] | None = None
    web: bool = False
    artifacts: tuple[str, ...] = ()


@dataclass(frozen=True)
class SeatSpec:
    """Resolved seat identity and model before dispatch."""

    focus: str
    agent: str
    model: str


@dataclass(frozen=True)
class DispatchedSeat:
    """One seat paired with its newly reserved Orca round."""

    seat: SeatSpec
    round: Dispatched


@dataclass(frozen=True)
class DebateOpenResult:
    """Outcome of ``open_debate``."""

    debate_id: int
    seats: tuple[DispatchedSeat, ...]


@dataclass(frozen=True)
class DebateCrossResult:
    """Outcome of ``cross_debate``."""

    debate_id: int
    seats: tuple[DispatchedSeat, ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class _OpenFlags:
    """Resolved dispatch flags and pinned artifact digests for opening a debate."""

    web: bool
    artifacts: tuple[str, ...]
    effort: str
    artifact_digests: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class _OpenDraft:
    """Validated inputs to persist in ``debate.json`` when opening a debate."""

    debate_id: int
    topic_file: Path
    topic_text: str
    flags: _OpenFlags


@dataclass(frozen=True)
class _CrossSave:
    """Cross-examination dispatch outcome to persist into ``debate.json``."""

    dispatched: Sequence[DispatchedSeat]
    dropped: list[JsonDict]


@dataclass(frozen=True)
class _StatusLookup:
    """Indexed task rounds and dropped focuses for seat status computation."""

    rounds_by_n: dict[int, JsonDict]
    dropped: set[str]


def _flock(fd: int, lock: bool) -> None:
    if fcntl:
        fcntl.flock(fd, fcntl.LOCK_EX if lock else fcntl.LOCK_UN)


@contextmanager
def _debate_lock(store: TaskStore, task_id: str) -> Iterator[Path]:
    """Serialize debate state transitions per task on ``.debate.lock`` (never ``.lock``)."""
    directory = store.task_dir(task_id)
    directory.mkdir(parents=True, exist_ok=True)
    with open(directory / ".debate.lock", "a", encoding="utf-8") as handle:
        _flock(handle.fileno(), True)
        try:
            yield directory
        finally:
            _flock(handle.fileno(), False)


def debate_path(store: TaskStore, task_id: str) -> Path:
    """Path to ``debate.json`` inside ``task_id``'s store directory."""
    return store.task_dir(task_id) / DEBATE_FILE


def load_debate(store: TaskStore, task_id: str) -> JsonDict | None:
    """Read ``debate.json`` if present, or None when no debate has been opened yet."""
    path = debate_path(store, task_id)
    if not os.path.lexists(path):
        return None
    try:
        data = json.loads(read_regular_text(path))
    except (OSError, ValueError) as exc:
        raise DispatchError(f"cannot read {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise DispatchError(f"corrupted debate state in {path}: expected a JSON object")
    return data


def require_debate(store: TaskStore, task_id: str) -> JsonDict:
    """Read ``debate.json`` or raise ``DispatchError`` when missing."""
    data = load_debate(store, task_id)
    if data is None:
        raise DispatchError(f"no debate found for task '{task_id}'")
    return data


def save_debate(store: TaskStore, task_id: str, state: JsonDict) -> Path:
    """Atomically write ``debate.json`` for ``task_id``."""
    path = debate_path(store, task_id)
    atomic_write_text(path, json.dumps(state, indent=2, ensure_ascii=False) + "\n")
    return path


def dropped_focuses(state: JsonDict) -> set[str]:
    """Seat focuses recorded in ``state['dropped']``."""
    found: set[str] = set()
    for item in state.get("dropped", []):
        if isinstance(item, dict) and item.get("focus"):
            found.add(str(item["focus"]))
    return found


def _read_topic(path: Path) -> str:
    try:
        text = read_regular_text(path)
    except (OSError, UnicodeDecodeError) as exc:
        raise DispatchError(f"cannot read topic file {path}: {exc}") from exc
    if len(text.encode("utf-8")) > TOPIC_MAX_BYTES:
        raise DispatchError(f"topic file {path} exceeds {TOPIC_MAX_BYTES} bytes")
    if not text.strip():
        raise DispatchError(f"topic file {path} is empty")
    return text


def _topic_preview(text: str) -> list[str]:
    return [line.rstrip() for line in text.splitlines() if line.strip()][:PREVIEW_LINES]


def _digest_regular_file(path: Path) -> str:
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOCTTY", 0))
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise OSError(errno.EINVAL, "not a regular file", str(path))
        with os.fdopen(fd, "rb", closefd=False) as handle:
            return hashlib.file_digest(handle, "sha256").hexdigest()
    finally:
        os.close(fd)


def _resolve_artifact_digests(artifacts: Sequence[str]) -> dict[str, str]:
    digests: dict[str, str] = {}
    for raw in artifacts:
        if not str(raw).strip():
            raise DispatchError("artifact path cannot be empty")
        try:
            target = Path(raw).expanduser().resolve(strict=True)
            sha = _digest_regular_file(target)
        except OSError as exc:
            raise DispatchError(f"artifact not found or unreadable: {raw} ({exc})") from exc
        digests[str(target)] = sha
    return digests


def _next_focus(agent: str, count: int, used: set[str]) -> str:
    if count == 1 and agent not in used:
        return agent
    suffix = max(count, 2)
    while f"{agent}-{suffix}" in used:
        suffix += 1
    return f"{agent}-{suffix}"


def _assign_focuses(agents: Sequence[str]) -> list[tuple[str, str]]:
    counts: dict[str, int] = {}
    used: set[str] = set()
    pairs: list[tuple[str, str]] = []
    for agent in agents:
        counts[agent] = counts.get(agent, 0) + 1
        focus = _next_focus(agent, counts[agent], used)
        used.add(focus)
        pairs.append((focus, agent))
    return pairs


def _validate_model_keys(
    models: dict[str, str] | None, pairs: list[tuple[str, str]]
) -> dict[str, str]:
    model_map = dict(models or {})
    valid = {agent for _, agent in pairs} | {focus for focus, _ in pairs}
    unknown = sorted(key for key in model_map if key not in valid)
    if unknown:
        raise DispatchError(f"unknown --model target(s): {', '.join(unknown)}")
    return model_map


def _seat_model(focus: str, agent: str, model_map: dict[str, str], config: FlowConfig) -> str:
    default_model = DEFAULT_MODELS.get(provider(agent), "")
    model = model_map.get(focus, model_map.get(agent, default_model))
    effective = model.strip() or default_model
    if err := config.model_error(effective):
        raise DispatchError(f"seat '{focus}': {err}")
    effort = config.effort("debater")
    if effort and not effective:
        raise DispatchError(
            f"seat '{focus}': effort requires a model (pass --model or set taskflow.debater_model)"
        )
    if config.denied_models and not effective:
        raise DispatchError(
            f"seat '{focus}': pass --model or set taskflow.debater_model when "
            "taskflow.denied_models is active"
        )
    return effective if (effort or config.denied_models) else model


def _build_seat(pair: tuple[str, str], model_map: dict[str, str], config: FlowConfig) -> SeatSpec:
    focus, agent = pair
    if provider(agent) == HUMAN:
        raise DispatchError(f"seat '{focus}': human cannot run as a debate worker")
    if err := config.agent_error(agent):
        raise DispatchError(f"seat '{focus}': {err}")
    return SeatSpec(focus=focus, agent=agent, model=_seat_model(focus, agent, model_map, config))


def assign_seats(
    agents: Sequence[str], models: dict[str, str] | None, config: FlowConfig
) -> tuple[SeatSpec, ...]:
    """Validate seat agents/providers/models and assign deterministic focuses."""
    cleaned = [str(agent).strip() for agent in agents]
    if any(not agent for agent in cleaned):
        raise DispatchError("debate seat agent id cannot be empty")
    if len(cleaned) < 2:
        raise DispatchError("a debate requires at least 2 seats")
    if len({provider(agent) for agent in cleaned}) < 2:
        raise DispatchError("a debate requires at least 2 distinct providers")
    pairs = _assign_focuses(cleaned)
    model_map = _validate_model_keys(models, pairs)
    return tuple(_build_seat(pair, model_map, config) for pair in pairs)


def _read_dispatch_json(path: Path) -> JsonDict | None:
    try:
        found = json.loads(path.read_text(encoding="utf-8"))
        int(found["n"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return found if isinstance(found, dict) else None


def _check_pending_focuses(store: TaskStore, task: Task, focuses: set[str]) -> None:
    settled = {int(r.get("n", 0)) for r in task.rounds}
    runs_dir = store.task_dir(task.id) / "runs"
    for path in sorted(runs_dir.glob("*/dispatch.json")):
        found = _read_dispatch_json(path)
        if found is None or int(found["n"]) in settled:
            continue
        focus = str(found.get("focus", ""))
        if found.get("role") == "debater" and focus in focuses:
            number = int(found["n"])
            raise DispatchError(
                f"debater round {number:03d} (focus '{focus}') is still pending: "
                "collect or abort it before dispatching that focus again"
            )


def _check_task_ready(task: Task) -> None:
    if task.blocked:
        raise DispatchError(
            f"'{task.id}' is blocked by {task.blocked.get('owner')}: {task.blocked.get('needs')}"
        )
    if missing := partition(task.repos).missing:
        raise DispatchError(f"bound repo not found: {missing[0]['path']}")


def _rollback_dispatched(store: TaskStore, task_id: str, dispatched: list[Dispatched]) -> None:
    rounds_dir = store.rounds_dir(task_id)
    for item in dispatched:
        shutil.rmtree(run_dir(store, task_id, item.n), ignore_errors=True)
        for round_file in rounds_dir.glob(f"{item.n:03d}-*.md"):
            round_file.unlink(missing_ok=True)
        seal_path(store, task_id, item.n).unlink(missing_ok=True)


def _dispatch_seats(
    store: TaskStore,
    task: Task,
    config: FlowConfig,
    requests: Sequence[tuple[SeatSpec, DispatchRequest]],
) -> tuple[DispatchedSeat, ...]:
    reserved: list[Dispatched] = []
    seats: list[DispatchedSeat] = []
    try:
        for seat, request in requests:
            dispatched = plan_dispatch(store, task, config, request)
            reserved.append(dispatched)
            seats.append(DispatchedSeat(seat=seat, round=dispatched))
    except BaseException:
        _rollback_dispatched(store, task.id, reserved)
        raise
    return tuple(seats)


def _open_requests(
    task: Task,
    seats: Sequence[SeatSpec],
    prompt: str,
    flags: _OpenFlags,
) -> list[tuple[SeatSpec, DispatchRequest]]:
    return [
        (
            seat,
            DispatchRequest(
                role="debater",
                phase=task.phase,
                focus=seat.focus,
                prompt=prompt,
                agent={"agent": seat.agent, "model": seat.model},
                web=flags.web,
                artifacts=flags.artifacts,
                effort=flags.effort,
            ),
        )
        for seat in seats
    ]


def _open_state(draft: _OpenDraft, dispatched: Sequence[DispatchedSeat]) -> JsonDict:
    return {
        "debate_id": draft.debate_id,
        "status": "open",
        "topic_file": str(draft.topic_file.resolve()),
        "topic_sha": digest_text(draft.topic_text),
        "topic_preview": _topic_preview(draft.topic_text),
        "flags": {"web": bool(draft.flags.web), "artifacts": list(draft.flags.artifacts)},
        "artifact_digests": dict(draft.flags.artifact_digests),
        "seats": [
            {
                "focus": item.seat.focus,
                "agent": item.seat.agent,
                "model": item.seat.model,
                "thesis_round": item.round.n,
                "cross_round": None,
            }
            for item in dispatched
        ],
        "dropped": [],
        "recorded_open_keys": [],
    }


def _check_openable(existing: JsonDict | None, task_id: str) -> None:
    if existing is None:
        return
    status = existing.get("status")
    if status == "open":
        raise DispatchError(f"task '{task_id}' already has an open debate")
    if status != "closed":
        raise DispatchError(f"debate for '{task_id}' has unsupported status '{status}'")


def _open_debate_locked(
    store: TaskStore, task_id: str, config: FlowConfig, opts: OpenDebateOptions
) -> DebateOpenResult:
    task = store.get(task_id)
    _check_task_ready(task)
    existing = load_debate(store, task_id)
    _check_openable(existing, task_id)
    topic_text = _read_topic(opts.topic_file)
    seats = assign_seats(opts.agents, opts.models, config)
    digests = _resolve_artifact_digests(opts.artifacts)
    flags = _OpenFlags(opts.web, tuple(digests), config.effort("debater"), digests)
    _check_pending_focuses(store, task, {seat.focus for seat in seats})
    orca.require_orca()
    task, _ = refresh(store, task, config)
    requests = _open_requests(task, seats, topic_text.strip() + THESIS_INSTRUCTION, flags)
    dispatched = _dispatch_seats(store, task, config, requests)
    debate_id = int(existing.get("debate_id", 0)) + 1 if existing else 1
    draft = _OpenDraft(debate_id, opts.topic_file, topic_text, flags)
    try:
        save_debate(store, task_id, _open_state(draft, dispatched))
    except BaseException:
        _rollback_dispatched(store, task_id, [item.round for item in dispatched])
        raise
    return DebateOpenResult(debate_id=debate_id, seats=dispatched)


def open_debate(
    store: TaskStore, task_id: str, config: FlowConfig, opts: OpenDebateOptions
) -> DebateOpenResult:
    """Validate and dispatch one thesis round per seat, writing ``debate.json``."""
    with _debate_lock(store, task_id):
        return _open_debate_locked(store, task_id, config, opts)


def _partition_thesis(
    seats: Sequence[JsonDict], rounds_by_n: dict[int, JsonDict]
) -> tuple[list[JsonDict], list[JsonDict], list[str]]:
    pending = [
        int(seat["thesis_round"]) for seat in seats if int(seat["thesis_round"]) not in rounds_by_n
    ]
    if pending:
        joined = ", ".join(f"{n:03d}" for n in pending)
        raise DispatchError(f"thesis round(s) still pending: {joined}")
    valid: list[JsonDict] = []
    dropped: list[JsonDict] = []
    warnings: list[str] = []
    for seat in seats:
        number = int(seat["thesis_round"])
        record = rounds_by_n[number]
        if record.get("state") == "valid":
            valid.append(seat)
            continue
        reason = str(record.get("reason") or record.get("state") or "invalid")
        msg = f"dropped seat '{seat['focus']}' (round {number:03d}: {reason})"
        warnings.append(msg)
        dropped.append(
            {
                "focus": str(seat["focus"]),
                "agent": str(seat["agent"]),
                "model": str(seat["model"]),
                "thesis_round": number,
                "reason": reason,
                "message": msg,
            }
        )
    return valid, dropped, warnings


def _validate_cross_seats(seats: Sequence[JsonDict], config: FlowConfig) -> None:
    for seat in seats:
        focus = str(seat["focus"])
        agent = str(seat["agent"])
        model = str(seat.get("model", ""))
        if err := config.agent_error(agent):
            raise DispatchError(f"seat '{focus}': {err}")
        if err := config.model_error(model or DEFAULT_MODELS.get(provider(agent), "")):
            raise DispatchError(f"seat '{focus}': {err}")


def _cross_topic(state: JsonDict) -> str:
    topic_text = _read_topic(Path(str(state["topic_file"])))
    expected_sha = str(state.get("topic_sha", ""))
    if expected_sha and digest_text(topic_text) != expected_sha:
        raise DispatchError("topic file changed since the debate was opened")
    return topic_text


def _cross_artifacts(state: JsonDict, flags: JsonDict) -> tuple[str, ...]:
    raw_artifacts = flags.get("artifacts", ())
    if not isinstance(raw_artifacts, list | tuple):
        raise DispatchError("corrupted debate state: flags.artifacts must be a list")
    raw_digests = state.get("artifact_digests")
    if raw_digests is not None and not isinstance(raw_digests, dict):
        raise DispatchError("corrupted debate state: artifact_digests must be an object")
    expected = dict(raw_digests or {})
    current = _resolve_artifact_digests(tuple(str(item) for item in raw_artifacts))
    for path, sha in current.items():
        if expected.get(path) != sha:
            raise DispatchError(f"artifact changed since the debate was opened: {path}")
    return tuple(current)


def _cross_flags(state: JsonDict, effort: str) -> tuple[str, _OpenFlags]:
    topic_text = _cross_topic(state)
    raw_flags = state.get("flags", {})
    if not isinstance(raw_flags, dict):
        raise DispatchError("corrupted debate state: flags must be an object")
    flags = dict(raw_flags)
    artifacts = _cross_artifacts(state, flags)
    return topic_text.strip(), _OpenFlags(bool(flags.get("web", False)), artifacts, effort)


def _cross_requests(
    task: Task,
    valid_seats: Sequence[JsonDict],
    prompt: str,
    flags: _OpenFlags,
) -> list[tuple[SeatSpec, DispatchRequest]]:
    requests: list[tuple[SeatSpec, DispatchRequest]] = []
    for seat in valid_seats:
        focus = str(seat["focus"])
        spec = SeatSpec(focus=focus, agent=str(seat["agent"]), model=str(seat.get("model", "")))
        rebuts = tuple(
            int(other["thesis_round"]) for other in valid_seats if other["focus"] != focus
        )
        req = DispatchRequest(
            role="debater",
            phase=task.phase,
            focus=focus,
            prompt=prompt,
            agent={"agent": spec.agent, "model": spec.model},
            rebuts=rebuts,
            web=flags.web,
            artifacts=flags.artifacts,
            effort=flags.effort,
        )
        requests.append((spec, req))
    return requests


def _save_cross_state(
    store: TaskStore,
    task_id: str,
    state: JsonDict,
    outcome: _CrossSave,
) -> None:
    cross_by_focus = {item.seat.focus: item.round.n for item in outcome.dispatched}
    updated = json.loads(json.dumps(state))
    for seat in updated["seats"]:
        if seat["focus"] in cross_by_focus:
            seat["cross_round"] = cross_by_focus[seat["focus"]]
    updated["dropped"] = [*updated.get("dropped", []), *outcome.dropped]
    save_debate(store, task_id, updated)


def _valid_cross_seats(
    state: JsonDict, task: Task, config: FlowConfig
) -> tuple[list[JsonDict], list[JsonDict], list[str]]:
    seats = list(state.get("seats", []))
    if any(seat.get("cross_round") is not None for seat in seats):
        raise DispatchError("cross-examination was already dispatched for this debate")
    rounds_by_n = {int(r.get("n", 0)): r for r in task.rounds}
    valid_seats, dropped, warnings = _partition_thesis(seats, rounds_by_n)
    if len(valid_seats) < 2:
        raise DispatchError("fewer than 2 valid thesis seats remain for cross-examination")
    if len({provider(str(s["agent"])) for s in valid_seats}) < 2:
        raise DispatchError(
            "fewer than 2 distinct providers remain among valid thesis seats for cross-examination"
        )
    _validate_cross_seats(valid_seats, config)
    return valid_seats, dropped, warnings


def _cross_debate_locked(store: TaskStore, task_id: str, config: FlowConfig) -> DebateCrossResult:
    state = require_debate(store, task_id)
    if state.get("status") != "open":
        raise DispatchError(f"debate for '{task_id}' is {state.get('status')}, not open")
    task = store.get(task_id)
    _check_task_ready(task)
    valid_seats, dropped, warnings = _valid_cross_seats(state, task, config)
    _check_pending_focuses(store, task, {str(s["focus"]) for s in valid_seats})
    orca.require_orca()
    prompt, flags = _cross_flags(state, config.effort("debater"))
    task, _ = refresh(store, task, config)
    requests = _cross_requests(task, valid_seats, prompt, flags)
    dispatched = _dispatch_seats(store, task, config, requests)
    try:
        _save_cross_state(store, task_id, state, _CrossSave(dispatched, dropped))
    except BaseException:
        _rollback_dispatched(store, task_id, [item.round for item in dispatched])
        raise
    return DebateCrossResult(
        debate_id=int(state["debate_id"]), seats=dispatched, warnings=tuple(warnings)
    )


def cross_debate(store: TaskStore, task_id: str, config: FlowConfig) -> DebateCrossResult:
    """Validate thesis rounds and dispatch all-against-all cross-examination rounds."""
    with _debate_lock(store, task_id):
        return _cross_debate_locked(store, task_id, config)


def _seat_status_row(seat: JsonDict, lookup: _StatusLookup) -> dict[str, object]:
    focus = str(seat["focus"])
    thesis_round = int(seat["thesis_round"])
    thesis_rec = lookup.rounds_by_n.get(thesis_round)
    thesis_state = str(thesis_rec.get("state", "invalid")) if thesis_rec is not None else "pending"
    cross_raw = seat.get("cross_round")
    cross_round = int(cross_raw) if cross_raw is not None else None
    cross_state, overall = _cross_and_overall(focus, thesis_state, cross_round, lookup)
    return {
        "focus": focus,
        "agent": str(seat["agent"]),
        "model": str(seat.get("model", "")),
        "thesis_round": thesis_round,
        "thesis_state": thesis_state,
        "cross_round": cross_round,
        "cross_state": cross_state,
        "state": overall,
    }


def _cross_and_overall(
    focus: str,
    thesis_state: str,
    cross_round: int | None,
    lookup: _StatusLookup,
) -> tuple[str, str]:
    if focus in lookup.dropped:
        return "dropped", "dropped"
    if cross_round is None:
        if thesis_state == "invalid":
            return "invalid", "invalid"
        return "pending", "pending"
    cross_rec = lookup.rounds_by_n.get(cross_round)
    if cross_rec is None:
        return "pending", "pending"
    cross_state = str(cross_rec.get("state", "invalid"))
    return cross_state, ("collected" if cross_state == "valid" else "invalid")


def debate_status(store: TaskStore, task_id: str) -> list[dict[str, object]]:
    """Return one status dict per seat of the task's current or last debate."""
    state = require_debate(store, task_id)
    task = store.get(task_id)
    lookup = _StatusLookup(
        rounds_by_n={int(r.get("n", 0)): r for r in task.rounds},
        dropped=dropped_focuses(state),
    )
    return [_seat_status_row(seat, lookup) for seat in state.get("seats", [])]
