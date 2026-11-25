"""Second Brain CRUD, unified search, and neural-network graph endpoints."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..brain.search import SearchQuery, SearchSources
from ..brain.search import search as brain_search
from ..brain.store import (
    DEFAULT_SCOPE,
    VALID_KINDS,
    BrainNote,
    BrainStore,
    NoteDraft,
    NoteFilter,
    SecretContentError,
    is_stale,
    today_iso,
)
from ..taskflow.store import TaskStore
from .graph import GraphQuery, build_brain_graph


class CreateNoteBody(BaseModel):
    title: str = ""
    body: str = Field(min_length=1)
    kind: str = "gotcha"
    scope: str = DEFAULT_SCOPE
    tags: list[str] = Field(default_factory=list)
    repos: list[str] = Field(default_factory=list)
    source: str = ""
    slug: str = ""


class UpdateNoteBody(BaseModel):
    title: str = Field(min_length=1)
    body: str = Field(min_length=1)
    kind: str
    tags: list[str] = Field(default_factory=list)
    repos: list[str] = Field(default_factory=list)
    source: str = ""


def _map_brain_error(exc: Exception) -> HTTPException:
    if isinstance(exc, SecretContentError):
        return HTTPException(
            status_code=422, detail={"message": str(exc), "code": "secret_rejected"}
        )
    if isinstance(exc, FileNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, FileExistsError):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status_code=400, detail=str(exc))
    return HTTPException(status_code=500, detail=str(exc))


def _serialize_note(note: BrainNote) -> dict[str, Any]:
    return {**note.to_dict(), "stale": is_stale(note)}


def _backlinks_for(store: BrainStore, target: BrainNote) -> list[dict[str, str]]:
    backlinks: list[dict[str, str]] = []
    markers = (f"[[{target.slug}]]", f"[[{target.ref}]]", target.ref)
    for other in store.list():
        if other.ref == target.ref:
            continue
        if any(marker in other.body for marker in markers):
            backlinks.append({"ref": other.ref, "title": other.title, "kind": other.kind})
    return backlinks


def _note_facets(all_notes: list[BrainNote]) -> tuple[list[str], list[str]]:
    return sorted({r for n in all_notes for r in n.repos}), sorted(
        {t for n in all_notes for t in n.tags}
    )


def build_brain_router(
    brain_factory: Callable[[], BrainStore],
    task_factory: Callable[[], TaskStore],
) -> APIRouter:
    router = APIRouter(prefix="/api/brain", tags=["brain"])

    @router.get("/notes")
    def list_notes(
        scope: str | None = None,
        kind: str | None = None,
        repo: str | None = None,
        stale_days: int | None = None,
    ) -> dict[str, Any]:
        store = brain_factory()
        flt = NoteFilter(
            scope=scope or None, kind=kind or None, repo=repo or None, stale_days=stale_days
        )
        try:
            notes, all_notes = store.list(flt), store.list()
        except Exception as exc:
            raise _map_brain_error(exc) from exc
        repos, tags = _note_facets(all_notes)
        return {
            "notes": [_serialize_note(n) for n in notes],
            "scopes": store.scopes() or [DEFAULT_SCOPE],
            "kinds": list(VALID_KINDS),
            "repos": repos,
            "tags": tags,
        }

    @router.get("/notes/{scope}/{slug}")
    def get_note(scope: str, slug: str) -> dict[str, Any]:
        store = brain_factory()
        try:
            note = store.get(f"{scope}/{slug}")
        except Exception as exc:
            raise _map_brain_error(exc) from exc
        return {"note": _serialize_note(note), "backlinks": _backlinks_for(store, note)}

    @router.post("/notes", status_code=201)
    def create_note(body: CreateNoteBody) -> dict[str, Any]:
        store = brain_factory()
        try:
            note = store.add(
                NoteDraft(
                    body=body.body,
                    title=body.title,
                    kind=body.kind,
                    scope=body.scope,
                    tags=tuple(body.tags),
                    repos=tuple(body.repos),
                    source=body.source,
                    slug=body.slug,
                )
            )
        except Exception as exc:
            raise _map_brain_error(exc) from exc
        return {"note": _serialize_note(note)}

    @router.put("/notes/{scope}/{slug}")
    def update_note(scope: str, slug: str, body: UpdateNoteBody) -> dict[str, Any]:
        store = brain_factory()
        try:
            existing = store.get(f"{scope}/{slug}")
            updated = store.save(
                BrainNote(
                    slug=existing.slug,
                    title=body.title.strip(),
                    kind=body.kind,
                    scope=existing.scope,
                    body=body.body.strip("\n"),
                    tags=tuple(dict.fromkeys(t.strip() for t in body.tags if t.strip())),
                    repos=tuple(dict.fromkeys(r.strip() for r in body.repos if r.strip())),
                    source=body.source.strip(),
                    created=existing.created,
                    updated=today_iso(),
                    path=existing.path,
                )
            )
        except Exception as exc:
            raise _map_brain_error(exc) from exc
        return {"note": _serialize_note(updated)}

    @router.get("/search")
    def search_all(
        q: str = "",
        scope: str | None = None,
        kind: str | None = None,
        limit: int = 30,
    ) -> dict[str, Any]:
        if not q.strip():
            return {"hits": []}
        brain, tasks = brain_factory(), task_factory()
        hits = brain_search(
            SearchQuery(
                text=q,
                scope=scope or None,
                kind=kind or None,
                limit=max(1, min(limit, 100)),
            ),
            SearchSources(brain_store=brain, task_store=tasks),
        )
        return {
            "hits": [
                {
                    "source": h.source,
                    "ref": (
                        f"{h.scope}/{Path(h.path).stem}"
                        if h.source == "brain"
                        else Path(h.path).parent.name
                        if h.source == "taskflow"
                        else Path(h.path).stem
                    ),
                    "path": h.path,
                    "title": h.title,
                    "kind": h.kind,
                    "scope": h.scope,
                    "snippet": h.snippet,
                    "score": h.score,
                }
                for h in hits
            ]
        }

    @router.get("/graph")
    def get_graph(
        scope: str | None = None,
        kind: str | None = None,
        hubs: bool = True,
    ) -> dict[str, Any]:
        try:
            return build_brain_graph(
                brain_factory(),
                task_factory(),
                GraphQuery(scope=scope or None, kind=kind or None, include_hubs=hubs),
            )
        except Exception as exc:
            raise _map_brain_error(exc) from exc

    return router
