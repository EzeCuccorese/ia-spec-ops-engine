"""Taskflow-to-brain archiving and curated, deduplicated import from Claude/Codex memory."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from pathlib import Path

from ..taskflow.handoff import scrub
from ..taskflow.models import Task
from ..taskflow.store import TaskStore
from .store import (
    DEFAULT_SCOPE,
    BrainNote,
    BrainStore,
    NoteFilter,
    has_secret,
    infer_repo,
    infer_scope,
    parse_note,
    slugify,
    today_iso,
    validate_scope,
)

IMPORT_SOURCES: tuple[str, ...] = ("claude", "codex")
_CLAUDE_TYPE_MAP: dict[str, str] = {
    "feedback": "gotcha",
    "reference": "reference",
    "project": "decision",
    "user": "howto",
}
_FRONTMATTER_RE = re.compile(r"^---\r?\n(.*?)\r?\n---(?:\r?\n|$)", re.DOTALL)
_HEADING_H2_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)


@dataclass(frozen=True)
class ArchiveOptions:
    brain_store: BrainStore | None = None
    task_store: TaskStore | None = None
    scope: str | None = None
    dry_run: bool = False


@dataclass(frozen=True)
class ArchiveResult:
    task_id: str
    action: str  # "created" | "updated" | "unchanged" | "would-create" | "would-update"
    note: BrainNote


@dataclass(frozen=True)
class ImportCandidate:
    slug: str
    title: str
    kind: str
    body: str
    source: str
    origin_path: str
    duplicates: int = 0
    status: str = "new"  # "new" | "duplicate" | "secret"

    def to_dict(self) -> dict[str, object]:
        return {
            "slug": self.slug,
            "title": self.title,
            "kind": self.kind,
            "source": self.source,
            "origin_path": self.origin_path,
            "duplicates": self.duplicates,
            "status": self.status,
        }


@dataclass(frozen=True)
class ImportOptions:
    source: str
    scope: str = DEFAULT_SCOPE
    source_dir: Path | None = None
    select: tuple[str, ...] = ()
    apply: bool = False


@dataclass(frozen=True)
class ImportReport:
    source: str
    applied: bool
    candidates: tuple[ImportCandidate, ...]
    imported: tuple[BrainNote, ...] = ()


# -- task archiving ------------------------------------------------------------------------


def _task_repos(task: Task) -> tuple[str, ...]:
    names: list[str] = []
    for entry in task.repos:
        raw = str(entry.get("path", "")).strip()
        if not raw:
            continue
        path = Path(raw).expanduser()
        name = (infer_repo(path) if path.exists() else None) or path.name
        if name and name not in names:
            names.append(name)
    return tuple(names)


def _task_scope(task: Task, explicit: str | None, brain_root: Path) -> str:
    if explicit:
        return validate_scope(explicit)
    for entry in task.repos:
        raw = str(entry.get("path", "")).strip()
        if not raw:
            continue
        inferred = infer_scope(Path(raw).expanduser(), root=brain_root)
        if inferred != DEFAULT_SCOPE:
            return inferred
    return DEFAULT_SCOPE


def _append_section(lines: list[str], heading: str, items: list[str]) -> None:
    if not items:
        return
    lines.extend(["", f"## {heading}", *items])


def _render_archive_body(task: Task) -> str:
    lines = [
        f"# {task.id}: {task.title}",
        "",
        f"Status: {task.status} · workflow: {task.workflow} · updated: {task.updated_at[:10]}",
    ]
    if task.summary:
        lines.extend(["", "## Summary", task.summary.strip()])
    decisions = [
        f"- {d['text']} — {d['why']}" if d.get("why") else f"- {d['text']}" for d in task.decisions
    ]
    facts = [f"- {f['text']}" for f in task.facts]
    links = [
        *[f"- [{item.get('title', 'link')}]({item.get('url', '')})" for item in task.links],
        *[
            f"- {r.get('kind', 'ref')}: {r.get('value', '')}"
            + (f" ({r['url']})" if r.get("url") else "")
            for r in task.references
        ],
    ]
    repos = [
        f"- `{r.get('path', '?')}` (branch: `{r.get('branch', '?')}`"
        + (f", PR: {r['pr']}" if r.get("pr") else "")
        + ")"
        for r in task.repos
    ]
    _append_section(lines, "Decisions", decisions)
    _append_section(lines, "Facts", facts)
    _append_section(lines, "Links", links)
    _append_section(lines, "Repositories", repos)
    return scrub("\n".join(lines)).strip()


def _same_content(existing: BrainNote, proposed: BrainNote) -> bool:
    return (
        existing.title == proposed.title
        and existing.kind == proposed.kind
        and existing.tags == proposed.tags
        and existing.repos == proposed.repos
        and existing.source == proposed.source
        and existing.body.strip() == proposed.body.strip()
    )


def _existing_archive(store: BrainStore, scope: str, slug: str) -> BrainNote | None:
    path = store.note_path(scope, slug)
    if not path.is_file():
        return None
    return parse_note(path.read_text(encoding="utf-8"), slug=slug, scope=scope, path=path)


def _build_archive_note(
    task: Task, scope: str, store: BrainStore, existing: BrainNote | None
) -> BrainNote:
    slug = slugify(f"archive-{task.id}")
    created = existing.created if existing else (task.created_at[:10] or today_iso())
    return BrainNote(
        slug=slug,
        title=scrub(f"{task.id}: {task.title}"),
        kind="archive",
        scope=scope,
        body=_render_archive_body(task),
        tags=("archive", "taskflow"),
        repos=tuple(scrub(r) for r in _task_repos(task)),
        source=scrub(task.id),
        created=created,
        updated=today_iso(),
        path=store.note_path(scope, slug),
    )


def archive_task(task_id: str, options: ArchiveOptions | None = None) -> ArchiveResult:
    """Write or update an idempotent archive note in the brain for ``task_id``."""
    opts = options or ArchiveOptions()
    b_store = opts.brain_store or BrainStore()
    t_store = opts.task_store or TaskStore()
    task = t_store.get(task_id)
    chosen_scope = _task_scope(task, opts.scope, b_store.root)
    existing = _existing_archive(b_store, chosen_scope, slugify(f"archive-{task.id}"))
    proposed = _build_archive_note(task, chosen_scope, b_store, existing)
    if existing and _same_content(existing, proposed):
        return ArchiveResult(task.id, "unchanged", existing)
    if opts.dry_run:
        return ArchiveResult(task.id, "would-update" if existing else "would-create", proposed)
    saved = b_store.save(proposed)
    return ArchiveResult(task.id, "updated" if existing else "created", saved)


def archive_closed_tasks(options: ArchiveOptions | None = None) -> list[ArchiveResult]:
    """Archive every closed taskflow task (idempotent)."""
    opts = options or ArchiveOptions()
    t_store = opts.task_store or TaskStore()
    b_store = opts.brain_store or BrainStore()
    shared = ArchiveOptions(
        brain_store=b_store, task_store=t_store, scope=opts.scope, dry_run=opts.dry_run
    )
    closed = [t for t in t_store.list(include_closed=True) if t.status == "closed"]
    return [archive_task(t.id, shared) for t in closed]


# -- curated memory import (Claude / Codex) ------------------------------------------------


@dataclass(frozen=True)
class _RawEntry:
    slug: str
    title: str
    kind: str
    body: str
    source: str
    origin_path: str
    mtime: float


def _parse_kv_header(block: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in block.splitlines():
        if ":" not in line:
            continue
        key, val = line.split(":", 1)
        result[key.strip().lower()] = val.strip().strip("\"'")
    return result


def _read_claude_entry(path: Path) -> _RawEntry | None:
    try:
        raw = path.read_text(encoding="utf-8")
        mtime = path.stat().st_mtime
    except OSError:
        return None
    match = _FRONTMATTER_RE.match(raw)
    header = _parse_kv_header(match.group(1)) if match else {}
    body = raw[match.end() :].strip() if match else raw.strip()
    if not body:
        return None
    title = (
        header.get("name") or header.get("title") or path.stem.replace("_", " ").replace("-", " ")
    )
    kind = _CLAUDE_TYPE_MAP.get(header.get("type", "").lower(), "reference")
    return _RawEntry(
        slug=slugify(title or path.stem),
        title=title.strip(),
        kind=kind,
        body=body,
        source=f"claude:{path.parent.parent.name}/{path.name}",
        origin_path=str(path),
        mtime=mtime,
    )


def _discover_claude(source_dir: Path | None) -> list[_RawEntry]:
    root = source_dir if source_dir is not None else Path.home() / ".claude" / "projects"
    if not root.is_dir():
        return []
    entries: list[_RawEntry] = []
    for path in sorted(root.glob("*/memory/*.md")):
        if not path.is_file() or path.name.lower() == "memory.md":
            continue
        entry = _read_claude_entry(path)
        if entry is not None:
            entries.append(entry)
    return entries


def _split_codex_memory_md(path: Path) -> list[_RawEntry]:
    try:
        text = path.read_text(encoding="utf-8")
        mtime = path.stat().st_mtime
    except OSError:
        return []
    matches = list(_HEADING_H2_RE.finditer(text))
    entries: list[_RawEntry] = []
    for idx, match in enumerate(matches):
        title = match.group(1).strip()
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        if not title or not body:
            continue
        entries.append(
            _RawEntry(
                slug=slugify(title),
                title=title,
                kind="reference",
                body=body,
                source=f"codex:{path.name}",
                origin_path=str(path),
                mtime=mtime,
            )
        )
    return entries


def _discover_codex(source_dir: Path | None) -> list[_RawEntry]:
    root = source_dir if source_dir is not None else Path.home() / ".codex" / "memories"
    if not root.is_dir():
        return []
    entries: list[_RawEntry] = []
    memory_file = root / "MEMORY.md"
    if memory_file.is_file():
        entries.extend(_split_codex_memory_md(memory_file))
    for path in sorted(root.glob("*.md")):
        if not path.is_file() or path.name.lower() == "memory.md":
            continue
        entry = _read_claude_entry(path)
        if entry is not None:
            entries.append(replace(entry, source=f"codex:{path.name}"))
    return entries


def _dedup_entries(
    entries: list[_RawEntry], existing_slugs: set[str], existing_titles: set[str]
) -> list[ImportCandidate]:
    grouped: dict[str, list[_RawEntry]] = {}
    for entry in entries:
        grouped.setdefault(entry.slug, []).append(entry)
    candidates: list[ImportCandidate] = []
    for slug in sorted(grouped):
        group = grouped[slug]
        winner = max(group, key=lambda item: (item.mtime, len(item.body)))
        if has_secret(winner.title) or has_secret(winner.body):
            status = "secret"
        elif slug in existing_slugs or winner.title.lower() in existing_titles:
            status = "duplicate"
        else:
            status = "new"
            existing_slugs.add(slug)
            existing_titles.add(winner.title.lower())
        candidates.append(
            ImportCandidate(
                slug=slug,
                title=winner.title,
                kind=winner.kind,
                body=winner.body,
                source=winner.source,
                origin_path=winner.origin_path,
                duplicates=len(group) - 1,
                status=status,
            )
        )
    return candidates


def _write_imported(
    store: BrainStore, candidates: list[ImportCandidate], scope: str, source: str
) -> tuple[BrainNote, ...]:
    stamp = today_iso()
    imported: list[BrainNote] = []
    for cand in candidates:
        if cand.status != "new":
            continue
        note = BrainNote(
            slug=cand.slug,
            title=cand.title,
            kind=cand.kind,
            scope=scope,
            body=cand.body,
            tags=("imported", source),
            source=cand.source,
            created=stamp,
            updated=stamp,
        )
        imported.append(store.save(note))
    return tuple(imported)


def import_memories(options: ImportOptions, brain_store: BrainStore | None = None) -> ImportReport:
    """Discover, deduplicate, and optionally import Claude or Codex memory notes."""
    if options.source not in IMPORT_SOURCES:
        valid = ", ".join(IMPORT_SOURCES)
        raise ValueError(f"Unsupported import source {options.source!r}: expected one of {valid}")
    scope = validate_scope(options.scope)
    store = brain_store or BrainStore()
    existing = store.list(NoteFilter(scope=scope))
    raw = (
        _discover_claude(options.source_dir)
        if options.source == "claude"
        else _discover_codex(options.source_dir)
    )
    candidates = _dedup_entries(
        raw, {n.slug for n in existing}, {n.title.lower() for n in existing}
    )
    if options.select:
        candidates = [c for c in candidates if c.slug in set(options.select)]
    if not options.apply:
        return ImportReport(options.source, applied=False, candidates=tuple(candidates))
    imported = _write_imported(store, candidates, scope, options.source)
    return ImportReport(
        options.source, applied=True, candidates=tuple(candidates), imported=imported
    )
