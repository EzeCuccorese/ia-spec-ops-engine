"""``ai-governance brain``: cross-agent second brain notes, search, archive and import."""

from __future__ import annotations

import argparse
import hashlib
import os
import shlex
import subprocess
import sys
import tempfile
from dataclasses import replace
from pathlib import Path

from ..output import emit_json, emit_kv, emit_rows, emit_status, emit_text
from .archive import (
    IMPORT_SOURCES,
    ArchiveOptions,
    ArchiveResult,
    ImportOptions,
    ImportReport,
    archive_closed_tasks,
    archive_task,
    import_memories,
)
from .search import DEFAULT_LIMIT, SEARCH_KINDS, SearchQuery, search
from .store import (
    _FRONTMATTER_RE,
    DEFAULT_STALE_DAYS,
    VALID_KINDS,
    BrainNote,
    BrainStore,
    NoteDraft,
    NoteFilter,
    SecretContentError,
    check_no_secrets,
    infer_repo,
    infer_scope,
    parse_note,
    today_iso,
    validate_kind,
)


def _split_multi(values: list[str] | None) -> tuple[str, ...]:
    items: list[str] = []
    for raw in values or ():
        for part in raw.split(","):
            cleaned = part.strip()
            if cleaned and cleaned not in items:
                items.append(cleaned)
    return tuple(items)


def _resolve_repos(args: argparse.Namespace) -> tuple[str, ...]:
    if getattr(args, "no_repo", False):
        return ()
    explicit = _split_multi(args.repo)
    if explicit:
        return explicit
    inferred = infer_repo(Path.cwd())
    return (inferred,) if inferred else ()


def cmd_add(args: argparse.Namespace) -> int:
    store = BrainStore()
    scope = args.scope or infer_scope(Path.cwd(), root=store.root)
    draft = NoteDraft(
        body=args.text,
        title=args.title or "",
        kind=args.kind,
        scope=scope,
        tags=_split_multi(args.tag),
        repos=_resolve_repos(args),
        source=args.source or "",
        slug=args.slug or "",
    )
    note = store.add(draft)
    if args.json:
        emit_json(note.to_dict())
        return 0
    emit_status("ok", f"Saved {note.ref} ({note.path})")
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    query = SearchQuery(
        text=args.query,
        kind=args.kind,
        scope=args.scope,
        limit=args.limit,
    )
    hits = search(query)
    if args.json:
        emit_json([h.to_dict() for h in hits])
        return 0
    if not hits:
        emit_status("info", f"No matches for '{args.query}'")
        return 0
    emit_rows(
        [(f"{h.source}:{h.kind}", h.title, h.path, h.snippet) for h in hits],
        headers=("Type", "Title", "Path", "Match"),
        title=f"Brain search: {args.query}",
        more_hint="ai-governance brain search --limit 50",
    )
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    note = BrainStore().get(args.slug, scope=args.scope)
    if args.json:
        emit_json(note.to_dict())
        return 0
    pairs = [
        ("Ref", note.ref),
        ("Kind", note.kind),
        ("Tags", ", ".join(note.tags) or "-"),
        ("Repos", ", ".join(note.repos) or "-"),
        ("Source", note.source or "-"),
        ("Updated", f"{note.updated} (created {note.created})"),
        ("Path", str(note.path or "")),
    ]
    emit_kv(pairs, title=note.title, full=True)
    if note.body:
        emit_text(note.body, full=True)
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    stale_days = args.stale_days if args.stale else None
    flt = NoteFilter(
        kind=args.kind,
        scope=args.scope,
        repo=args.repo,
        stale_days=stale_days,
    )
    notes = BrainStore().list(flt)
    if args.json:
        emit_json([n.to_dict() for n in notes])
        return 0
    if not notes:
        emit_status("info", "No brain notes found.")
        return 0
    emit_rows(
        [(n.ref, n.kind, n.updated, ", ".join(n.repos) or "-", n.title) for n in notes],
        headers=("Ref", "Kind", "Updated", "Repos", "Title"),
        title="Brain notes",
        more_hint="ai-governance brain list --json",
    )
    return 0


def _editor_cmd(explicit: str | None) -> list[str]:
    raw = explicit or os.environ.get("VISUAL") or os.environ.get("EDITOR") or "vi"
    parts = shlex.split(raw)
    if not parts:
        raise ValueError("Editor command cannot be empty.")
    return parts


def _edit_in_temp(before: str, slug: str, editor: list[str]) -> tuple[int, str]:
    fd, raw_temp = tempfile.mkstemp(prefix=f"brain-edit-{slug}-", suffix=".md")
    temp_path = Path(raw_temp)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            os.chmod(temp_path, 0o600)
            handle.write(before)
        proc = subprocess.run([*editor, str(temp_path)], check=False)
        after = temp_path.read_text(encoding="utf-8") if proc.returncode == 0 else ""
        return proc.returncode, after
    finally:
        temp_path.unlink(missing_ok=True)


