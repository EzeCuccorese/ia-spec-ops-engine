"""Filesystem locations used by ai-governance (XDG layout).

- Config: ``$AI_GOVERNANCE_CONFIG_DIR`` or ``$XDG_CONFIG_HOME/ai-governance``
  (default ``~/.config/ai-governance``).
- State: ``$AI_GOVERNANCE_STATE_DIR`` or ``$XDG_STATE_HOME/ai-governance``
  (default ``~/.local/state/ai-governance``).

Paths are resolved on every call so tests can monkeypatch the environment.
"""

from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "ai-governance"


def config_dir() -> Path:
    explicit = os.environ.get("AI_GOVERNANCE_CONFIG_DIR")
    if explicit:
        return Path(explicit).expanduser()
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base).expanduser() / APP_NAME


def state_dir() -> Path:
    explicit = os.environ.get("AI_GOVERNANCE_STATE_DIR")
    if explicit:
        return Path(explicit).expanduser()
    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(base).expanduser() / APP_NAME
