"""Checks for references that must stay out of company facing text."""

from __future__ import annotations

import html
import re

_INTERNAL_REFERENCE = re.compile(
    r"\b(?:ai-governance|ai_governance|ia-spec-ops-engine|taskflow|qg_skip|workspace_engine)\b"
    r"|\bws\s+(?:check|run|detect|condense|design|hooks)\b"
    r"|\bquality[- ]gate\b|\binternal hooks?\b|\bengine tooling\b",
    re.IGNORECASE,
)


class ConfidentialityError(ValueError):
    """Raised when external content includes a reference to private tooling."""


def reject_engine_references(text: str) -> None:
    """Reject identifiable engine or tooling references in company facing text."""
    if _INTERNAL_REFERENCE.search(html.unescape(text)):
        raise ConfidentialityError("Content includes restricted internal references.")
