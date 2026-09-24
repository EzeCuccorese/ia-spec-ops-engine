"""
workspace_engine.common.colors — Unified ANSI color palette and Rich console for Workspace Engine.

Also hosts a small "agent mode" output helper (`is_agent_mode`, `emit_rows`,
`truncate`) so that non-interactive `ws` commands emit compact plain text
when run by an AI coding agent instead of ANSI-heavy Rich tables. This is a
deliberate, small duplication of `ai_governance.output`: `workspace_engine`
must not depend on the `ai-governance` package.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Sequence
from typing import TextIO

from rich.console import Console
from rich.table import Table

# Shared Rich Console instance
console = Console()
err_console = Console(stderr=True)

DEFAULT_MAX_LINES = 20
DEFAULT_MAX_CHARS = 1500


# Environment variables set by supported agents for the commands they spawn.
# Kept identical to ai_governance.output.AGENT_ENV_MARKERS (contract test at repo root).
AGENT_ENV_MARKERS: tuple[str, ...] = (
    "CLAUDE_CODE_CHILD_SESSION",
    "CLAUDECODE",
    "CODEX_SANDBOX",
    "ANTIGRAVITY_AGENT",
)


def is_agent_mode() -> bool:
    """Returns True when output should be compact/plain for an AI agent.

    ``WORKSPACE_AGENT=1`` forces agent mode on; ``WORKSPACE_AGENT=0`` forces it
    off. Otherwise agent mode is on when an agent env marker is present; a plain
    pipe keeps full human output.
    """
    forced = os.environ.get("WORKSPACE_AGENT")
    if forced == "1":
        return True
    if forced == "0":
        return False
    return any(os.environ.get(name) for name in AGENT_ENV_MARKERS)


def truncate(
    text: str,
    *,
    max_lines: int = DEFAULT_MAX_LINES,
    max_chars: int = DEFAULT_MAX_CHARS,
    more_hint: str = "",
) -> str:
    """Truncates `text` to at most `max_lines` lines and `max_chars` characters.

    Cuts only on line boundaries. When truncation occurs (by either limit),
    the last returned line is exactly ``more: <more_hint>`` (or just
    ``more:`` when `more_hint` is empty).
    """
    all_lines = text.splitlines()
    hint_line = "more:" + (f" {more_hint}" if more_hint else "")

    needs_line_cut = len(all_lines) > max_lines
    candidate_lines = all_lines[: max_lines - 1] if needs_line_cut else list(all_lines)

    needs_char_cut = len("\n".join(candidate_lines)) > max_chars
    if needs_char_cut:
        budget = max_chars - len(hint_line) - 1
        kept: list[str] = []
        total = 0
        for line in candidate_lines:
            add = len(line) + (1 if kept else 0)
            if total + add > budget:
                break
            kept.append(line)
            total += add
        candidate_lines = kept

    if needs_line_cut or needs_char_cut:
        candidate_lines.append(hint_line)

    return "\n".join(candidate_lines)


def emit_rows(
    rows: Sequence[Sequence[str]],
    *,
    headers: Sequence[str] | None = None,
    title: str | None = None,
    full: bool = False,
    more_hint: str = "",
) -> None:
    """Emits tabular data: a rich table on TTY, or one compact line per row.

    In agent mode, columns are joined with ``" | "``; the title (if any)
    and headers (if any) each become their own line above the rows.
    """
    if is_agent_mode():
        lines: list[str] = []
        if title:
            lines.append(title)
        if headers:
            lines.append(" | ".join(headers))
        lines.extend(" | ".join(row) for row in rows)
        text = "\n".join(lines)
        if not full:
            text = truncate(text, more_hint=more_hint)
        print(text)
        return

    table = Table(title=title, border_style="cyan")
    for header in headers or []:
        table.add_column(header)
    for row in rows:
        table.add_row(*row)
    console.print(table)


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
    if is_agent_mode():
        print(f"INFO: {message}", file=target)
        return
    print(f"{Color.CYAN}ℹ {message}{Color.RESET}", file=target)


def log_success(message: str, file: TextIO | None = None) -> None:
    """Prints a success message with unified formatting."""
    target = file if file is not None else sys.stdout
    if is_agent_mode():
        print(f"OK: {message}", file=target)
        return
    print(f"{Color.GREEN}✔ {message}{Color.RESET}", file=target)


def log_warning(message: str, file: TextIO | None = None) -> None:
    """Prints a warning message with unified formatting."""
    target = file if file is not None else sys.stdout
    if is_agent_mode():
        print(f"WARN: {message}", file=target)
        return
    print(f"{Color.YELLOW}⚠ {message}{Color.RESET}", file=target)


def log_error(message: str, file: TextIO | None = None) -> None:
    """Prints an error message to stderr with unified formatting."""
    target = file if file is not None else sys.stderr
    if is_agent_mode():
        print(f"ERROR: {message}", file=target)
        return
    print(f"{Color.RED}✖ {message}{Color.RESET}", file=target)


def colorize(text: str, color: str) -> str:
    """Wraps text with an ANSI code and resets automatically."""
    return f"{color}{text}{Color.RESET}"
