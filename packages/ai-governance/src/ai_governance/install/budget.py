"""Fixed context cost per agent: bytes loaded every session, before any file is touched."""

from __future__ import annotations

from pathlib import Path

from ..frontmatter import _FRONTMATTER_RE
from .engine import END, START, Ledger
from .installer import COMPLETIONS_OWNER, SCHEDULE_OWNER, SCRIPTS_OWNER

BYTES_PER_TOKEN = 4


def _always_loaded(path: Path, text: str, agent: str = "") -> bool:
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
        if agent == "claude":
            return "paths:" not in header
        if agent == "antigravity":
            return "trigger: glob" not in header
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


def _entry_costs(kind: str, path: Path, agent: str = "") -> tuple[int, int]:
    text = path.read_text(encoding="utf-8")
    if kind == "block":
        agent_bytes = len(_block(text).encode("utf-8"))
        user_text = _user_content(text) if path.name == "AGENTS.md" else ""
        user_bytes = len(user_text.encode("utf-8")) if user_text else 0
        return agent_bytes, user_bytes
    if _always_loaded(path, text, agent):
        return len(text.encode("utf-8")), 0
    return 0, 0


_IGNORED_OWNERS = frozenset({SCRIPTS_OWNER, COMPLETIONS_OWNER, SCHEDULE_OWNER})


def _file_targets(ledger: Ledger) -> set[Path]:
    return {
        ledger.resolve(entry["path"]).resolve()
        for entry in ledger.entries
        if entry["kind"] == "file" and entry["agent"] not in _IGNORED_OWNERS
    }


def _should_count(entry: dict[str, str], path: Path, file_targets: set[Path]) -> bool:
    if entry["agent"] in _IGNORED_OWNERS or entry["kind"] == "hooks" or not path.is_file():
        return False
    return not (entry["kind"] == "link" and path.resolve() in file_targets)


def fixed_cost(ledger: Ledger) -> dict[str, int]:
    """Bytes per owner (each agent, ``project`` = shared, ``user_custom`` = user custom) loaded at session start."""
    totals: dict[str, int] = {}
    file_targets = _file_targets(ledger)
    for entry in ledger.entries:
        path = ledger.resolve(entry["path"])
        if not _should_count(entry, path, file_targets):
            continue
        agent_bytes, user_bytes = _entry_costs(entry["kind"], path, entry["agent"])
        if user_bytes:
            totals["user_custom"] = totals.get("user_custom", 0) + user_bytes
        totals[entry["agent"]] = totals.get(entry["agent"], 0) + agent_bytes
    return totals
