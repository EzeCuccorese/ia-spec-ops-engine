#!/usr/bin/env python3
"""
workspace_engine.cli.load_env — Deterministic update of environment variables in YAML/dotenv config files.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from workspace_engine.common import log_error, log_info, log_success


def update_env_in_yaml(yaml_path: Path, services: list[str], key: str, value: str) -> bool:
    if not yaml_path.is_file():
        log_error(f"File not found: {yaml_path}")
        return False

    try:
        from ruamel.yaml import YAML
        from ruamel.yaml.error import YAMLError

        yaml = YAML()
        yaml.preserve_quotes = True
        yaml.indent(mapping=2, sequence=4, offset=2)
        yaml.width = 4096

        with open(yaml_path, encoding="utf-8") as f:
            data = yaml.load(f)

        updated = False
        for app in data.get("apps", []):
            if app.get("name") in services:
                if "configMapProperties" not in app or app["configMapProperties"] is None:
                    app["configMapProperties"] = {}
                if app["configMapProperties"].get(key) != value:
                    app["configMapProperties"][key] = value
                    updated = True
                    log_success(f"  Updated {app['name']}")

        if updated:
            with open(yaml_path, "w", encoding="utf-8") as f:
                yaml.dump(data, f)
            log_success(f"  Saved to {yaml_path}")
            return True
        else:
            log_info("  No changes required.")
            return True
    except (OSError, YAMLError, AttributeError, KeyError) as e:
        log_error(f"Error processing YAML {yaml_path}: {e}")
        return False


def _update_envs(
    root_dir: Path, env_to_value: dict[str, str], services: list[str], key: str
) -> bool:
    """Updates ``values.<env>.yaml`` for every env; False when any of them failed."""
    all_ok = True
    for env, value in env_to_value.items():
        log_info(f"Processing environment {env}...")
        yaml_path = root_dir / f"values.{env}.yaml"
        if not update_env_in_yaml(yaml_path, services, key, value):
            all_ok = False
    return all_ok


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="ws env-load", description="Updates variables in GitOps or deployment YAML files."
    )
    parser.add_argument("--envs", required=True, help="Environments (comma-separated)")
    parser.add_argument("--services", required=True, help="Services (comma-separated)")
    parser.add_argument("--var", required=True, help="Variable name")
    parser.add_argument("--values", required=True, help="Values (comma-separated)")
    parser.add_argument(
        "--root", default=os.path.expanduser("~/projects/gitops/apps/apps"), help="Root directory"
    )
    parser.add_argument("--suffix", help="Optional suffix for values")
    args = parser.parse_args(argv)

    envs = [e.strip() for e in args.envs.split(",")]
    services = [s.strip() for s in args.services.split(",")]
    values = [v.strip() for v in args.values.split(",")]
    key = args.var.strip()
    root_dir = Path(args.root).expanduser()

    if args.suffix:
        values = [f"{v}{args.suffix}" for v in values]

    if len(envs) != len(values):
        log_error(
            f"--envs and --values differ: {len(envs)} environment(s) but {len(values)} value(s)."
        )
        sys.exit(1)
    env_to_value = dict(zip(envs, values, strict=True))

    if not _update_envs(root_dir, env_to_value, services, key):
        sys.exit(1)


if __name__ == "__main__":
    main()
