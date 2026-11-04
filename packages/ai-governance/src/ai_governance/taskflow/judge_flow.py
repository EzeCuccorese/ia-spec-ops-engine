"""``taskflow judge``: the engine runs the checks, then one reader round per focus is dispatched.

Order, so that evidence and dispatches always describe ONE baseline (the clean committed code
the stamp was taken on):

1. judges are resolved and their independence from the builder is checked;
2. the checks run by code in a throwaway copy of each repo, and every real checkout is
   verified unchanged afterwards (``judge.run_engine_checks``);
3. the code stamp is recomputed; if it moved, nothing is recorded and nothing is dispatched;
4. the check evidence is recorded with that stamp;
5. each non-human focus is dispatched against the very HEAD and tree fingerprint the checks
   used (``dispatch`` refuses when they differ), and the worker-start line is yielded.

Judges whose agent is ``human`` need no worker: the user approves them in the chat.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

from . import orca
from .control import CheckedBaseline, DispatchError
from .dispatch import (
    Dispatched,
    DispatchRequest,
    check_dispatchable,
    plan_dispatch,
    refuse_pending,
)
from .gates import GateContext
from .judge import (
    CheckRun,
    JudgeError,
    JudgeScope,
    independent_judges,
    judge_prompt,
    run_engine_checks,
)
from .models import JsonDict, Task
from .repos import NONE_LIVE, on_live, partition
from .risk import decided_by_human
from .store import TaskStore


@dataclass(frozen=True)
class JudgeJob:
    store: TaskStore
    task: Task
    ctx: GateContext
    scope: JudgeScope


def _bound(job: JudgeJob) -> list[JsonDict]:
    task = job.task
    bound = list(partition(task.repos).live if job.scope.repos is None else job.scope.repos)
    if task.repos and not bound:
        raise ValueError(NONE_LIVE)
    return bound


def _engine_judges(job: JudgeJob, judges: list[JsonDict]) -> list[JsonDict]:
    """Judges a worker runs; the frozen risk decides which focuses the user judges."""
    return [
        j for j in judges if not decided_by_human(job.ctx.risk, job.ctx.config, str(j["focus"]))
    ]


def _preflight(job: JudgeJob, judges: list[JsonDict]) -> None:
    """Refuse before the checks run: Orca, every bound repo on disk, allowed agents and no
    judge round already pending for a focus."""
    orca.require_orca()
    task = job.task
    if missing := partition(task.repos).missing:
        raise DispatchError(f"bound repo not found: {missing[0]['path']}")
    task_dir = job.store.task_dir(task.id)
    for judge in judges:
        request = DispatchRequest("judge", task.phase, str(judge["focus"]), "", judge)
        check_dispatchable(task, job.ctx.config, request)
        refuse_pending(task, task_dir, request)


def _dispatch_all(
    job: JudgeJob, judges: list[JsonDict], run: CheckRun, expected: CheckedBaseline
) -> Iterator[Dispatched]:
    for judge in _engine_judges(job, judges):  # the user judges the rest in the chat
        focus = str(judge["focus"])
        prompt = judge_prompt(job.task, focus, run)
        request = DispatchRequest("judge", job.task.phase, focus, prompt, judge, expected)
        yield plan_dispatch(job.store, job.store.get(job.task.id), job.ctx.config, request)


def judge_flow(job: JudgeJob, restamp: Callable[[], str]) -> Iterator[Dispatched]:
    """Run the checks, record their evidence and yield one dispatch per non-human focus.
    ``restamp`` recomputes the code stamp key; a different one than the job started from
    means the code moved while the checks ran."""
    task, ctx = job.task, job.ctx
    judges = independent_judges(task, ctx.config, job.scope.focus, list(ctx.risk.judges))
    if engine := _engine_judges(job, judges):
        _preflight(job, engine)  # fail before spending time on the checks
    bound = _bound(job)
    paths = [Path(b["path"]) for b in bound]
    run = on_live(paths, lambda: run_engine_checks(job.store, task, ctx, bound))
    if (now := restamp()) != ctx.stamp_key:
        raise JudgeError(
            f"the code changed while the checks ran (stamp {ctx.stamp_key[:12]} -> {now[:12]}): "
            f"nothing was recorded or dispatched; run `taskflow judge {task.id}` again"
        )
    run.publish()
    job.store.mutate(task.id, lambda t: t.evidence.extend(run.evidence))
    yield from _dispatch_all(job, judges, run, run.baseline(ctx.stamp_key))
