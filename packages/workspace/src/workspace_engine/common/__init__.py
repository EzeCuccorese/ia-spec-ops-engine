"""
workspace_engine.common — Base package of shared utilities and libraries for Workspace Engine.
"""

from __future__ import annotations

from workspace_engine.common.colors import (
    BLUE,
    BOLD,
    CYAN,
    DEFAULT_MAX_CHARS,
    DEFAULT_MAX_LINES,
    DIM,
    END,
    GRAY,
    GREEN,
    MAGENTA,
    RED,
    RESET,
    UNDERLINE,
    WHITE,
    YELLOW,
    Color,
    colorize,
    emit_rows,
    is_agent_mode,
    log_error,
    log_info,
    log_success,
    log_warning,
    truncate,
)
from workspace_engine.common.subprocess import (
    DEFAULT_COMMAND_TIMEOUT,
    run_command,
    run_command_safe,
    run_git,
)

__all__ = [
    "Color",
    "RED",
    "GREEN",
    "YELLOW",
    "BLUE",
    "MAGENTA",
    "CYAN",
    "WHITE",
    "GRAY",
    "BOLD",
    "DIM",
    "UNDERLINE",
    "RESET",
    "END",
    "colorize",
    "log_info",
    "log_success",
    "log_warning",
    "log_error",
    "is_agent_mode",
    "emit_rows",
    "truncate",
    "DEFAULT_MAX_LINES",
    "DEFAULT_MAX_CHARS",
    "DEFAULT_COMMAND_TIMEOUT",
    "run_command",
    "run_command_safe",
    "run_git",
]
