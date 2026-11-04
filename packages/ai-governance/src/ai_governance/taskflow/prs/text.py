"""Display safety for text that comes from GitHub or from a paste (titles, groups, errors).

Such text is data. It is flattened to one short plain line before it reaches a table or JSON,
and it is never placed inside an instruction, a hook answer or an Orca line.
"""

from __future__ import annotations

import re
import unicodedata

_ANSI = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\)?|[@-Z\\-_])")
_BLOCKED_CATEGORIES = frozenset({"Cc", "Cf", "Zl", "Zp"})
_SPACE = re.compile(r"\s+")
ELLIPSIS = "..."


def clean_text(value: object, limit: int = 60) -> str:
    """One printable line of at most ``limit`` characters (controls and escapes removed)."""
    text = _ANSI.sub("", str(value))
    text = "".join(" " if ch in "\r\n\t" else ch for ch in text)
    text = "".join(ch for ch in text if unicodedata.category(ch) not in _BLOCKED_CATEGORIES)
    text = _SPACE.sub(" ", text).strip()
    if len(text) > limit:
        text = text[: max(limit - len(ELLIPSIS), 0)].rstrip() + ELLIPSIS
    return text


def safe_text(value: object, limit: int = 60) -> str:
    """``clean_text`` for display: ``[`` is escaped so Rich never reads it as markup."""
    return clean_text(value, limit).replace("[", "\\[")
