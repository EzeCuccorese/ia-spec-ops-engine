"""Unified plain-text search across brain notes, taskflow tasks, and scoped corporate rules."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from .. import corporate
from ..paths import state_dir
from ..taskflow.handoff import scrub
from ..taskflow.models import Task
from ..taskflow.store import TaskStore
from .store import DEFAULT_SCOPE, VALID_KINDS, BrainNote, BrainStore, NoteFilter, infer_scope

SEARCH_KINDS: tuple[str, ...] = (*VALID_KINDS, "task", "rule")
DEFAULT_LIMIT = 20
_SNIPPET_MAX = 120
_FRONTMATTER_RE = re.compile(r"^---\r?\n.*?\r?\n---(?:\r?\n|$)", re.DOTALL)


@dataclass(frozen=True)
class SearchQuery:
    text: str
    kind: str | None = None
    scope: str | None = None
    limit: int = DEFAULT_LIMIT


@dataclass(frozen=True)
class SearchSources:
    brain_store: BrainStore | None = None
    task_store: TaskStore | None = None
    corporate_dir: Path | None = None


@dataclass(frozen=True)
class SearchHit:
    source: str
    kind: str
    scope: str
    title: str
    path: str
    snippet: str
    score: int

    def to_dict(self) -> dict[str, object]:
        return {
            "source": self.source,
            "kind": self.kind,
            "scope": self.scope,
            "title": self.title,
            "path": self.path,
            "snippet": self.snippet,
        }


def _tokens(text: str) -> list[str]:
    return [tok for tok in text.lower().split() if tok]


def _clean_line(line: str) -> str:
    collapsed = " ".join(line.strip().split())
    if len(collapsed) <= _SNIPPET_MAX:
        return collapsed
    return collapsed[: _SNIPPET_MAX - 1].rstrip() + "…"


def _best_snippet(lines: Sequence[str], tokens: list[str], fallback: str) -> str:
    best_line = ""
    best_hits = -1
    for raw in lines:
        cleaned = _clean_line(raw)
        if not cleaned:
            continue
        lower = cleaned.lower()
        hits = sum(1 for tok in tokens if tok in lower)
        if hits > best_hits:
            best_hits = hits
            best_line = cleaned
    return best_line or _clean_line(fallback)


def _score_text(phrase: str, tokens: list[str], title: str, extra: str) -> int:
    title_low = title.lower()
    extra_low = extra.lower()
    combined = f"{title_low}\n{extra_low}"
    if not all(tok in combined for tok in tokens):
        return 0
    score = 10 if phrase in title_low else 0
    score += 5 * sum(1 for tok in tokens if tok in title_low)
    score += 2 if phrase in extra_low else 0
    score += sum(1 for tok in tokens if tok in extra_low)
    return score


def _note_hit(note: BrainNote, phrase: str, tokens: list[str]) -> SearchHit | None:
    meta_bits = " ".join((*note.tags, *note.repos, note.source, note.slug))
    searchable = f"{meta_bits}\n{note.body}"
    score = _score_text(phrase, tokens, note.title, searchable)
    if score == 0:
        return None
    snippet = _best_snippet(note.body.splitlines(), tokens, meta_bits or note.title)
    return SearchHit(
        source="brain",
        kind=note.kind,
        scope=note.scope,
        title=note.title,
        path=str(note.path or ""),
        snippet=snippet,
        score=score,
    )


def _search_brain(
    store: BrainStore, query: SearchQuery, phrase: str, tokens: list[str]
) -> list[SearchHit]:
    if query.kind and query.kind not in VALID_KINDS:
        return []
    flt = NoteFilter(kind=query.kind, scope=query.scope)
    hits: list[SearchHit] = []
    for note in store.list(flt):
        hit = _note_hit(note, phrase, tokens)
        if hit is not None:
            hits.append(hit)
    return hits


def _task_lines(task: Task) -> list[str]:
    lines: list[str] = []
    if task.summary:
        lines.append(task.summary)
    lines.extend(str(f.get("text", "")) for f in task.facts)
    lines.extend(
        f"{d.get('text', '')} ({d.get('why', '')})" if d.get("why") else str(d.get("text", ""))
        for d in task.decisions
    )
    lines.extend(f"{link.get('title', '')}: {link.get('url', '')}" for link in task.links)
    lines.extend(
        f"{r.get('kind', '')}: {r.get('value', '')} {r.get('url', '')}".strip()
        for r in task.references
    )
    return [scrub(line) for line in lines if line.strip()]


def _task_scope(task: Task, brain_dir: Path) -> str:
    for entry in task.repos:
        raw_path = str(entry.get("path", ""))
        if not raw_path:
            continue
        inferred = infer_scope(Path(raw_path), root=brain_dir)
        if inferred != DEFAULT_SCOPE:
            return inferred
    return DEFAULT_SCOPE


def _resolve_task_store(sources: SearchSources) -> TaskStore | None:
    if sources.task_store is not None:
        return sources.task_store
    tasks_dir = state_dir() / "taskflow" / "tasks"
    return TaskStore() if tasks_dir.is_dir() else None


def _search_tasks(
    sources: SearchSources, query: SearchQuery, phrase: str, tokens: list[str]
) -> list[SearchHit]:
    if query.kind and query.kind != "task":
        return []
    t_store = _resolve_task_store(sources)
    if t_store is None:
        return []
    b_root = sources.brain_store.root if sources.brain_store else BrainStore().root
    hits: list[SearchHit] = []
    for task in t_store.list(include_closed=True):
        scope = _task_scope(task, b_root)
        if query.scope and scope != query.scope:
            continue
        lines = _task_lines(task)
        title = f"{task.id}: {task.title} [{task.status}]"
        score = _score_text(phrase, tokens, title, "\n".join(lines))
        if score == 0:
            continue
        hits.append(
            SearchHit(
                source="taskflow",
                kind="task",
                scope=scope,
                title=title,
                path=str(t_store.task_dir(task.id) / "state.json"),
                snippet=_best_snippet(lines, tokens, task.title),
                score=score,
            )
        )
    return hits


def _rule_title(body: str, fallback: str) -> str:
    for raw in body.splitlines():
        line = raw.strip()
        if line.startswith("#"):
            return line.lstrip("#").strip() or fallback
    return fallback


def _corporate_rule_entries(root: Path, scope: str | None) -> list[tuple[str, Path]]:
    if not scope:
        return []
    selected = corporate.selected_names()
    if selected is not None and scope not in selected:
        return []
    if scope not in corporate.available(root):
        return []
    return [(scope, path) for path in corporate.rule_paths(root, scope)]


def _iter_rule_entries(sources: SearchSources, scope: str | None) -> list[tuple[str, Path]]:
    if not scope or scope == DEFAULT_SCOPE:
        return []
    c_root = (
        sources.corporate_dir if sources.corporate_dir is not None else corporate.corporate_root()
    )
    return _corporate_rule_entries(c_root, scope)


def _search_rules(
    sources: SearchSources, query: SearchQuery, phrase: str, tokens: list[str]
) -> list[SearchHit]:
    if query.kind and query.kind != "rule":
        return []
    hits: list[SearchHit] = []
    for scope, path in _iter_rule_entries(sources, query.scope):
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError:
            continue
        body = _FRONTMATTER_RE.sub("", raw).strip()
        title = _rule_title(body, path.stem)
        score = _score_text(phrase, tokens, title, body)
        if score == 0:
            continue
        hits.append(
            SearchHit(
                source="rule",
                kind="rule",
                scope=scope,
                title=title,
                path=str(path.resolve()),
                snippet=_best_snippet(body.splitlines(), tokens, title),
                score=score,
            )
        )
    return hits


def search(query: SearchQuery, sources: SearchSources | None = None) -> list[SearchHit]:
    """Search brain notes, taskflow tasks, and corporate rules in the requested scope."""
    if query.kind and query.kind not in SEARCH_KINDS:
        valid = ", ".join(SEARCH_KINDS)
        raise ValueError(f"Invalid search kind {query.kind!r}: expected one of {valid}")
    if query.limit < 1:
        raise ValueError(f"limit must be >= 1, got {query.limit}")
    tokens = _tokens(query.text)
    if not tokens:
        raise ValueError("Search query cannot be empty.")
    phrase = " ".join(tokens)
    src = sources or SearchSources()
    b_store = src.brain_store or BrainStore()
    hits = [
        *_search_brain(b_store, query, phrase, tokens),
        *_search_tasks(src, query, phrase, tokens),
        *_search_rules(src, query, phrase, tokens),
    ]
    hits.sort(key=lambda h: (-h.score, h.source, h.title.lower(), h.path))
    return hits[: query.limit]
