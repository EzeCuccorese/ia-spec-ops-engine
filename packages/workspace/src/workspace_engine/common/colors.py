"""
workspace_engine.common.colors — Unified ANSI color palette and Rich console for Workspace Engine.
"""

from __future__ import annotations

import sys
from typing import TextIO

from rich.console import Console

# Shared Rich Console instance
console = Console()
err_console = Console(stderr=True)


class Color:
    """Standard and high-fidelity ANSI escape codes."""

    RED = "\033[0;31m"
    GREEN = "\033[0;32m"
    YELLOW = "\033[1;33m"
    BLUE = "\033[0;34m"
    MAGENTA = "\033[0;35m"
    CYAN = "\033[0;36m"
    WHITE = "\033[1;37m"
    GRAY = "\033[0;90m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    UNDERLINE = "\033[4m"
    RESET = "\033[0m"
    END = "\033[0m"

    HIGH_RED = "\033[91m"
    HIGH_GREEN = "\033[92m"
    HIGH_YELLOW = "\033[93m"
    HIGH_BLUE = "\033[94m"
    HIGH_MAGENTA = "\033[95m"
    HIGH_CYAN = "\033[96m"
    HIGH_WHITE = "\033[97m"


# Direct global aliases
RED = Color.RED
GREEN = Color.GREEN
YELLOW = Color.YELLOW
BLUE = Color.BLUE
MAGENTA = Color.MAGENTA
CYAN = Color.CYAN
WHITE = Color.WHITE
GRAY = Color.GRAY
BOLD = Color.BOLD
DIM = Color.DIM
UNDERLINE = Color.UNDERLINE
RESET = Color.RESET
END = Color.END


def log_info(message: str, file: TextIO | None = None) -> None:
    """Prints an informational message with unified formatting."""
    target = file if file is not None else sys.stdout
    print(f"{Color.CYAN}ℹ {message}{Color.RESET}", file=target)


def log_success(message: str, file: TextIO | None = None) -> None:
    """Prints a success message with unified formatting."""
    target = file if file is not None else sys.stdout
    print(f"{Color.GREEN}✔ {message}{Color.RESET}", file=target)


def log_warning(message: str, file: TextIO | None = None) -> None:
    """Prints a warning message with unified formatting."""
    target = file if file is not None else sys.stdout
    print(f"{Color.YELLOW}⚠ {message}{Color.RESET}", file=target)


def log_error(message: str, file: TextIO | None = None) -> None:
    """Prints an error message to stderr with unified formatting."""
    target = file if file is not None else sys.stderr
    print(f"{Color.RED}✖ {message}{Color.RESET}", file=target)


def colorize(text: str, color: str) -> str:
    """Wraps text with an ANSI code and resets automatically."""
    return f"{color}{text}{Color.RESET}"