def _validate_edited_note(after: str, note: BrainNote, path: Path) -> BrainNote:
    if after.startswith("---") and not _FRONTMATTER_RE.match(after):
        raise ValueError("Invalid frontmatter: missing closing '---' delimiter.")
    edited = parse_note(after, slug=note.slug, scope=note.scope, path=path)
    if not edited.body.strip():
        raise ValueError("Note text cannot be empty.")
    validate_kind(edited.kind)
    check_no_secrets(edited.title, edited.body, edited.source, *edited.tags, *edited.repos)
    return replace(edited, scope=note.scope, slug=note.slug, path=path, updated=today_iso())


def cmd_edit(args: argparse.Namespace) -> int:
    store = BrainStore()
    note = store.get(args.slug, scope=args.scope)
    path = note.path or store.note_path(note.scope, note.slug)
    before = path.read_text(encoding="utf-8")
    before_digest = hashlib.sha256(before.encode("utf-8")).hexdigest()
    returncode, after = _edit_in_temp(before, note.slug, _editor_cmd(args.editor))
    if returncode != 0:
        emit_status("error", f"Editor exited with code {returncode}")
        return 1
    if after != before:
        validated = _validate_edited_note(after, note, path)
        current = path.read_text(encoding="utf-8")
        if hashlib.sha256(current.encode("utf-8")).hexdigest() != before_digest:
            raise ValueError(
                f"Note '{note.ref}' changed on disk while editing; aborting without overwriting."
            )
        store.save(validated, reject_secrets=False)
    emit_status("ok", f"Edited {note.ref} ({path})")
    return 0


def _emit_archive_results(results: list[ArchiveResult], as_json: bool) -> int:
    if as_json:
        emit_json(
            [
                {
                    "task_id": r.task_id,
                    "action": r.action,
                    "ref": r.note.ref,
                    "path": str(r.note.path),
                }
                for r in results
            ]
        )
        return 0
    if not results:
        emit_status("info", "No closed tasks to archive.")
        return 0
    if len(results) == 1:
        res = results[0]
        emit_status("ok", f"{res.action}: {res.note.ref} ({res.note.path})")
        return 0
    emit_rows(
        [(r.task_id, r.action, r.note.ref, str(r.note.path)) for r in results],
        headers=("Task", "Action", "Ref", "Path"),
        title="Brain archive",
        full=True,
    )
    return 0


def cmd_archive(args: argparse.Namespace) -> int:
    if not args.task_id and not args.all_closed:
        raise ValueError("Provide a task id or pass --all-closed.")
    opts = ArchiveOptions(scope=args.scope, dry_run=args.dry_run)
    results = archive_closed_tasks(opts) if args.all_closed else [archive_task(args.task_id, opts)]
    return _emit_archive_results(results, args.json)


def _emit_import_report(report: ImportReport, scope: str, as_json: bool) -> int:
    if as_json:
        emit_json(
            {
                "source": report.source,
                "applied": report.applied,
                "imported": [n.ref for n in report.imported],
                "candidates": [c.to_dict() for c in report.candidates],
            }
        )
        return 0
    if not report.candidates:
        emit_status("info", f"No candidate notes found for '{report.source}'.")
        return 0
    emit_rows(
        [(c.slug, c.kind, c.status, str(c.duplicates), c.title) for c in report.candidates],
        headers=("Slug", "Kind", "Status", "Dups", "Title"),
        title=f"Import from {report.source} ({'applied' if report.applied else 'dry-run'})",
        full=True,
    )
    if report.applied:
        emit_status("ok", f"Imported {len(report.imported)} note(s) into scope '{scope}'.")
    else:
        new_count = sum(1 for c in report.candidates if c.status == "new")
        emit_status(
            "info",
            f"Dry-run: {new_count} new candidate(s). Re-run with --apply (or --apply --select <slug,...>).",
        )
    return 0


def cmd_import(args: argparse.Namespace) -> int:
    if args.dry_run and args.apply:
        raise ValueError("Cannot combine --dry-run and --apply.")
    scope = args.scope or infer_scope(Path.cwd())
    opts = ImportOptions(
        source=args.source,
        scope=scope,
        source_dir=args.source_dir,
        select=_split_multi(args.select),
        apply=args.apply,
    )
    return _emit_import_report(import_memories(opts), scope, args.json)


# -- parser --------------------------------------------------------------------------------


