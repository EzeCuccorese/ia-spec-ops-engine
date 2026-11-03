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
from .agents import HUMAN
from .control import CheckedBaseline, DispatchError
from .dispatch import Dispatched, DispatchRequest, plan_dispatch
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


def _preflight(task: Task) -> None:
    """A reader round needs Orca and every bound repo on disk (it records them all)."""
    orca.require_orca()
    if missing := partition(task.repos).missing:
        raise DispatchError(f"bound repo not found: {missing[0]['path']}")


def _dispatch_all(
    job: JudgeJob, judges: list[JsonDict], run: CheckRun, expected: CheckedBaseline
) -> Iterator[Dispatched]:
    for judge in judges:
        if judge.get("agent") == HUMAN:
            continue  # the user judges in the chat: approve --action review --target <focus>
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
    if any(j.get("agent") != HUMAN for j in judges):
        _preflight(task)  # fail before spending time on the checks
    bound = _bound(job)
    paths = [Path(b["path"]) for b in bound]
    run = on_live(paths, lambda: run_engine_checks(job.store, task, ctx, bound))
    if (now := restamp()) != ctx.stamp_key:
        raise JudgeError(
            f"the code changed while the checks ran (stamp {ctx.stamp_key[:12]} -> {now[:12]}): "
            f"nothing was recorded or dispatched; run `taskflow judge {task.id}` again"
        )
    job.store.mutate(task.id, lambda t: t.evidence.extend(run.evidence))
    yield from _dispatch_all(job, judges, run, run.baseline(ctx.stamp_key))
