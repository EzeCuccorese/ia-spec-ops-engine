"""Structured documentation of where each agnostic trigger lives per host.

This module is documentation, not automation: it does not write host
configuration for anyone. It exists so later phases (and humans) can look up
where a given agnostic trigger (see ``TRIGGERS`` in ``catalog.py``) is wired
in a specific coding-agent host.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .catalog import TRIGGERS


@dataclass(frozen=True)
class HostBinding:
    trigger: str
    location: str
    notes: str = ""


HOST_TRIGGER_MAP: dict[str, tuple[HostBinding, ...]] = {
    "claude-code": (
        HostBinding(
            "before-shell-command",
            "~/.claude/settings.json → hooks.PreToolUse[matcher=Bash].hooks[].command",
        ),
        HostBinding(
            "after-shell-command",
            "~/.claude/settings.json → hooks.PostToolUse[matcher=Bash].hooks[].command",
        ),
        HostBinding(
            "on-turn-end",
            "~/.claude/settings.json → hooks.Stop[].hooks[].command",
        ),
        HostBinding(
            "on-worktree-create",
            "~/.claude/settings.json → hooks.WorktreeCreate[].hooks[].command",
            "Hook must exit 0 and print hookSpecificOutput.workTreePath; "
            "non-zero exit aborts worktree creation",
        ),
    ),
}


def bindings_for(host: str) -> tuple[HostBinding, ...]:
    return HOST_TRIGGER_MAP.get(host, ())


def known_hosts() -> list[str]:
    return list(HOST_TRIGGER_MAP.keys())


def detect_host() -> str | None:
    if (Path.home() / ".claude" / "settings.json").exists():
        return "claude-code"
    return None


def validate_host_map() -> None:
    """Raise if any automatic (non on-demand) trigger lacks a claude-code binding."""
    bound_triggers = {binding.trigger for binding in bindings_for("claude-code")}
    required = TRIGGERS - {"on-demand"}
    missing = required - bound_triggers
    if missing:
        raise ValueError(
            f"claude-code host map is missing bindings for triggers: {sorted(missing)}"
        )