def _add_note_commands(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    add_p = sub.add_parser("add", help="Capture a new note (rejects secret-like content)")
    add_p.add_argument("text", help="Note body text")
    add_p.add_argument("--title", help="Explicit note title (defaults to first line)")
    add_p.add_argument("--kind", choices=VALID_KINDS, default="gotcha", help="Note kind")
    add_p.add_argument("--tag", action="append", help="Tag (repeatable or comma-separated)")
    add_p.add_argument("--scope", help="Namespace scope (defaults from current repo)")
    add_p.add_argument("--repo", action="append", help="Repository tag (defaults to current repo)")
    add_p.add_argument(
        "--no-repo", action="store_true", help="Do not attach the current repository"
    )
    add_p.add_argument("--source", help="Origin reference (task id, PR, session)")
    add_p.add_argument("--slug", help="Explicit note slug")
    add_p.add_argument("--json", action="store_true", help="Emit JSON output")
    add_p.set_defaults(handler=cmd_add)

    search_p = sub.add_parser("search", help="Search brain notes, taskflow tasks, and rules")
    search_p.add_argument("query", help="Plain-text search query")
    search_p.add_argument("--kind", choices=SEARCH_KINDS, help="Filter by kind, 'task', or 'rule'")
    search_p.add_argument("--scope", help="Filter by namespace scope")
    search_p.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help="Max results to show")
    search_p.add_argument("--json", action="store_true", help="Emit JSON output")
    search_p.set_defaults(handler=cmd_search)

    show_p = sub.add_parser("show", help="Show a note by slug or <scope>/<slug>")
    show_p.add_argument("slug", help="Note slug or <scope>/<slug>")
    show_p.add_argument("--scope", help="Explicit scope namespace")
    show_p.add_argument("--json", action="store_true", help="Emit JSON output")
    show_p.set_defaults(handler=cmd_show)

    list_p = sub.add_parser("list", help="List brain notes with optional filters")
    list_p.add_argument("--kind", choices=VALID_KINDS, help="Filter by note kind")
    list_p.add_argument("--scope", help="Filter by namespace scope")
    list_p.add_argument("--repo", help="Filter by repository name")
    list_p.add_argument("--stale", action="store_true", help="Show only stale notes")
    list_p.add_argument(
        "--stale-days",
        type=int,
        default=DEFAULT_STALE_DAYS,
        help=f"Days before a note counts as stale (default {DEFAULT_STALE_DAYS})",
    )
    list_p.add_argument("--json", action="store_true", help="Emit JSON output")
    list_p.set_defaults(handler=cmd_list)


def _add_lifecycle_commands(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    edit_p = sub.add_parser("edit", help="Open an existing note in $VISUAL / $EDITOR")
    edit_p.add_argument("slug", help="Note slug or <scope>/<slug>")
    edit_p.add_argument("--scope", help="Explicit scope namespace")
    edit_p.add_argument("--editor", help="Override editor command")
    edit_p.set_defaults(handler=cmd_edit)

    arch_p = sub.add_parser("archive", help="Write an idempotent archive note from a taskflow task")
    arch_p.add_argument("task_id", nargs="?", help="Taskflow task id")
    arch_p.add_argument("--all-closed", action="store_true", help="Archive every closed task")
    arch_p.add_argument("--scope", help="Override destination scope")
    arch_p.add_argument("--dry-run", action="store_true", help="Preview without writing files")
    arch_p.add_argument("--json", action="store_true", help="Emit JSON output")
    arch_p.set_defaults(handler=cmd_archive)

    imp_p = sub.add_parser(
        "import", help="Curated, deduplicated import from Claude or Codex memory"
    )
    imp_p.add_argument(
        "--from", dest="source", required=True, choices=IMPORT_SOURCES, help="Memory source"
    )
    imp_p.add_argument("--dry-run", action="store_true", help="Preview candidates only (default)")
    imp_p.add_argument(
        "--apply", action="store_true", help="Write selected new candidates to brain"
    )
    imp_p.add_argument("--select", action="append", help="Candidate slug(s) to include")
    imp_p.add_argument("--scope", help="Destination namespace scope")
    imp_p.add_argument("--source-dir", type=Path, help="Override source memory directory")
    imp_p.add_argument("--json", action="store_true", help="Emit JSON output")
    imp_p.set_defaults(handler=cmd_import)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ai-governance brain",
        description="Cross-agent second brain notes (PARA Resources & Archive).",
    )
    sub = parser.add_subparsers(dest="action")
    _add_note_commands(sub)
    _add_lifecycle_commands(sub)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handler = getattr(args, "handler", None)
    if handler is None:
        parser.print_help()
        return 0
    try:
        return int(handler(args))
    except (SecretContentError, ValueError, OSError) as exc:
        emit_status("error", str(exc))
        return 1


if __name__ == "__main__":
    sys.exit(main())
