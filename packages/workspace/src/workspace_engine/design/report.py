"""workspace_engine.design.report — Human and JSON rendering for ``ws design``."""

from __future__ import annotations

from .config import DesignConfig
from .metrics import Violation

SCHEMA_VERSION = 1


def format_text(violations: list[Violation], config: DesignConfig, files: int) -> str:
    lines = [
        f"{v.path}:{v.start_line} {v.symbol} — {v.metric} {v.value} > {v.limit}" for v in violations
    ]
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
            }
            for v in violations
        ],
        "files": files,
    }
