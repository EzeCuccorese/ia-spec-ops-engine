"""``ai-governance config show``: the effective configuration and where each value came from."""

from __future__ import annotations

import argparse
import sys

from ._config_core import ConfigError, Value, render_show
from .settings import effective, repo_root, retired_rows


def _taskflow_rows() -> tuple[dict[str, Value], str]:
    """Exactly what ``taskflow.config.load_config`` resolves, with the origin of each value;
    when that fails, no rows and the reason (never a successful unrestricted view)."""
    from pathlib import Path

    from .taskflow.config import describe_config

    try:
        return describe_config([repo_root() or Path.cwd()]), ""
    except (ConfigError, ValueError, OSError) as exc:
        return {}, str(exc)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="ai-governance config")
    sub = parser.add_subparsers(dest="action", required=True)
    show = sub.add_parser("show", help="Print the effective configuration")
    show.add_argument("--origin", action="store_true", help="Show the layer each value came from")
    show.add_argument("--json", action="store_true", help="Machine-readable output")
    args = parser.parse_args(argv)
    try:
        values = effective()
    except ConfigError as exc:
        print(f"Error: {exc}")
        return 1
    rows, failure = _taskflow_rows()
    values.update(retired_rows())
    values.update(rows)
    print(render_show(values, origin=args.origin, as_json=args.json))
    if failure:
        print(f"Error: {failure}", file=sys.stderr)
        return 1
    blocked = values.get("taskflow.allowed_agents")
    if blocked is not None and blocked.origin == "blocked":
        print(f"Error: {blocked.source}", file=sys.stderr)
        return 1
    return 0
