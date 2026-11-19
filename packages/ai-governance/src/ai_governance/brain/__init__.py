"""Cross-agent second brain (PARA Resources & Archive) backed by plain Markdown files."""

from __future__ import annotations

from .store import (
    DEFAULT_SCOPE,
    DEFAULT_STALE_DAYS,
    VALID_KINDS,
    BrainNote,
    BrainStore,
    NoteDraft,
    NoteFilter,
    SecretContentError,
    brain_root,
    infer_repo,
    infer_scope,
    slugify,
)

__all__ = [
    "BrainNote",
    "BrainStore",
    "DEFAULT_SCOPE",
    "DEFAULT_STALE_DAYS",
    "NoteDraft",
    "NoteFilter",
    "SecretContentError",
    "VALID_KINDS",
    "brain_root",
    "infer_repo",
    "infer_scope",
    "slugify",
]
