"""Fixed context cost per agent: bytes loaded every session, before any file is touched."""

from __future__ import annotations

from pathlib import Path

from ..frontmatter import _FRONTMATTER_RE
from .engine import END, START, Ledger
from .installer import SCHEDULE_OWNER, SCRIPTS_OWNER

BYTES_PER_TOKEN = 4


def _always_loaded(path: Path, text: str) -> bool:
    """Path-scoped rules load only for matching files; everything else is fixed cost."""
    if path.suffix != ".md":
        return False
    posix = path.as_posix()
    if "/ai-governance/always/" in posix or "/ai-governance/personal/" in posix:
        return True
    if posix.endswith("/ai-governance/company/index.md"):
        return True
    if "/rules/" in posix:
        match = _FRONTMATTER_RE.match(text)
        header = match.group(1) if match else ""
        return "paths:" not in header and "trigger: glob" not in header
    return False


def _block(text: str) -> str:
    if START in text and END in text:
        return text.split(START, 1)[1].split(END, 1)[0]
    return ""


def _user_content(text: str) -> str:
    if START in text and END in text:
        before = text.split(START, 1)[0]
        after = text.split(END, 1)[1]
        return (before + after).strip()
    return text.strip()


def _entry_costs(kind: str, path: Path) -> tuple[int, int]:
    text = path.read_text(encoding="utf-8")
    if kind == "block":
        agent_bytes = len(_block(text).encode("utf-8"))
        user_text = _user_content(text) if path.name == "AGENTS.md" else ""
        user_bytes = len(user_text.encode("utf-8")) if user_text else 0
        return agent_bytes, user_bytes
    if _always_loaded(path, text):
        return len(text.encode("utf-8")), 0
    return 0, 0


def fixed_cost(ledger: Ledger) -> dict[str, int]:
    """Bytes per owner (each agent, ``project`` = shared, ``user_custom`` = user custom) loaded at session start."""
    totals: dict[str, int] = {}
    for entry in ledger.entries:
        path = ledger.resolve(entry["path"])
        if entry["agent"] in {SCRIPTS_OWNER, SCHEDULE_OWNER} or not path.is_file():
            continue
        if entry["kind"] == "hooks":
            continue
        agent_bytes, user_bytes = _entry_costs(entry["kind"], path)
        if user_bytes:
            totals["user_custom"] = totals.get("user_custom", 0) + user_bytes
        totals[entry["agent"]] = totals.get(entry["agent"], 0) + agent_bytes
    return totals
