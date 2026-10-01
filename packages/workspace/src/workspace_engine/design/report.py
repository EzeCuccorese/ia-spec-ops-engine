"""workspace_engine.design.report — Human and JSON rendering for ``ws design``."""

from __future__ import annotations

from .config import DesignConfig
from .metrics import FUNCTION_METRICS, FunctionMetrics, Violation

SCHEMA_VERSION = 1

HINTS = {
    "complexity": "extract branches into named functions / guard clauses",
    "length": "extract steps into well-named functions",
    "args": "introduce a parameter object",
    "nesting": "return early, extract inner blocks",
    "layers": "depend on a port (interface) in the inner layer; implement it in the outer layer",
    "empty-catch": "handle, rethrow with context, or log with a reason",
    "todo-ticket": "add a ticket reference or do it now",
    "commented-code": "delete it — version control remembers",
    "test-no-assert": "assert the observable result or delete the test",
    "test-trivial-assert": "assert real behavior; this can never fail",
    "test-mock-only": "assert the result or state, not only the calls",
    "test-sleep": "inject a clock or poll with a timeout",
    "test-duplicate": "merge into one parametrized test",
}

BLOCKING_HEADER = "Blocking"
PREEXISTING_HEADER = "Pre-existing (not blocking)"
PREEXISTING_FOOTER = "Fix one at a time, surgically: ws design --focus <path:line>"

_FOCUS_SOURCE_CAP = 120


def _violation_line(v: Violation) -> str:
    was = ""
    if v.base_value is not None:
        delta = f", {v.value - v.base_value:+d}" if v.worsened else ""
        was = f" (was {v.base_value}{delta})"
    return (
        f"{v.path}:{v.start_line}-{v.end_line} {v.symbol} — "
        f"{v.metric} {v.value} > {v.limit}{was} → {HINTS[v.metric]}"
    )


def _summary(violations: list[Violation]) -> str:
    """One line for the pre-existing violations that are not listed individually."""
    functions = {
        (v.path, v.symbol, v.start_line) for v in violations if v.metric in FUNCTION_METRICS
    }
    lines = len(violations) - sum(1 for v in violations if v.metric in FUNCTION_METRICS)
    parts = []
    if functions:
        parts.append(
            f"{len(functions)} pre-existing functions over the limits in touched files — "
            "see ws design --focus <path:line>"
        )
    if lines:
        parts.append(f"{lines} pre-existing line-based findings outside the changed lines")
    return "\n".join(parts)


def _blocking_lines(blocking: list[Violation]) -> list[str]:
    if not blocking:
        return []
    return [BLOCKING_HEADER, *(_violation_line(v) for v in blocking)]


def _warning_lines(warnings: list[Violation], verbose: bool) -> list[str]:
    """Worsened legacy first, then touched legacy; untouched legacy only when verbose."""
    if not warnings:
        return []
    listed = [v for v in warnings if verbose or v.base_value is not None]
    listed.sort(key=lambda v: not v.worsened)  # stable: worsened first
    lines = [PREEXISTING_HEADER, *(_violation_line(v) for v in listed)]
    folded = [v for v in warnings if v not in listed]
    if folded:
        lines.append(_summary(folded))
    if listed:
        lines.append(PREEXISTING_FOOTER)
    return lines


def _verdict(blocking: list[Violation], warnings: list[Violation], files: int, mode: str) -> str:
    if not blocking:
        extra = f", {len(warnings)} pre-existing warning(s)" if warnings else ""
        return f"✔ design: PASS ({files} files{extra})"
    functions = len({(v.path, v.symbol, v.start_line) for v in blocking})
    summary = f"✘ design: {len(blocking)} blocking violation(s) in {functions} function(s)"
    return f"⚠ {summary}" if mode == "warn" else summary


def format_text(
    violations: list[Violation], config: DesignConfig, files: int, verbose: bool = True
) -> str:
    """Renders the report. ``verbose=False`` folds untouched legacy into one summary line."""
    blocking = [v for v in violations if v.blocking]
    warnings = [v for v in violations if not v.blocking]
    sections = [s for s in (_blocking_lines(blocking), _warning_lines(warnings, verbose)) if s]
    lines: list[str] = []
    for section in sections:
        lines.extend(([""] if lines else []) + section)
    lines.append(_verdict(blocking, warnings, files, config.mode))
    return "\n".join(lines)


def to_dict(violations: list[Violation], config: DesignConfig, files: int) -> dict[str, object]:
    blocking = any(v.blocking for v in violations)
    status = (
        "pass" if not violations else ("fail" if blocking and config.mode == "block" else "warn")
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "violations": [
            {
                "path": v.path,
                "symbol": v.symbol,
                "start_line": v.start_line,
                "end_line": v.end_line,
                "metric": v.metric,
                "value": v.value,
                "limit": v.limit,
                "origin": v.origin,
                "blocking": v.blocking,
                "base_value": v.base_value,
            }
            for v in violations
        ],
        "files": files,
    }


def format_focus(fm: FunctionMetrics, config: DesignConfig, source: str) -> str:
    """A focused brief for one function: metrics vs. limits, hints, numbered source."""
    checks: list[tuple[str, int, int]] = [
        ("complexity", fm.complexity, config.max_complexity),
        ("length", fm.length, config.max_function_lines),
        ("args", fm.args, config.max_args),
    ]
    if fm.nesting is not None:
        checks.append(("nesting", fm.nesting, config.max_nesting))

    lines = [f"{fm.path}:{fm.start_line}-{fm.end_line} {fm.symbol}", ""]
    failing = [metric for metric, value, limit in checks if value > limit]
    for metric, value, limit in checks:
        status = "FAIL" if value > limit else "ok"
        lines.append(f"  {metric}: {value} (limit {limit}) [{status}]")
    lines.append("")
    if failing:
        lines.append("Hints:")
        lines.extend(f"  {metric} → {HINTS[metric]}" for metric in failing)
    else:
        lines.append("Within limits.")

    lines.append("")
    lines.append("Source:")
    body = source.splitlines()[fm.start_line - 1 : fm.end_line]
    shown = body[:_FOCUS_SOURCE_CAP]
    width = len(str(fm.start_line + len(shown) - 1)) if shown else len(str(fm.start_line))
    lines.extend(f"{fm.start_line + i:>{width}} | {text}" for i, text in enumerate(shown))
    if len(body) > _FOCUS_SOURCE_CAP:
        lines.append(f"  … {len(body) - _FOCUS_SOURCE_CAP} more line(s) omitted")
    return "\n".join(lines)
