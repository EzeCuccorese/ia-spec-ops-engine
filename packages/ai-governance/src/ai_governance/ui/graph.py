"""Build the neural-network knowledge graph from Second Brain notes and Taskflow tasks."""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from ..brain.store import BrainNote, BrainStore, NoteFilter, is_stale
from ..taskflow.models import Task
from ..taskflow.store import TaskStore

_WIKILINK_RE = re.compile(r"\[\[([A-Za-z0-9_./-]+)\]\]")
_REF_RE = re.compile(r"\b([A-Za-z0-9][A-Za-z0-9_-]*/[a-z0-9][a-z0-9_-]*)\b")


@dataclass(frozen=True)
class GraphQuery:
    scope: str | None = None
    kind: str | None = None
    include_hubs: bool = True


@dataclass
class _GraphAcc:
    nodes: dict[str, dict[str, Any]] = field(default_factory=dict)
    links: list[dict[str, Any]] = field(default_factory=list)
    seen: set[tuple[str, str, str]] = field(default_factory=set)
    by_ref: dict[str, BrainNote] = field(default_factory=dict)
    by_slug: dict[str, list[BrainNote]] = field(default_factory=lambda: defaultdict(list))

    def register(self, note: BrainNote) -> None:
        self.by_ref[note.ref] = note
        self.by_slug[note.slug].append(note)
        self.nodes[_note_node_id(note.ref)] = _note_node(note)

    def add_edge(self, source: str, target: str, kind: str, weight: int) -> None:
        key = (source, target, kind)
        if key in self.seen or source == target:
            return
        self.seen.add(key)
        self.links.append({"source": source, "target": target, "kind": kind, "weight": weight})


def _note_node_id(ref: str) -> str:
    return f"note:{ref}"


def _note_node(note: BrainNote) -> dict[str, Any]:
    return {
        "id": _note_node_id(note.ref),
        "type": "note",
        "ref": note.ref,
        "slug": note.slug,
        "scope": note.scope,
        "kind": note.kind,
        "label": note.title,
        "tags": list(note.tags),
        "repos": list(note.repos),
        "updated": note.updated,
        "stale": is_stale(note),
    }


def _resolve_links_in_body(
    note: BrainNote,
    by_ref: dict[str, BrainNote],
    by_slug: dict[str, list[BrainNote]],
) -> set[str]:
    targets: set[str] = set()
    for token in _WIKILINK_RE.findall(note.body):
        if token in by_ref:
            targets.add(token)
        elif token in by_slug and len(by_slug[token]) == 1:
            targets.add(by_slug[token][0].ref)
    for token in _REF_RE.findall(note.body):
        if token in by_ref:
            targets.add(token)
    targets.discard(note.ref)
    return targets


def _add_hub_edges(acc: _GraphAcc, note: BrainNote) -> None:
    src = _note_node_id(note.ref)
    for tag in note.tags:
        hub_id = f"tag:{tag}"
        acc.nodes.setdefault(
            hub_id, {"id": hub_id, "type": "tag", "kind": "tag", "label": f"#{tag}"}
        )
        acc.add_edge(src, hub_id, "tag", 1)
    for repo in note.repos:
        hub_id = f"repo:{repo}"
        acc.nodes.setdefault(hub_id, {"id": hub_id, "type": "repo", "kind": "repo", "label": repo})
        acc.add_edge(src, hub_id, "repo", 1)


def _add_shared_note_edges(acc: _GraphAcc, notes: list[BrainNote]) -> None:
    for index, left in enumerate(notes):
        left_tags, left_repos = set(left.tags), set(left.repos)
        for right in notes[index + 1 :]:
            overlap = len(left_tags & set(right.tags)) + len(left_repos & set(right.repos))
            if overlap > 0:
                acc.add_edge(_note_node_id(left.ref), _note_node_id(right.ref), "shared", overlap)


def _add_task_archive_link(acc: _GraphAcc, note: BrainNote, tasks_by_id: dict[str, Task]) -> None:
    task_id = ""
    for prefix in ("task:", "taskflow:"):
        if note.source.startswith(prefix):
            task_id = note.source.removeprefix(prefix).strip()
            break
    if not task_id:
        return
    task = tasks_by_id.get(task_id)
    node_id = f"task:{task_id}"
    acc.nodes.setdefault(
        node_id,
        {
            "id": node_id,
            "type": "task",
            "kind": "task",
            "task_id": task_id,
            "label": task.title if task else task_id,
            "status": task.status if task else "archived",
        },
    )
    acc.add_edge(_note_node_id(note.ref), node_id, "archive", 2)


def _apply_degrees(acc: _GraphAcc) -> None:
    counts: dict[str, int] = defaultdict(int)
    for link in acc.links:
        counts[str(link["source"])] += 1
        counts[str(link["target"])] += 1
    for node_id, node in acc.nodes.items():
        node["degree"] = counts.get(node_id, 0)


def _populate_edges(
    acc: _GraphAcc,
    notes: list[BrainNote],
    task_store: TaskStore | None,
    *,
    include_hubs: bool,
) -> None:
    tasks_by_id = {t.id: t for t in task_store.list(include_closed=True)} if task_store else {}
    for note in notes:
        for target_ref in sorted(_resolve_links_in_body(note, acc.by_ref, acc.by_slug)):
            acc.add_edge(_note_node_id(note.ref), _note_node_id(target_ref), "reference", 3)
        _add_task_archive_link(acc, note, tasks_by_id)
        if include_hubs:
            _add_hub_edges(acc, note)
    if not include_hubs:
        _add_shared_note_edges(acc, notes)


def _graph_stats(node_list: list[dict[str, Any]], links: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for node in node_list:
        counts[str(node["type"])] += 1
    return {
        "notes": counts["note"],
        "tasks": counts["task"],
        "tags": counts["tag"],
        "repos": counts["repo"],
        "links": len(links),
    }


def build_brain_graph(
    brain_store: BrainStore,
    task_store: TaskStore | None = None,
    query: GraphQuery | None = None,
) -> dict[str, Any]:
    """Build nodes, weighted edges, and summary stats for the neural-network graph."""
    opts = query or GraphQuery()
    notes = brain_store.list(NoteFilter(scope=opts.scope, kind=opts.kind))
    acc = _GraphAcc()
    for note in notes:
        acc.register(note)

    _populate_edges(acc, notes, task_store, include_hubs=opts.include_hubs)
    _apply_degrees(acc)
    node_list = list(acc.nodes.values())
    return {
        "nodes": node_list,
        "links": acc.links,
        "stats": _graph_stats(node_list, acc.links),
    }
