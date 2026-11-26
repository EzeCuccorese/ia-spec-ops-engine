"""Taskflow & debate/Orca orchestration API endpoints for the visual dashboard."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..brain.archive import ArchiveOptions, archive_task
from ..brain.store import BrainStore, SecretContentError
from ..taskflow import orca
from ..taskflow.collect import RoundRef, abort_round, collect_round
from ..taskflow.config import load_config
from ..taskflow.control import UsageRefusal
from ..taskflow.debate import (
    OpenDebateOptions,
    cross_debate,
    debate_status,
    load_debate,
    open_debate,
)
from ..taskflow.dispatch import DispatchError
from ..taskflow.models import STATUSES, WORKFLOWS, Task, now_iso
from ..taskflow.store import LOG_FILE, TaskStore, atomic_write_text, validate_task_id
from ..taskflow.synthesis import close_debate
from ..tools.atlassian_common import AtlassianError
from .jira_lookup import fetch_jira_issue
from .launcher import _extract_dispatch_id, launch_reserved_round


class CreateTaskBody(BaseModel):
    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    summary: str = ""
    workflow: str = "tri-agent"
    parent: str = ""
    jira_url: str = ""


class PatchTaskBody(BaseModel):
    title: str | None = None
    summary: str | None = None
    status: str | None = None
    phase: str | None = None
    blocked: dict[str, Any] | None = None


class StepBody(BaseModel):
    text: str = Field(min_length=1)


class StepPatchBody(BaseModel):
    done: bool


class FactBody(BaseModel):
    text: str = Field(min_length=1)


class DecisionBody(BaseModel):
    text: str = Field(min_length=1)
    why: str = Field(min_length=1)


class LinkBody(BaseModel):
    title: str = Field(min_length=1)
    url: str = Field(min_length=1)


class ArchiveBody(BaseModel):
    scope: str | None = None


class DebateOpenBody(BaseModel):
    topic: str = Field(min_length=1)
    agents: list[str] = Field(min_length=1)
    models: dict[str, str] = Field(default_factory=dict)
    web: bool = False


class DebateCloseBody(BaseModel):
    partial: bool = False


class RoundCollectBody(BaseModel):
    dispatch_id: str = Field(min_length=1)


class RoundAbortBody(BaseModel):
    reason: str = Field(min_length=1)
    dispatch_id: str | None = None


def _map_error(exc: Exception) -> HTTPException:
    if isinstance(exc, SecretContentError):
        return HTTPException(
            status_code=422, detail={"message": str(exc), "code": "secret_rejected"}
        )
    if isinstance(exc, FileNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, FileExistsError):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, orca.OrcaError):
        return HTTPException(status_code=502, detail=str(exc))
    if isinstance(exc, (ValueError, DispatchError, UsageRefusal)):
        return HTTPException(status_code=400, detail=str(exc))
    return HTTPException(status_code=500, detail=str(exc))


def _pending_dispatches(store: TaskStore, task: Task) -> list[dict[str, Any]]:
    settled = {int(r.get("n", 0)) for r in task.rounds}
    runs_dir = store.task_dir(task.id) / "runs"
    if not runs_dir.is_dir():
        return []
    items: list[dict[str, Any]] = []
    for path in sorted(runs_dir.glob("*/dispatch.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        number = int(data.get("n", 0))
        if number in settled:
            continue
        launch_path = Path(str(data.get("launch", "")))
        launch_text = launch_path.read_text(encoding="utf-8") if launch_path.is_file() else ""
        items.append(
            {
                "n": number,
                "role": str(data.get("role", "")),
                "focus": str(data.get("focus", "")),
                "agent": str(data.get("agent", "")),
                "model": str(data.get("model", "")),
                "launched": launch_path.is_file(),
                "dispatch_id": _extract_dispatch_id(launch_text),
            }
        )
    return items


def _task_summary_dict(store: TaskStore, task: Task) -> dict[str, Any]:
    done = sum(1 for step in task.steps if step.get("done"))
    return {
        "id": task.id,
        "title": task.title,
        "status": task.status,
        "summary": task.summary,
        "parent": task.parent,
        "workflow": task.workflow,
        "phase": task.phase,
        "blocked": task.blocked,
        "subtasks": list(task.subtasks),
        "done_steps": done,
        "total_steps": len(task.steps),
        "repos": list(task.repos),
        "links": list(task.links),
        "has_debate": load_debate(store, task.id) is not None,
        "pending_rounds": len(_pending_dispatches(store, task)),
        "created_at": task.created_at,
        "updated_at": task.updated_at,
    }


def _task_detail_dict(store: TaskStore, task: Task) -> dict[str, Any]:
    task_dir = store.task_dir(task.id)
    log_path = task_dir / LOG_FILE
    log_lines = (
        log_path.read_text(encoding="utf-8").splitlines()[-100:] if log_path.is_file() else []
    )
    synthesis_path = task_dir / "debate" / "synthesis.md"
    synthesis = synthesis_path.read_text(encoding="utf-8") if synthesis_path.is_file() else ""
    debate_state = load_debate(store, task.id)
    seats = debate_status(store, task.id) if debate_state is not None else []
    return {
        **task.to_dict(),
        "log_lines": log_lines,
        "pending_dispatches": _pending_dispatches(store, task),
        "debate": {
            "active": debate_state is not None,
            "state": debate_state,
            "seats": seats,
            "synthesis": synthesis,
        },
    }


def _apply_task_patch(task: Task, body: PatchTaskBody) -> None:
    if body.title is not None:
        task.title = body.title.strip()
    if body.summary is not None:
        task.summary = body.summary.strip()
    if body.status is not None:
        if body.status not in STATUSES:
            raise ValueError(f"Invalid status {body.status!r}; expected {STATUSES}")
        task.status = body.status
    if body.phase is not None:
        task.phase = body.phase.strip()
    if body.blocked is not None:
        task.blocked = dict(body.blocked)


def _map_atlassian_error(exc: AtlassianError) -> HTTPException:
    msg = str(exc)
    lower = msg.lower()
    if "not set" in lower or "atlassian_" in lower:
        return HTTPException(status_code=503, detail=msg)
    if "404" in lower or "not found" in lower or "does not exist" in lower:
        return HTTPException(status_code=404, detail=msg)
    return HTTPException(status_code=502, detail=msg)


def _register_task_crud_routes(router: APIRouter, store_factory: Callable[[], TaskStore]) -> None:
    @router.get("")
    def list_tasks(include_closed: bool = True) -> dict[str, Any]:
        store = store_factory()
        tasks = [_task_summary_dict(store, t) for t in store.list(include_closed=include_closed)]
        return {"tasks": tasks}

    @router.get("/jira-lookup")
    def jira_lookup(q: str = "") -> dict[str, str]:
        try:
            return fetch_jira_issue(q)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except AtlassianError as exc:
            raise _map_atlassian_error(exc) from exc

    @router.post("", status_code=201)
    def create_task(body: CreateTaskBody) -> dict[str, Any]:
        store = store_factory()
        try:
            task_id = validate_task_id(body.id.strip())
            if body.workflow not in WORKFLOWS:
                raise ValueError(f"Invalid workflow {body.workflow!r}; expected {WORKFLOWS}")
            links = (
                [{"title": f"Jira {task_id}", "url": body.jira_url.strip()}]
                if body.jira_url.strip()
                else []
            )
            task = Task(
                id=task_id,
                title=body.title.strip(),
                summary=body.summary.strip(),
                workflow=body.workflow,
                parent=body.parent.strip(),
                links=links,
            )
            created = store.create(task)
            return {"task": _task_detail_dict(store, created)}
        except Exception as exc:
            raise _map_error(exc) from exc

    @router.get("/{task_id}")
    def get_task(task_id: str) -> dict[str, Any]:
        store = store_factory()
        try:
            return {"task": _task_detail_dict(store, store.get(task_id))}
        except Exception as exc:
            raise _map_error(exc) from exc

    @router.patch("/{task_id}")
    def patch_task(task_id: str, body: PatchTaskBody) -> dict[str, Any]:
        store = store_factory()
        try:
            updated = store.mutate(task_id, lambda t: _apply_task_patch(t, body))
            return {"task": _task_detail_dict(store, updated)}
        except Exception as exc:
            raise _map_error(exc) from exc


def _register_notebook_routes(
    router: APIRouter,
    store_factory: Callable[[], TaskStore],
    brain_factory: Callable[[], BrainStore],
) -> None:
    @router.post("/{task_id}/steps", status_code=201)
    def add_step(task_id: str, body: StepBody) -> dict[str, Any]:
        store = store_factory()
        try:
            updated = store.mutate(
                task_id,
                lambda t: t.steps.append({"text": body.text.strip(), "done": False}),
                f"Step added: {body.text.strip()}",
            )
            return {"task": _task_detail_dict(store, updated)}
        except Exception as exc:
            raise _map_error(exc) from exc

    @router.patch("/{task_id}/steps/{index}")
    def toggle_step(task_id: str, index: int, body: StepPatchBody) -> dict[str, Any]:
        store = store_factory()

        def _toggle(task: Task) -> None:
            if index < 0 or index >= len(task.steps):
                raise ValueError(f"Step index {index} out of range")
            task.steps[index]["done"] = body.done

        try:
            updated = store.mutate(task_id, _toggle)
            return {"task": _task_detail_dict(store, updated)}
        except Exception as exc:
            raise _map_error(exc) from exc

    @router.post("/{task_id}/facts", status_code=201)
    def add_fact(task_id: str, body: FactBody) -> dict[str, Any]:
        store = store_factory()
        try:
            updated = store.mutate(
                task_id,
                lambda t: t.facts.append({"text": body.text.strip(), "at": now_iso()}),
            )
            return {"task": _task_detail_dict(store, updated)}
        except Exception as exc:
            raise _map_error(exc) from exc

    @router.post("/{task_id}/decisions", status_code=201)
    def add_decision(task_id: str, body: DecisionBody) -> dict[str, Any]:
        store = store_factory()
        try:
            updated = store.mutate(
                task_id,
                lambda t: t.decisions.append(
                    {"text": body.text.strip(), "why": body.why.strip(), "at": now_iso()}
                ),
            )
            return {"task": _task_detail_dict(store, updated)}
        except Exception as exc:
            raise _map_error(exc) from exc

    @router.post("/{task_id}/links", status_code=201)
    def add_link(task_id: str, body: LinkBody) -> dict[str, Any]:
        store = store_factory()
        try:
            updated = store.mutate(
                task_id,
                lambda t: t.links.append({"title": body.title.strip(), "url": body.url.strip()}),
            )
            return {"task": _task_detail_dict(store, updated)}
        except Exception as exc:
            raise _map_error(exc) from exc

    @router.post("/{task_id}/archive")
    def archive_to_brain(task_id: str, body: ArchiveBody) -> dict[str, Any]:
        store, brain = store_factory(), brain_factory()
        try:
            res = archive_task(
                task_id,
                ArchiveOptions(scope=body.scope, task_store=store, brain_store=brain),
            )
            return {
                "ref": res.note.ref,
                "action": res.action,
                "created": res.action == "created",
                "updated": res.action == "updated",
            }
        except Exception as exc:
            raise _map_error(exc) from exc


def _register_debate_routes(router: APIRouter, store_factory: Callable[[], TaskStore]) -> None:
    @router.post("/{task_id}/debates/open")
    def api_open_debate(task_id: str, body: DebateOpenBody) -> dict[str, Any]:
        store = store_factory()
        try:
            task = store.get(task_id)
            topic_file = store.task_dir(task_id) / "debate-topic.md"
            atomic_write_text(topic_file, body.topic.strip() + "\n")
            cfg = load_config([Path(r["path"]) for r in task.repos])
            res = open_debate(
                store,
                task_id,
                cfg,
                OpenDebateOptions(
                    topic_file=topic_file,
                    agents=tuple(body.agents),
                    models=dict(body.models),
                    web=body.web,
                ),
            )
            return {
                "debate_id": res.debate_id,
                "rounds": [
                    {
                        "n": s.round.n,
                        "focus": s.seat.focus,
                        "agent": s.seat.agent,
                        "model": s.seat.model,
                    }
                    for s in res.seats
                ],
            }
        except Exception as exc:
            raise _map_error(exc) from exc

    @router.post("/{task_id}/debates/cross")
    def api_cross_debate(task_id: str) -> dict[str, Any]:
        store = store_factory()
        try:
            task = store.get(task_id)
            cfg = load_config([Path(r["path"]) for r in task.repos])
            res = cross_debate(store, task_id, cfg)
            return {
                "debate_id": res.debate_id,
                "warnings": list(res.warnings),
                "rounds": [
                    {
                        "n": s.round.n,
                        "focus": s.seat.focus,
                        "agent": s.seat.agent,
                        "model": s.seat.model,
                    }
                    for s in res.seats
                ],
            }
        except Exception as exc:
            raise _map_error(exc) from exc

    @router.post("/{task_id}/debates/close")
    def api_close_debate(task_id: str, body: DebateCloseBody) -> dict[str, Any]:
        store = store_factory()
        try:
            path = close_debate(store, task_id, partial=body.partial)
            return {"synthesis_path": str(path), "synthesis": path.read_text(encoding="utf-8")}
        except Exception as exc:
            raise _map_error(exc) from exc

    @router.post("/{task_id}/rounds/{number}/launch")
    def api_launch_round(task_id: str, number: int) -> dict[str, Any]:
        try:
            return launch_reserved_round(store_factory(), task_id, number)
        except Exception as exc:
            raise _map_error(exc) from exc

    @router.post("/{task_id}/rounds/{number}/collect")
    def api_collect_round(task_id: str, number: int, body: RoundCollectBody) -> dict[str, Any]:
        try:
            res = collect_round(store_factory(), RoundRef(task_id, number), body.dispatch_id)
            return {"record": res.record, "already_settled": res.already}
        except Exception as exc:
            raise _map_error(exc) from exc

    @router.post("/{task_id}/rounds/{number}/abort")
    def api_abort_round(task_id: str, number: int, body: RoundAbortBody) -> dict[str, Any]:
        try:
            rec = abort_round(
                store_factory(), RoundRef(task_id, number), body.reason, body.dispatch_id
            )
            return {"record": rec}
        except Exception as exc:
            raise _map_error(exc) from exc


def build_tasks_router(
    store_factory: Callable[[], TaskStore],
    brain_factory: Callable[[], BrainStore],
) -> APIRouter:
    router = APIRouter(prefix="/api/tasks", tags=["tasks"])
    _register_task_crud_routes(router, store_factory)
    _register_notebook_routes(router, store_factory, brain_factory)
    _register_debate_routes(router, store_factory)
    return router
