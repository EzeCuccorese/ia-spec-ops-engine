"""ai_governance.output — Agent-aware output primitives for ai-governance CLIs.

When a coding agent runs these CLIs, verbose output (rich tables, banners,
indented JSON) lands in its context window and wastes tokens. "Agent mode"
emits compact plain text instead: one line per row, ``key: value`` pairs,
dense JSON and short ``OK:``/``WARN:``/``ERROR:``/``INFO:`` status lines.

Agent mode is detected from the environment each supported agent sets for
the commands it spawns (see :data:`AGENT_ENV_MARKERS`). ``AI_GOVERNANCE_AGENT``
overrides detection: ``1`` forces agent mode, ``0`` forces human mode. A plain
pipe (``| grep``) is NOT agent mode, so humans and scripts get full output.
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Sequence
from typing import Any, Literal

from rich.console import Console
from rich.table import Table

DEFAULT_MAX_LINES = 20
DEFAULT_MAX_CHARS = 1500

# Rich console is kept private to this module: TTY consumers no longer
# need to import rich themselves for output.
_console = Console()


# Environment variables set by supported agents for the commands they spawn.
AGENT_ENV_MARKERS: tuple[str, ...] = (
    "CLAUDE_CODE_CHILD_SESSION",  # Claude Code (tool and hook subprocesses)
    "CLAUDECODE",  # Claude Code (any subprocess)
    "CODEX_SANDBOX",  # OpenAI Codex (spawned commands; experimental upstream)
    "ANTIGRAVITY_AGENT",  # Google Antigravity agent terminal
)


def is_agent_mode() -> bool:
    """Returns True when output should be compact/plain for an AI agent."""
    forced = os.environ.get("AI_GOVERNANCE_AGENT")
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
    _console.print(table)


def emit_kv(
    pairs: Sequence[tuple[str, str]],
    *,
    title: str | None = None,
    full: bool = False,
    more_hint: str = "",
) -> None:
    """Emits key/value data: a two-column rich table on TTY, or `key: value` lines."""
    if is_agent_mode():
        lines: list[str] = []
        if title:
            lines.append(title)
        lines.extend(f"{key}: {value}" for key, value in pairs)
        text = "\n".join(lines)
        if not full:
            text = truncate(text, more_hint=more_hint)
        print(text)
        return

    table = Table(title=title, show_header=False, border_style="cyan")
    table.add_column("Key", style="bold green")
    table.add_column("Value", style="white")
    for key, value in pairs:
        table.add_row(key, value)
    _console.print(table)


def emit_json(obj: Any) -> None:
    """Emits JSON: dense single-line in agent mode, indented for TTY use."""
    if is_agent_mode():
        print(json.dumps(obj, separators=(",", ":"), ensure_ascii=False))
    else:
        print(json.dumps(obj, indent=2, ensure_ascii=False))


_STATUS_STYLE: dict[str, tuple[str, str]] = {
    "ok": ("green", "✔"),
    "warn": ("yellow", "⚠"),
    "error": ("red", "✖"),
    "info": ("cyan", "ℹ"),
}


def emit_status(level: Literal["ok", "warn", "error", "info"], message: str) -> None:
    """Emits a status line. Errors go to stderr; all others go to stdout."""
    is_error = level == "error"
    if is_agent_mode():
        prefix = level.upper()
        stream = sys.stderr if is_error else sys.stdout
        print(f"{prefix}: {message}", file=stream)
        return

    # Preserve pre-existing TTY behaviour: statuses (including errors) print to
    # stdout via the shared Console. Only agent mode routes ERROR to stderr,
    # per contract.
    style, icon = _STATUS_STYLE[level]
    _console.print(f"[{style}]{icon} {message}[/{style}]")


def emit_text(text: str, *, full: bool = False, more_hint: str = "") -> None:
    """Emits free-form text, truncated in agent mode unless `full` is True."""
    if is_agent_mode():
        if not full:
            text = truncate(text, more_hint=more_hint)
        print(text)
        return
    _console.print(text)
