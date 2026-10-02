"""Fixed context cost per agent: bytes loaded every session, before any file is touched."""

from __future__ import annotations

from pathlib import Path

from .engine import END, START, Ledger
from .installer import installed_agents

BYTES_PER_TOKEN = 4


def _always_loaded(path: Path, text: str) -> bool:
    """Path-scoped rules load only for matching files; everything else is fixed cost."""
    if path.suffix != ".md" or "/rules/" not in path.as_posix():
        return False  # scouts/skills: only name + description preload (not counted)
    header = text.split("\n---", 1)[0] if text.startswith("---") else ""
    return "paths:" not in header and "trigger: glob" not in header


def _block(text: str) -> str:
    if START in text and END in text:
        return text.split(START, 1)[1].split(END, 1)[0]
    return ""


def fixed_cost(ledger: Ledger) -> dict[str, int]:
    """Bytes per owner (each agent, ``project`` = shared) loaded at session start."""
    totals: dict[str, int] = {}
    agents = installed_agents(ledger)
    for entry in ledger.entries:
        path = ledger.resolve(entry["path"])
        if entry["agent"] not in agents or not path.is_file() or entry["kind"] == "hooks":
            continue
        text = path.read_text(encoding="utf-8")
        size = 0
        if entry["kind"] == "block":
            size = len(_block(text).encode("utf-8"))
        elif _always_loaded(path, text):
            size = len(text.encode("utf-8"))
        totals[entry["agent"]] = totals.get(entry["agent"], 0) + size
    return totals
