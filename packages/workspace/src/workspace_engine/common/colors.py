"""
workspace_engine.common.colors — Unified ANSI color palette and plain-text output helpers.

Hosts the "agent mode" output helper (`is_agent_mode`, `emit_rows`,
`truncate`) so that non-interactive `ws` commands emit compact plain text.
This is a deliberate, small duplication of `ai_governance.output`:
`workspace_engine` must not depend on the `ai-governance` package.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from typing import TextIO

from workspace_engine._config_core import AGENT_ENV_MARKERS as AGENT_ENV_MARKERS
from workspace_engine._config_core import ConfigError
from workspace_engine._config_core import is_agent_mode as core_is_agent_mode
from workspace_engine.settings import effective

DEFAULT_MAX_LINES = 20
DEFAULT_MAX_CHARS = 1500


def is_agent_mode() -> bool:
    """Returns True when output should be compact/plain for an AI agent.

    ``WORKSPACE_AGENT=1`` forces agent mode on; ``WORKSPACE_AGENT=0`` forces it
    off. Otherwise agent mode is on when an agent env marker is present; a plain
    pipe keeps full human output.
    """
    return core_is_agent_mode("workspace")


def _limit(key: str, fallback: int) -> int:
    try:
        return int(effective()[key].value)  # type: ignore[call-overload]
    except ConfigError:
        return fallback


def _limit_or(value: int | None, key: str, fallback: int) -> int:
    return value if value is not None else _limit(key, fallback)


def _fit_lines(lines: list[str], budget: int) -> list[str]:
    """The leading lines whose joined length stays within ``budget``."""
    kept: list[str] = []
    total = 0
    for line in lines:
        add = len(line) + (1 if kept else 0)
        if total + add > budget:
            break
        kept.append(line)
        total += add
    return kept


def truncate(
    text: str,
    *,
    max_lines: int | None = None,
    max_chars: int | None = None,
    more_hint: str = "",
) -> str:
    """Truncates `text` to at most `max_lines` lines and `max_chars` characters.

    Cuts only on line boundaries. When truncation occurs (by either limit),
    the last returned line is exactly ``more: <more_hint>`` (or just
    ``more:`` when `more_hint` is empty).
    """
    max_lines = _limit_or(max_lines, "output.max_lines", DEFAULT_MAX_LINES)
    max_chars = _limit_or(max_chars, "output.max_chars", DEFAULT_MAX_CHARS)
    all_lines = text.splitlines()
    hint_line = "more:" + (f" {more_hint}" if more_hint else "")

    needs_line_cut = len(all_lines) > max_lines
    candidate_lines = all_lines[: max_lines - 1] if needs_line_cut else list(all_lines)

    needs_char_cut = len("\n".join(candidate_lines)) > max_chars
    if needs_char_cut:
        candidate_lines = _fit_lines(candidate_lines, max_chars - len(hint_line) - 1)

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
    """Emits tabular data as one compact line per row.

    Columns are joined with ``" | "``; the title (if any) and headers (if any)
    each become their own line above the rows. In agent mode, output is
    truncated unless ``full`` is True.
    """
    lines: list[str] = []
    if title:
        lines.append(title)
    if headers:
        lines.append(" | ".join(headers))
    lines.extend(" | ".join(row) for row in rows)
    text = "\n".join(lines)
    if is_agent_mode() and not full:
        text = truncate(text, more_hint=more_hint)
    print(text)


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
