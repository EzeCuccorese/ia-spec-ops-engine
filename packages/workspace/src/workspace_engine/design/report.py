"""workspace_engine.design.report — Human and JSON rendering for ``ws design``."""

from __future__ import annotations

from .config import DesignConfig
from .metrics import FunctionMetrics, Violation

SCHEMA_VERSION = 1

HINTS = {
    "complexity": "extract branches into named functions / guard clauses",
    "length": "extract steps into well-named functions",
    "args": "introduce a parameter object",
    "nesting": "return early, extract inner blocks",
    "layers": "depend on a port (interface) in the inner layer; implement it in the outer layer",
}

NEW_HEADER = "New code"
LEGACY_HEADER = (
    "Pre-existing code — surgical fix: change only this function, keep behavior, "
    "add a characterization test first"
)
LEGACY_FOOTER = "Fix one at a time: ws design --focus <path:line>"

_FOCUS_SOURCE_CAP = 120


def _violation_line(v: Violation) -> str:
    return (
        f"{v.path}:{v.start_line}-{v.end_line} {v.symbol} — "
        f"{v.metric} {v.value} > {v.limit} → {HINTS[v.metric]}"
    )


def format_text(violations: list[Violation], config: DesignConfig, files: int) -> str:
    new = [v for v in violations if v.origin == "new"]
    legacy = [v for v in violations if v.origin == "legacy"]
    lines: list[str] = []
    if new:
        lines.append(NEW_HEADER)
        lines.extend(_violation_line(v) for v in new)
    if legacy:
        if lines:
            lines.append("")
        lines.append(LEGACY_HEADER)
        lines.extend(_violation_line(v) for v in legacy)
        lines.append(LEGACY_FOOTER)
    functions = len({(v.path, v.symbol, v.start_line) for v in violations})
    if violations:
        summary = f"✘ design: {len(violations)} violation(s) in {functions} function(s)"
        if config.mode == "warn":
            summary = f"⚠ {summary}"
        lines.append(summary)
    else:
        lines.append(f"✔ design: PASS ({files} files)")
    return "\n".join(lines)


def to_dict(violations: list[Violation], config: DesignConfig, files: int) -> dict[str, object]:
    status = "pass" if not violations else ("warn" if config.mode == "warn" else "fail")
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
