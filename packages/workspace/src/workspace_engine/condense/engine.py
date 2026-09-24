"""Deterministic command-output condenser (no LLM).

Keeps what an agent needs from a command's output inside a character budget:
the tool's summary line, every failure with nearby context, and the tail, while
dropping ANSI codes, progress bars, timestamps and repeated noise. Successful
runs collapse to one line.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

DEFAULT_BUDGET = 2500
_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07]*\x07")
_TIMESTAMP = re.compile(r"^\s*\[?\d{4}-\d{2}-\d{2}[T ][\d:.,]+Z?\]?\s*")
# Progress redraws: bracketed bars, or lines ending in a percentage (downloads, pytest dots).
_PROGRESS = re.compile(r"^\s*\[[#=>\-\s.]+\]|\d{1,3}(\.\d+)?%\]?\s*$")
_TEMPLATE_TOKENS = re.compile(r"0x[0-9a-f]+|\b[0-9a-f]{7,40}\b|\d+(\.\d+)?|(/[\w.\-]+)+")

_GENERIC_SIGNAL = re.compile(
    r"\b(error|errors|failed|failure|failures|fatal|exception|traceback|panic|"
    r"assert(ion)?error|segmentation fault|undefined reference|cannot find|not found|"
    r"denied|refused|timed out|FAIL|ERROR)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ToolProfile:
    name: str
    command: re.Pattern[str]
    summary: re.Pattern[str]
    signal: re.Pattern[str]


PROFILES: tuple[ToolProfile, ...] = (
    ToolProfile(
        "pytest",
        re.compile(r"\b(pytest|py\.test)\b|-m pytest"),
        re.compile(r"^=+ .*\b(passed|failed|error|errors|no tests ran)\b.* in [\d.]+s"),
        re.compile(r"^(E\s|FAILED |ERROR |_{3,} .* _{3,}$|\S+\.py:\d+: )"),
    ),
    ToolProfile(
        "jest",
        re.compile(r"\b(jest|vitest)\b|npm (run )?test|yarn test|pnpm test"),
        re.compile(r"^\s*(Tests?|Test Files|Test Suites):\s+.*\b(passed|failed|total)\b"),
        re.compile(r"^\s*(●|×|✕|FAIL\b|Expected|Received|AssertionError|at .*:\d+:\d+)"),
    ),
    ToolProfile(
        "go",
        re.compile(r"\bgo (test|vet|build)\b"),
        re.compile(r"^(ok|FAIL)\s+\S+\s+[\d.]+s"),
        re.compile(r"^(--- FAIL|FAIL|panic:|\s+\S+\.go:\d+:)"),
    ),
    ToolProfile(
        "cargo",
        re.compile(r"\bcargo (test|build|clippy|check)\b"),
        re.compile(r"^test result: "),
        re.compile(
            r"^(error(\[E\d+\])?:|warning: unused|---- .* stdout ----|thread '.*' panicked)"
        ),
    ),
    ToolProfile(
        "maven-gradle",
        re.compile(r"\b(mvn|mvnw|gradle|gradlew)\b"),
        re.compile(r"(BUILD (SUCCESS|FAILURE|SUCCESSFUL|FAILED)|Tests run: \d+, Failures: \d+)"),
        re.compile(r"(\[ERROR\]|FAILED|<<< FAIL|Caused by:|^\s+at [\w.$]+\(.*:\d+\))"),
    ),
    ToolProfile(
        "lint",
        re.compile(r"\b(tsc|eslint|ruff|mypy|flake8|pylint|golangci-lint)\b"),
        re.compile(r"^(Found \d+ errors?|\d+ problems?|✖ \d+ problems?|Success: no issues)"),
        re.compile(r"^\S+[:(]\d+[:,]\d*\)?:?\s|error TS\d+"),
    ),
)


def profile_for(command: str) -> ToolProfile | None:
    return next((profile for profile in PROFILES if profile.command.search(command)), None)


def clean_lines(text: str) -> list[str]:
    """Strips ANSI, carriage-return progress redraws, timestamps and progress bars."""
    lines: list[str] = []
    for raw in _ANSI.sub("", text).splitlines():
        line = _TIMESTAMP.sub("", raw.rsplit("\r", 1)[-1]).rstrip()
        if line and not _PROGRESS.search(line):
            lines.append(line)
    return lines


def _template(line: str) -> str:
    return _TEMPLATE_TOKENS.sub("#", line.strip())


def dedupe(lines: list[str]) -> list[str]:
    """Collapses runs of lines that differ only in numbers, hashes or paths."""
    out: list[str] = []
    run_template, run_count = "", 0
    for line in lines:
        template = _template(line)
        if out and template == run_template:
            run_count += 1
            continue
        if run_count:
            out.append(f"  … ×{run_count} similar lines")
        out.append(line)
        run_template, run_count = template, 0
    if run_count:
        out.append(f"  … ×{run_count} similar lines")
    return out


@dataclass(frozen=True)
class Condensed:
    text: str
    tool: str
    original_chars: int
    truncated: bool


def condense(
    text: str, command: str = "", exit_code: int | None = None, budget: int = DEFAULT_BUDGET
) -> Condensed:
    """Condenses ``text`` for an agent within ``budget`` characters."""
    profile = profile_for(command)
    tool = profile.name if profile else "generic"
    lines = clean_lines(text)
    summaries = [line for line in lines if profile and profile.summary.search(line)]

    # Only known tools have a trustworthy summary line; generic output (listings, logs)
    # keeps head, tail and deduped structure instead of collapsing to one line.
    if exit_code == 0 and profile is not None and len(text) > budget:
        head = summaries[-1] if summaries else (lines[-1] if lines else "")
        body = f"✓ {tool}: {head.strip('= ').strip()}" if head else f"✓ {tool}: ok"
        return Condensed(body, tool, len(text), True)
    if len(text) <= budget:
        return Condensed("\n".join(lines), tool, len(text), False)

    signal = profile.signal if profile else _GENERIC_SIGNAL
    keep: set[int] = set(range(min(3, len(lines))))
    keep.update(range(max(0, len(lines) - 8), len(lines)))
    for index, line in enumerate(lines):
        if signal.search(line) or _GENERIC_SIGNAL.search(line):
            keep.update(range(max(0, index - 2), min(len(lines), index + 7)))
        if line in summaries:
            keep.add(index)

    selected: list[str] = []
    previous = -1
    for index in sorted(keep):
        if index != previous + 1:
            selected.append(f"  … {index - previous - 1} lines omitted")
        selected.append(lines[index])
        previous = index
    if previous != len(lines) - 1:
        selected.append(f"  … {len(lines) - previous - 1} lines omitted")
    compact = dedupe(selected)

    # Budget: keep summaries and the earliest failures; the tail always survives.
    tail = compact[-8:]
    result: list[str] = []
    used = sum(len(line) + 1 for line in tail)
    for line in compact[:-8]:
        if used + len(line) + 1 > budget - 80:
            result.append("  … more failures omitted (use the saved log)")
            break
        result.append(line)
        used += len(line) + 1
    return Condensed("\n".join(result + tail), tool, len(text), True)
