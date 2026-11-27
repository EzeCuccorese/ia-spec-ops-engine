"""Pull request review: one reviewer round per PR, then one judge round of another provider.

A review is a set of ordinary rounds (``validator`` as the reviewer, ``judge``) plus a
``review.json`` file in the task directory. Each round is bound to a read-only capture of
its pull request (see ``review_source``), not to a local working tree, so several pull
requests are reviewed in parallel and none needs a local checkout. ``review.json`` stays
outside ``control.baseline``: opening, judging or closing never counts as control drift.

The engine dispatches nothing itself and writes nothing to GitHub. Publishing a review is a
separate step of the coordinating session, after the owner approved the summary.
"""

from __future__ import annotations

import json
import os
import shutil
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from . import orca
from .agents import DEFAULT_MODELS, HUMAN, PREFERENCE, provider, read_regular_text
from .config import FlowConfig
from .control import DispatchError

# Review state shares the debate's per-task lock: both reserve rounds of the same task.
from .debate import _debate_lock as _state_lock
from .debate import _rollback_dispatched
from .dispatch import Dispatched, DispatchRequest, plan_dispatch
from .models import JsonDict, Task, now_iso
from .review_format import judge_prompt, reviewer_prompt
from .review_source import PullRef, PullSnapshot, parse_pr_url, snapshot_pull_request, viewer_login
from .store import TaskStore, atomic_write_text

REVIEW_FILE = "review.json"
REVIEWER_ROLE = "validator"
JUDGE_ROLE = "judge"
MAX_PULL_REQUESTS = 8


@dataclass(frozen=True)
class OpenReviewOptions:
    """What ``review open`` was asked: which pull requests, who reviews, any extra focus."""

    urls: tuple[str, ...]
    agent: str
    model: str = ""
    lens: str = ""


@dataclass(frozen=True)
class DispatchedReview:
    """One pull request paired with the round just reserved for it."""

    key: str
    round: Dispatched


@dataclass(frozen=True)
class ReviewDispatch:
    """Outcome of ``open_review`` or ``judge_review``."""

    review_id: int
    items: tuple[DispatchedReview, ...]
    warnings: tuple[str, ...] = ()


def review_path(store: TaskStore, task_id: str) -> Path:
    return store.task_dir(task_id) / REVIEW_FILE


