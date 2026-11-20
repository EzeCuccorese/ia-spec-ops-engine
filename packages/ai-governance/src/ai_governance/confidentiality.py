"""Checks for references that must stay out of company facing text."""

from __future__ import annotations

import html
import re
import unicodedata

_INTERNAL_REFERENCE = re.compile(
    r"\b(?:ai-governance|ai_governance|ia-spec-ops-engine|taskflow|qg_skip|workspace_engine)\b"
    r"|\bws\s+(?:check|run|detect|condense|design|hooks)\b"
    r"|\bengine tooling\b",
    re.IGNORECASE,
)


class ConfidentialityError(ValueError):
    """Raised when external content includes a reference to private tooling."""


def _normalize(text: str) -> str:
    nfkc = unicodedata.normalize("NFKC", html.unescape(text))
    chars = []
    for ch in nfkc:
        cat = unicodedata.category(ch)
        if cat == "Cf":
            continue
        if cat == "Pd" or ch == "\u2212":
            chars.append("-")
        else:
            chars.append(ch)
    return "".join(chars)


def reject_engine_references(text: str) -> None:
    """Reject identifiable engine or tooling references in company facing text."""
    match = _INTERNAL_REFERENCE.search(_normalize(text))
    if match:
        raise ConfidentialityError(
            f"Content includes restricted internal references: {match.group(0)!r}."
        )
