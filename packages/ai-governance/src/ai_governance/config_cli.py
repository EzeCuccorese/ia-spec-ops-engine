"""``ai-governance config show``: the effective configuration and where each value came from."""

from __future__ import annotations

import argparse

from ._config_core import ConfigError, Value, render_show
from .settings import effective, repo_root


def _taskflow_controls() -> dict[str, Value]:
    """Judges, checks and risk rules in force, with who set them (user, default or a repo)."""
    from pathlib import Path

    from .taskflow.config import load_config

    origins: dict[str, tuple[str, str]] = {}
    root = repo_root() or Path.cwd()
    try:
        load_config([root], origins=origins)
    except (ConfigError, ValueError, OSError):
        return {}
    return {
        key: Value(state, state.split(" ")[0], source) for key, (state, source) in origins.items()
    }


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
    values.update(_taskflow_controls())
    print(render_show(values, origin=args.origin, as_json=args.json))
    return 0
