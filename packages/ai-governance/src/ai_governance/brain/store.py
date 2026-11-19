"""Plain-Markdown second brain store under ``$AI_GOVERNANCE_BRAIN_DIR`` or ``data_dir()/brain``.

Notes are partitioned into top-level namespaces (``personal/`` and ``<company>/``) so every
agent and worktree reads the same files while keeping company knowledge isolated.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from ..corporate import available as corporate_packs
from ..paths import data_dir
from ..taskflow.handoff import scrub
from ..taskflow.store import atomic_write_text

VALID_KINDS: tuple[str, ...] = ("gotcha", "reference", "decision", "howto", "archive")
DEFAULT_SCOPE = "personal"
DEFAULT_STALE_DAYS = 90

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,79}$")
_SCOPE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_PLAIN_SCALAR_RE = re.compile(r"^[A-Za-z0-9._/@ -]+$")
_YAML_KEYWORDS = frozenset({"true", "false", "null", "yes", "no", "on", "off", "~"})
_FRONTMATTER_RE = re.compile(r"^---\r?\n(.*?)\r?\n---(?:\r?\n|$)", re.DOTALL)


class SecretContentError(ValueError):
    """Raised when a note draft contains content that looks like a secret or credential."""


@dataclass(frozen=True)
class BrainNote:
    slug: str
    title: str
    kind: str
    scope: str
    body: str
    tags: tuple[str, ...] = ()
    repos: tuple[str, ...] = ()
    source: str = ""
    created: str = ""
    updated: str = ""
    path: Path | None = None

    @property
    def ref(self) -> str:
        return f"{self.scope}/{self.slug}"

    def to_dict(self) -> dict[str, object]:
        return {
            "ref": self.ref,
            "slug": self.slug,
            "title": self.title,
            "kind": self.kind,
            "scope": self.scope,
            "tags": list(self.tags),
            "repos": list(self.repos),
            "source": self.source,
            "created": self.created,
            "updated": self.updated,
            "path": str(self.path) if self.path else "",
            "body": self.body,
        }


@dataclass(frozen=True)
class NoteDraft:
    body: str
    title: str = ""
    kind: str = "gotcha"
    scope: str = DEFAULT_SCOPE
    tags: tuple[str, ...] = ()
    repos: tuple[str, ...] = ()
    source: str = ""
    slug: str = ""


@dataclass(frozen=True)
class NoteFilter:
    kind: str | None = None
    scope: str | None = None
    repo: str | None = None
    stale_days: int | None = None
    today: date | None = None


def brain_root() -> Path:
    """Storage root: ``$AI_GOVERNANCE_BRAIN_DIR``, else ``data_dir() / 'brain'``."""
    explicit = os.environ.get("AI_GOVERNANCE_BRAIN_DIR")
    if explicit:
        return Path(explicit).expanduser()
    return data_dir() / "brain"


def today_iso() -> str:
    return datetime.now(UTC).date().isoformat()


def validate_kind(kind: str) -> str:
    if kind not in VALID_KINDS:
        valid = ", ".join(VALID_KINDS)
        raise ValueError(f"Invalid note kind {kind!r}: expected one of {valid}")
    return kind


def validate_scope(scope: str) -> str:
    if not isinstance(scope, str) or not _SCOPE_RE.fullmatch(scope) or ".." in scope:
        raise ValueError(f"Invalid scope {scope!r}: use letters, digits, '-' or '_'")
    return scope


def validate_slug(slug: str) -> str:
    if not isinstance(slug, str) or not _SLUG_RE.fullmatch(slug) or ".." in slug:
        raise ValueError(f"Invalid note slug {slug!r}: use lowercase letters, digits, '-' or '_'")
    return slug


def slugify(text: str, max_len: int = 60) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    slug = cleaned[:max_len].strip("-")
    return slug or "note"


def parse_ref(ref: str) -> tuple[str | None, str]:
    """Parse ``<slug>`` or ``<scope>/<slug>`` into ``(scope, slug)``."""
    if "/" not in ref:
        return None, validate_slug(ref)
    parts = ref.split("/")
    if len(parts) != 2:
        raise ValueError(f"Invalid note reference {ref!r}: use '<slug>' or '<scope>/<slug>'")
    return validate_scope(parts[0]), validate_slug(parts[1])


def has_secret(text: str) -> bool:
    return bool(text) and scrub(text) != text


def check_no_secrets(*texts: str) -> None:
    if any(has_secret(text) for text in texts):
        raise SecretContentError(
            "Refusing to store note: content appears to contain a secret or credential."
        )


def derive_title(text: str) -> str:
    for raw_line in text.splitlines():
        line = raw_line.strip().lstrip("#").strip()
        if line:
            return line if len(line) <= 80 else line[:79].rstrip() + "…"
    return "Untitled note"


# -- git / scope inference -----------------------------------------------------------------


def _git_value(args: list[str], cwd: Path) -> str | None:
    try:
        proc = subprocess.run(
            ["git", *args], cwd=str(cwd), capture_output=True, text=True, timeout=2, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return proc.stdout.strip() or None if proc.returncode == 0 else None


def _git_common_dir(cwd: Path) -> Path | None:
    raw = _git_value(["rev-parse", "--git-common-dir"], cwd)
    if not raw:
        return None
    candidate = Path(raw)
    return candidate.resolve() if candidate.is_absolute() else (cwd / candidate).resolve()


def infer_repo(cwd: Path | None = None) -> str | None:
    """Canonical repository name, stable across linked git worktrees and subdirectories."""
    here = (cwd or Path.cwd()).resolve()
    common = _git_common_dir(here)
    if common is None:
        return None
    if common.name == ".git":
        return common.parent.name
    return common.name.removesuffix(".git") or None


def _company_candidates(root: Path) -> list[str]:
    names = set(corporate_packs())
    if root.is_dir():
        for entry in root.iterdir():
            if entry.is_dir() and entry.name != DEFAULT_SCOPE and not entry.name.startswith("."):
                names.add(entry.name)
    return sorted(names)


def _matches_company(company: str, path_parts: set[str], remote_url: str) -> bool:
    needle = company.lower()
    if needle in path_parts:
        return True
    if not remote_url:
        return False
    return bool(re.search(rf"(?:^|[:/._@-]){re.escape(needle)}(?:$|[:/._@-])", remote_url.lower()))


def infer_scope(cwd: Path | None = None, root: Path | None = None) -> str:
    """Default scope for ``cwd``: matching company namespace if detected, else ``personal``."""
    base = root if root is not None else brain_root()
    candidates = _company_candidates(base)
    if not candidates:
        return DEFAULT_SCOPE
    here = (cwd or Path.cwd()).resolve()
    parts = {part.lower() for part in here.parts}
    common = _git_common_dir(here)
    if common is not None:
        parts.update(part.lower() for part in common.parent.parts)
    remote = _git_value(["config", "--get", "remote.origin.url"], here) or ""
    for company in candidates:
        if _matches_company(company, parts, remote):
            return company
    return DEFAULT_SCOPE


# -- frontmatter serialization and parsing -------------------------------------------------


def _format_scalar(value: str) -> str:
    if (
        value
        and value == value.strip()
        and value.lower() not in _YAML_KEYWORDS
        and _PLAIN_SCALAR_RE.fullmatch(value)
    ):
        return value
    return json.dumps(value, ensure_ascii=False)


def _format_list(items: tuple[str, ...]) -> str:
    return "[" + ", ".join(_format_scalar(item) for item in items) + "]"


def serialize_note(note: BrainNote) -> str:
    lines = [
        "---",
        f"title: {_format_scalar(note.title)}",
        f"kind: {_format_scalar(note.kind)}",
        f"tags: {_format_list(note.tags)}",
        f"scope: {_format_scalar(note.scope)}",
        f"repos: {_format_list(note.repos)}",
        f"source: {_format_scalar(note.source)}",
        f"created: {_format_scalar(note.created)}",
        f"updated: {_format_scalar(note.updated)}",
        "---",
        "",
    ]
    body = note.body.strip()
    return "\n".join(lines) + (body + "\n" if body else "")


def _parse_scalar(raw: str) -> str:
    text = raw.strip()
    if not text:
        return ""
    if len(text) >= 2 and text[0] == '"' and text[-1] == '"':
        try:
            loaded = json.loads(text)
            return str(loaded)
        except ValueError:
            return text[1:-1]
    if len(text) >= 2 and text[0] == "'" and text[-1] == "'":
        return text[1:-1].replace("''", "'")
    return text


def _advance_quote(ch: str, quote: str | None, escaped: bool) -> tuple[str | None, bool]:
    if escaped:
        return quote, False
    if quote == '"' and ch == "\\":
        return quote, True
    if quote is not None:
        return (None if ch == quote else quote), False
    return (ch if ch in ('"', "'") else None), False


def _split_inline_list(inner: str) -> list[str]:
    items: list[str] = []
    buf: list[str] = []
    quote: str | None = None
    escaped = False
    for ch in inner:
        if quote is None and ch == ",":
            items.append(_parse_scalar("".join(buf)))
            buf = []
            continue
        quote, escaped = _advance_quote(ch, quote, escaped)
        buf.append(ch)
    if tail := "".join(buf).strip():
        items.append(_parse_scalar(tail))
    return [item for item in items if item]


def _append_block_item(raw_line: str, data: dict[str, object], list_key: str | None) -> bool:
    stripped = raw_line.strip()
    if not (list_key and raw_line.startswith((" ", "\t")) and stripped.startswith("- ")):
        return False
    items = data.setdefault(list_key, [])
    if isinstance(items, list):
        items.append(_parse_scalar(stripped[2:]))
    return True


def _apply_frontmatter_line(
    raw_line: str, data: dict[str, object], list_key: str | None
) -> str | None:
    stripped = raw_line.strip()
    if not stripped or stripped.startswith("#") or _append_block_item(raw_line, data, list_key):
        return list_key
    if ":" not in raw_line:
        return list_key
    key, raw_value = raw_line.split(":", 1)
    key, value = key.strip(), raw_value.strip()
    if not value:
        data[key] = []
        return key
    data[key] = (
        _split_inline_list(value[1:-1])
        if value.startswith("[") and value.endswith("]")
        else _parse_scalar(value)
    )
    return None


def _parse_frontmatter(block: str) -> dict[str, object]:
    data: dict[str, object] = {}
    list_key: str | None = None
    for raw_line in block.splitlines():
        list_key = _apply_frontmatter_line(raw_line, data, list_key)
    return data


def _meta_str(meta: dict[str, object], key: str) -> str:
    value = meta.get(key)
    return value.strip() if isinstance(value, str) else ""


def _as_tuple(raw: object) -> tuple[str, ...]:
    if isinstance(raw, list):
        return tuple(str(v).strip() for v in raw if str(v).strip())
    if isinstance(raw, str) and raw.strip():
        return (raw.strip(),)
    return ()


def _file_date(path: Path | None) -> str:
    if path is None or not path.exists():
        return today_iso()
    return datetime.fromtimestamp(path.stat().st_mtime, tz=UTC).date().isoformat()


def parse_note(text: str, *, slug: str, scope: str, path: Path | None = None) -> BrainNote:
    match = _FRONTMATTER_RE.match(text)
    meta = _parse_frontmatter(match.group(1)) if match else {}
    body = text[match.end() :].strip() if match else text.strip()
    fallback_date = _file_date(path)
    created = _meta_str(meta, "created") or fallback_date
    return BrainNote(
        slug=slug,
        title=_meta_str(meta, "title") or derive_title(body) or slug,
        kind=_meta_str(meta, "kind") or "reference",
        scope=_meta_str(meta, "scope") or scope,
        body=body,
        tags=_as_tuple(meta.get("tags")),
        repos=_as_tuple(meta.get("repos")),
        source=_meta_str(meta, "source"),
        created=created,
        updated=_meta_str(meta, "updated") or created,
        path=path,
    )


# -- staleness -----------------------------------------------------------------------------


def _note_date(note: BrainNote) -> date | None:
    for raw in (note.updated, note.created):
        if raw:
            try:
                return date.fromisoformat(raw[:10])
            except ValueError:
                continue
    return None


def is_stale(note: BrainNote, days: int = DEFAULT_STALE_DAYS, today: date | None = None) -> bool:
    if days < 1:
        raise ValueError(f"stale_days must be >= 1, got {days}")
    recorded = _note_date(note)
    if recorded is None:
        return False
    ref_day = today or datetime.now(UTC).date()
    return recorded < (ref_day - timedelta(days=days))


# -- store ---------------------------------------------------------------------------------


def _dedup_tuple(values: tuple[str, ...]) -> tuple[str, ...]:
    seen: list[str] = []
    for item in values:
        cleaned = item.strip()
        if cleaned and cleaned not in seen:
            seen.append(cleaned)
    return tuple(seen)


class BrainStore:
    """Manages Markdown notes partitioned by scope under ``self.root``."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = (root if root is not None else brain_root()).expanduser()

    def note_path(self, scope: str, slug: str) -> Path:
        clean_scope = validate_scope(scope)
        clean_slug = validate_slug(slug)
        path = self.root / clean_scope / f"{clean_slug}.md"
        if not path.resolve().is_relative_to(self.root.resolve()):
            raise ValueError(f"Note path escapes the brain store: {path}")
        return path

    def _unique_slug(self, scope: str, base_slug: str) -> str:
        candidate = validate_slug(base_slug)
        if not self.note_path(scope, candidate).exists():
            return candidate
        counter = 2
        while True:
            suffix = f"-{counter}"
            numbered = f"{candidate[: 80 - len(suffix)]}{suffix}"
            if not self.note_path(scope, numbered).exists():
                return numbered
            counter += 1

    def add(self, draft: NoteDraft) -> BrainNote:
        body = draft.body.strip()
        if not body:
            raise ValueError("Note text cannot be empty.")
        kind = validate_kind(draft.kind)
        scope = validate_scope(draft.scope)
        title = draft.title.strip() or derive_title(body)
        tags = _dedup_tuple(draft.tags)
        repos = _dedup_tuple(draft.repos)
        check_no_secrets(title, body, draft.source, *tags, *repos)
        if draft.slug:
            slug = validate_slug(draft.slug)
            if self.note_path(scope, slug).exists():
                raise FileExistsError(f"Note '{scope}/{slug}' already exists")
        else:
            slug = self._unique_slug(scope, slugify(title))
        stamp = today_iso()
        note = BrainNote(
            slug=slug,
            title=title,
            kind=kind,
            scope=scope,
            body=body,
            tags=tags,
            repos=repos,
            source=draft.source.strip(),
            created=stamp,
            updated=stamp,
        )
        return self.save(note, reject_secrets=False)

    def save(self, note: BrainNote, *, reject_secrets: bool = True) -> BrainNote:
        validate_kind(note.kind)
        scope = validate_scope(note.scope)
        slug = validate_slug(note.slug)
        if reject_secrets:
            check_no_secrets(note.title, note.body, note.source, *note.tags, *note.repos)
        path = self.note_path(scope, slug)
        stored = replace(note, scope=scope, slug=slug, path=path)
        atomic_write_text(path, serialize_note(stored))
        return stored

    def scopes(self) -> list[str]:
        if not self.root.is_dir():
            return []
        return sorted(
            entry.name
            for entry in self.root.iterdir()
            if entry.is_dir() and not entry.name.startswith(".")
        )

    def _read_file(self, scope: str, path: Path) -> BrainNote:
        return parse_note(path.read_text(encoding="utf-8"), slug=path.stem, scope=scope, path=path)

    def get(self, ref: str, *, scope: str | None = None) -> BrainNote:
        ref_scope, slug = parse_ref(ref)
        chosen_scope = validate_scope(scope) if scope else ref_scope
        if chosen_scope is not None:
            path = self.note_path(chosen_scope, slug)
            if not path.is_file():
                raise FileNotFoundError(f"Note '{chosen_scope}/{slug}' not found")
            return self._read_file(chosen_scope, path)
        matches = [
            (sc, self.note_path(sc, slug))
            for sc in self.scopes()
            if self.note_path(sc, slug).is_file()
        ]
        if not matches:
            raise FileNotFoundError(f"Note '{slug}' not found")
        if len(matches) > 1:
            choices = ", ".join(f"{sc}/{slug}" for sc, _ in matches)
            raise ValueError(f"Ambiguous note '{slug}' in multiple scopes: {choices}")
        found_scope, found_path = matches[0]
        return self._read_file(found_scope, found_path)

    def _matches_filter(self, note: BrainNote, criteria: NoteFilter) -> bool:
        if criteria.kind and note.kind != criteria.kind:
            return False
        if criteria.repo and criteria.repo.lower() not in {r.lower() for r in note.repos}:
            return False
        if criteria.stale_days is not None:
            return is_stale(note, days=criteria.stale_days, today=criteria.today)
        return True

    def _scope_notes(self, scope: str, flt: NoteFilter) -> list[BrainNote]:
        folder = self.root / scope
        if not folder.is_dir():
            return []
        notes: list[BrainNote] = []
        for path in sorted(folder.glob("*.md")):
            if not path.is_file() or not _SLUG_RE.fullmatch(path.stem):
                continue
            note = self._read_file(scope, path)
            if self._matches_filter(note, flt):
                notes.append(note)
        return notes

    def list(self, criteria: NoteFilter | None = None) -> list[BrainNote]:
        flt = criteria or NoteFilter()
        if flt.kind:
            validate_kind(flt.kind)
        if flt.stale_days is not None and flt.stale_days < 1:
            raise ValueError(f"stale_days must be >= 1, got {flt.stale_days}")
        target_scopes = [validate_scope(flt.scope)] if flt.scope else self.scopes()
        notes = [note for scope in target_scopes for note in self._scope_notes(scope, flt)]
        return sorted(notes, key=lambda n: (n.updated, n.ref), reverse=True)

    def count_for_repo(self, repo: str) -> int:
        return len(self.list(NoteFilter(repo=repo)))
