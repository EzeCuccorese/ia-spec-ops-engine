"""Shared YAML front matter utilities for rule files."""

from __future__ import annotations

import re
from typing import NamedTuple

VALID_TRIGGERS = {"always_on", "glob"}

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n(?:---|\.\.\.)\s*(?:\n|$)", re.DOTALL)
_TRIGGER_RE = re.compile(r"^\s*trigger:\s*['\"]?([a-zA-Z0-9_-]+)['\"]?\s*$", re.MULTILINE)


class FrontmatterCheck(NamedTuple):
    valid: bool
    trigger: str | None


def check_frontmatter(text: str) -> FrontmatterCheck:
    """Return whether the markdown text has a valid YAML front matter block.

    A valid rule front matter block starts with ``---`` and contains a ``trigger``
    attribute set to either ``always_on`` or ``glob``.
    """
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return FrontmatterCheck(valid=False, trigger=None)
    yaml_content = match.group(1)
    trigger_match = _TRIGGER_RE.search(yaml_content)
    if not trigger_match:
        return FrontmatterCheck(valid=False, trigger=None)
    trigger = trigger_match.group(1)
    return FrontmatterCheck(valid=trigger in VALID_TRIGGERS, trigger=trigger)


def ensure_frontmatter(content: str, default_trigger: str = "always_on") -> str:
    """Ensure the markdown content starts with a front matter block containing trigger."""
    check = check_frontmatter(content)
    if check.valid:
        return content
    match = _FRONTMATTER_RE.match(content)
    if match:
        yaml_content = match.group(1)
        rest = content[match.end() :]
        if _TRIGGER_RE.search(yaml_content):
            yaml_content = _TRIGGER_RE.sub(f"trigger: {default_trigger}", yaml_content)
        else:
            yaml_content = f"trigger: {default_trigger}\n{yaml_content}"
        return f"---\n{yaml_content.strip()}\n---\n{rest}"
    return f"---\ntrigger: {default_trigger}\n---\n{content}"
