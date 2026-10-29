"""Deterministic, task-scoped context that opens every prompt sent to an agent."""

from __future__ import annotations

from pathlib import Path

from .handoff import scrub
from .models import JsonDict, Task
from .store import TaskStore

RECENT_LIMIT = 5
_NEEDS_PLAN = ("validator", "builder")
FIELD_CHARS = 300


def _recent(items: list[JsonDict]) -> list[JsonDict]:
    return items[-RECENT_LIMIT:]


def _cap(text: object) -> str:
    value = str(text)
    return value if len(value) <= FIELD_CHARS else value[:FIELD_CHARS] + "..."


def task_context_lines(task: Task) -> list[str]:
    """Goal, decisions, facts and references: what every agent working on the task must know."""
    lines = [f"Goal: {_cap(task.summary or task.title)}"]
    for decision in _recent(task.decisions):
        why = f" (why: {decision['why']})" if decision.get("why") else ""
        lines.append(_cap(f"- decision: {decision['text']}{why}"))
    lines += [_cap(f"- fact: {fact['text']}") for fact in _recent(task.facts)]
    lines += [
        _cap(f"- reference: {r.get('kind')} {r.get('value')} {r.get('url', '')}".rstrip())
        for r in _recent(task.references)
    ]
    return lines


def _valid_rounds(task: Task, role: str) -> list[JsonDict]:
    return [
        r
        for r in task.rounds
        if r.get("role") == role and r.get("source") == "engine" and r.get("state") == "valid"
    ]


def _plan_lines(task: Task) -> list[str]:
    plans = _valid_rounds(task, "planner")
    if not plans:
        return ["Latest plan: none yet for this task."]
    plan = max(plans, key=lambda r: int(r["n"]))
    lines = [f"Latest plan (read it first): {plan['file']}"]
    since = [v for v in _valid_rounds(task, "validator") if v["n"] > plan["n"]]
    lines += [f"- validator round {v['file']}: {v.get('verdict')}" for v in _recent(since)]
    return lines


def round_header(store: TaskStore, task_id: str, role: str) -> str:
    """Everything an agent needs to stay on this task, and nothing from other tasks."""
    task = store.get(task_id)
    lines = [
        f"Role: {role}. Task {task.id}: {task.title}.",
        "Only this task: ignore other tasks' files under the taskflow store.",
        *task_context_lines(task),
        f"Rounds of this task: {store.rounds_dir(task.id)}",
    ]
    if role in _NEEDS_PLAN:
        lines += _plan_lines(task)
    if role != "judge":  # a judge works on its isolated copy, never the builder's checkout
        lines += [
            f"Repository {Path(r['path'])} (branch {r.get('branch', '')})" for r in task.repos
        ]
    return scrub("\n".join(lines)) + "\n\n"
