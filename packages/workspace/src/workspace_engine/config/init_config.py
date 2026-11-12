"""
workspace_engine.config.init_config — CLI handler for `ws config show`.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from workspace_engine.common import log_error


def add_config_arguments(parser: argparse.ArgumentParser) -> None:
    """Registers the `ws config show` subcommand and options on the given parser."""
    config_subparsers = parser.add_subparsers(dest="config_command", help="Config subcommands")

    p_show = config_subparsers.add_parser("show", help="Print the effective configuration")
    p_show.add_argument("--origin", action="store_true", help="Show where each value came from")
    p_show.add_argument("--json", action="store_true", help="Machine-readable output")


def _found_config_files(root: Path | None) -> list[Path]:
    from workspace_engine._config_core import xdg_dir
    from workspace_engine.settings import personal_repo_config_path

    found: list[Path] = []
    user_file = xdg_dir("config", "workspace") / "config.toml"
    if user_file.is_file():
        found.append(user_file)
    if root is not None:
        repo_file = root / ".workspace" / "config.toml"
        if repo_file.is_file():
            found.append(repo_file)
        personal_file = personal_repo_config_path(root)
        if personal_file.is_file():
            found.append(personal_file)
    return found


def _show(args: argparse.Namespace) -> int:
    """``ws config show``: effective workspace settings with their origin."""
    from workspace_engine._config_core import ConfigError, render_show
    from workspace_engine.settings import effective, repo_root

    root = repo_root()
    found_files = _found_config_files(root)

    try:
        values = effective(root)
    except (ConfigError, ValueError) as exc:
        log_error(str(exc))
        return 1

    if not getattr(args, "json", False):
        if found_files:
            print(f"Config files found ({len(found_files)}):")
            for f in found_files:
                print(f"  {f}")
            print()
        else:
            print("No config files found.\n")

    print(
        render_show(
            values, origin=getattr(args, "origin", False), as_json=getattr(args, "json", False)
        )
    )
    return 0


def run_config(args: argparse.Namespace) -> int:
    """Executes the `ws config` command from parsed CLI arguments."""
    config_command = getattr(args, "config_command", None) or "show"
    if config_command == "show":
        return _show(args)

    log_error(f"Unknown config subcommand: {config_command}")
    return 1
