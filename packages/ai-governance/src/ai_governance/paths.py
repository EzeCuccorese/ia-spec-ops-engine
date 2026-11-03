"""Filesystem locations used by ai-governance (XDG layout).

- Config: ``$AI_GOVERNANCE_CONFIG_DIR`` or ``$XDG_CONFIG_HOME/ai-governance``
  (default ``~/.config/ai-governance``).
- State: ``$AI_GOVERNANCE_STATE_DIR`` or ``$XDG_STATE_HOME/ai-governance``
  (default ``~/.local/state/ai-governance``).
- Data: ``$AI_GOVERNANCE_DATA_DIR`` or ``$XDG_DATA_HOME/ai-governance``
  (default ``~/.local/share/ai-governance``; generated shell completions).

Paths are resolved on every call so tests can monkeypatch the environment.
"""

from __future__ import annotations

from pathlib import Path

from ._config_core import xdg_dir

APP_NAME = "ai-governance"


def config_dir() -> Path:
    return xdg_dir("config", APP_NAME)


def state_dir() -> Path:
    return xdg_dir("state", APP_NAME)


def data_dir() -> Path:
    return xdg_dir("data", APP_NAME)