def load_review(store: TaskStore, task_id: str) -> JsonDict | None:
    """``review.json`` if present, or None when no review was opened yet."""
    path = review_path(store, task_id)
    if not os.path.lexists(path):
        return None
    try:
        data = json.loads(read_regular_text(path))
    except (OSError, ValueError) as exc:
        raise DispatchError(f"cannot read {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise DispatchError(f"corrupted review state in {path}: expected a JSON object")
    return data


def require_review(store: TaskStore, task_id: str) -> JsonDict:
    data = load_review(store, task_id)
    if data is None:
        raise DispatchError(f"no review found for task '{task_id}'")
    return data


def save_review(store: TaskStore, task_id: str, state: JsonDict) -> None:
    atomic_write_text(
        review_path(store, task_id), json.dumps(state, indent=2, ensure_ascii=False) + "\n"
    )


def snapshot_of(entry: JsonDict) -> PullSnapshot:
    """The capture a ``review.json`` entry describes."""
    return PullSnapshot(
        ref=parse_pr_url(str(entry["url"])),
        title=str(entry.get("title", "")),
        head_sha=str(entry["head_sha"]),
        base_ref=str(entry.get("base_ref", "")),
        is_draft=bool(entry.get("draft", False)),
        directory=Path(str(entry["dir"])),
    )


def _check_agent(config: FlowConfig, agent: str, what: str) -> None:
    if not agent or provider(agent) == HUMAN:
        raise DispatchError(f"{what}: a human cannot run as a worker")
    if err := config.agent_error(agent):
        raise DispatchError(f"{what}: {err}")


def _check_task(task: Task) -> None:
    if task.blocked:
        raise DispatchError(
            f"'{task.id}' is blocked by {task.blocked.get('owner')}: {task.blocked.get('needs')}"
        )


def _unique_refs(urls: Sequence[str]) -> list[PullRef]:
    refs: dict[str, PullRef] = {}
    for url in urls:
        ref = parse_pr_url(url)
        refs.setdefault(ref.key, ref)
    if not refs:
        raise DispatchError("a review needs at least one pull request (--pr <url>)")
    if len(refs) > MAX_PULL_REQUESTS:
        raise DispatchError(
            f"a review takes at most {MAX_PULL_REQUESTS} pull requests; open another one for the rest"
        )
    return list(refs.values())


def _entry(snapshot: PullSnapshot, agent: str, made: Dispatched) -> JsonDict:
    return {
        "key": snapshot.ref.key,
        "url": snapshot.ref.url,
        "title": snapshot.title,
        "head_sha": snapshot.head_sha,
        "base_ref": snapshot.base_ref,
        "draft": snapshot.is_draft,
        "dir": str(snapshot.directory),
        "reviewer": {"agent": agent, "round": made.n},
        "judge": None,
    }


def _dispatch(
    store: TaskStore,
    task: Task,
    config: FlowConfig,
    requests: Sequence[tuple[str, DispatchRequest]],
) -> tuple[DispatchedReview, ...]:
    """Reserve every round or none: a failure withdraws the ones already reserved."""
    reserved: list[Dispatched] = []
    try:
        for _, request in requests:
            reserved.append(plan_dispatch(store, task, config, request))
    except BaseException:
        _rollback_dispatched(store, task.id, reserved)
        raise
    return tuple(
        DispatchedReview(key, made) for (key, _), made in zip(requests, reserved, strict=True)
    )


def _launch_model(agent: str, model: str) -> str:
    """The model a round launches with: the one asked for, else the provider's default, so the
    launch can be verified at collect (empty only for a provider without a default). Dispatch
    resolves the same default only when an effort or denied models need it, so it is kept here."""
    return model.strip() or DEFAULT_MODELS.get(provider(agent), "")


def _reviewer_request(
    task: Task, snapshot: PullSnapshot, opts: OpenReviewOptions
) -> DispatchRequest:
    return DispatchRequest(
        role=REVIEWER_ROLE,
        phase=task.phase,
        focus=snapshot.ref.key,
        prompt=reviewer_prompt(snapshot, opts.lens),
        agent={"agent": opts.agent, "model": _launch_model(opts.agent, opts.model)},
        source=str(snapshot.source),
    )


def _open_locked(
    store: TaskStore, task_id: str, config: FlowConfig, opts: OpenReviewOptions
) -> ReviewDispatch:
    task = store.get(task_id)
    _check_task(task)
    existing = load_review(store, task_id)
    if existing is not None and existing.get("status") != "closed":
        raise DispatchError(f"task '{task_id}' already has an open review: close it first")
    _check_agent(config, opts.agent, "reviewer")
    refs = _unique_refs(opts.urls)
    orca.require_orca()
    review_id = int(existing.get("review_id", 0)) + 1 if existing else 1
    root = store.task_dir(task_id) / "review" / f"{review_id:03d}"
    try:
        viewer = viewer_login()
        snapshots = [snapshot_pull_request(ref.url, root / ref.key) for ref in refs]
        requests = [(s.ref.key, _reviewer_request(task, s, opts)) for s in snapshots]
        dispatched = _dispatch(store, task, config, requests)
    except BaseException:
        shutil.rmtree(root, ignore_errors=True)
        raise
    state: JsonDict = {
        "review_id": review_id,
        "status": "open",
        "opened_at": now_iso(),
        "viewer": viewer,
        "lens": opts.lens,
        "prs": [
            _entry(snapshot, opts.agent, item.round)
            for snapshot, item in zip(snapshots, dispatched, strict=True)
        ],
    }
    try:
        save_review(store, task_id, state)
    except BaseException:
        _rollback_dispatched(store, task_id, [item.round for item in dispatched])
        shutil.rmtree(root, ignore_errors=True)
        raise
    return ReviewDispatch(review_id, dispatched)


def open_review(
    store: TaskStore, task_id: str, config: FlowConfig, opts: OpenReviewOptions
) -> ReviewDispatch:
    """Capture each pull request and reserve one reviewer round per pull request."""
    with _state_lock(store, task_id):
        return _open_locked(store, task_id, config, opts)


def default_judge(config: FlowConfig, reviewer: str) -> str:
    """The preferred judge agent that is allowed here and is not the reviewer's provider."""
    for agent in PREFERENCE[JUDGE_ROLE]:
        if provider(agent) != provider(reviewer) and config.agent_error(agent) is None:
            return agent
    raise DispatchError(
        f"no allowed agent of another provider can judge a review by '{reviewer}': pass --agent"
    )


def _round_record(task: Task, number: int) -> JsonDict | None:
    return next((r for r in task.rounds if int(r.get("n", 0)) == number), None)


def _judgeable(task: Task, entries: Sequence[JsonDict]) -> tuple[list[JsonDict], list[str]]:
    """Entries whose reviewer round is settled and valid; the rest become warnings. A reviewer
    round still pending refuses the whole step, so the judges are dispatched together."""
    pending = [
        int(entry["reviewer"]["round"])
        for entry in entries
        if _round_record(task, int(entry["reviewer"]["round"])) is None
    ]
    if pending:
        joined = ", ".join(f"{n:03d}" for n in pending)
        raise DispatchError(f"reviewer round(s) still pending: {joined}")
    ready: list[JsonDict] = []
    warnings: list[str] = []
    for entry in entries:
        record = _round_record(task, int(entry["reviewer"]["round"])) or {}
        if record.get("state") == "valid":
            ready.append(entry)
        else:
            reason = record.get("reason") or record.get("state") or "invalid"
            warnings.append(f"{entry['key']}: reviewer round is not valid ({reason}); not judged")
    return ready, warnings


def _judge_request(task: Task, entry: JsonDict, agent: str, model: str) -> DispatchRequest:
    snapshot = snapshot_of(entry)
    record = _round_record(task, int(entry["reviewer"]["round"])) or {}
    return DispatchRequest(
        role=JUDGE_ROLE,
        phase=task.phase,
        focus=str(entry["key"]),
        prompt=judge_prompt(snapshot, Path(str(record["file"]))),
        agent={"agent": agent, "model": _launch_model(agent, model)},
        source=str(snapshot.source),
    )


def _open_entries(state: JsonDict, task_id: str) -> list[JsonDict]:
    if state.get("status") != "open":
        raise DispatchError(f"review for '{task_id}' is {state.get('status')}, not open")
    entries = [entry for entry in state.get("prs", []) if isinstance(entry, dict)]
    if any(entry.get("judge") for entry in entries):
        raise DispatchError("judge rounds were already dispatched for this review")
    return entries


def _pick_judge(config: FlowConfig, agent: str, ready: Sequence[JsonDict]) -> str:
    """The judge for these pull requests: of another provider than every reviewer."""
    reviewer = str(ready[0]["reviewer"]["agent"])
    judge = agent or default_judge(config, reviewer)
    _check_agent(config, judge, "judge")
    if any(provider(judge) == provider(str(e["reviewer"]["agent"])) for e in ready):
        raise DispatchError(
            f"the judge must be of another provider than the reviewer ('{reviewer}'): "
            f"'{judge}' is not"
        )
    return judge


def _judge_locked(
    store: TaskStore, task_id: str, config: FlowConfig, agent: str, model: str
) -> ReviewDispatch:
    state = require_review(store, task_id)
    entries = _open_entries(state, task_id)
    task = store.get(task_id)
    _check_task(task)
    ready, warnings = _judgeable(task, entries)
    if not ready:
        raise DispatchError("no pull request has a valid reviewer round to judge")
    judge = _pick_judge(config, agent, ready)
    orca.require_orca()
    requests = [(str(e["key"]), _judge_request(task, e, judge, model)) for e in ready]
    dispatched = _dispatch(store, task, config, requests)
    rounds = {item.key: item.round.n for item in dispatched}
    for entry in ready:
        entry["judge"] = {"agent": judge, "round": rounds[entry["key"]]}
    try:
        save_review(store, task_id, state)
    except BaseException:
        _rollback_dispatched(store, task_id, [item.round for item in dispatched])
        raise
    return ReviewDispatch(int(state["review_id"]), dispatched, tuple(warnings))


def judge_review(
    store: TaskStore, task_id: str, config: FlowConfig, agent: str = "", model: str = ""
) -> ReviewDispatch:
    """Reserve one judge round per pull request whose reviewer round is valid."""
    with _state_lock(store, task_id):
        return _judge_locked(store, task_id, config, agent, model)


def _round_state(task: Task, slot: object) -> tuple[int | None, str]:
    if not isinstance(slot, dict):
        return None, "not dispatched"
    number = int(slot["round"])
    record = _round_record(task, number)
    return number, str(record.get("state", "invalid")) if record is not None else "pending"


def review_status(store: TaskStore, task_id: str) -> list[JsonDict]:
    """One row per pull request of the task's current or last review."""
    state = require_review(store, task_id)
    task = store.get(task_id)
    rows: list[JsonDict] = []
    for entry in state.get("prs", []):
        reviewer_round, reviewer_state = _round_state(task, entry.get("reviewer"))
        judge_round, judge_state = _round_state(task, entry.get("judge"))
        rows.append(
            {
                "pr": entry["key"],
                "head": str(entry["head_sha"])[:10],
                "reviewer_round": reviewer_round,
                "reviewer_state": reviewer_state,
                "judge_round": judge_round,
                "judge_state": judge_state,
            }
        )
    return rows
