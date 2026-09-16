#!/usr/bin/env python3
"""
workspace_engine.cli.load_env — Deterministic update of environment variables in YAML/dotenv config files.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from workspace_engine.utils import log_error, log_info, log_success


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


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Updates variables in GitOps or deployment YAML files."
    )
    parser.add_argument("--envs", required=True, help="Environments (comma-separated)")
    parser.add_argument("--services", required=True, help="Services (comma-separated)")
    parser.add_argument("--var", required=True, help="Variable name")
    parser.add_argument("--values", required=True, help="Values (comma-separated)")
    parser.add_argument(
        "--root", default=os.path.expanduser("~/projects/gitops/apps/apps"), help="Root directory"
    )
    parser.add_argument("--suffix", help="Optional suffix for values")
    args = parser.parse_args()

    envs = [e.strip() for e in args.envs.split(",")]
    services = [s.strip() for s in args.services.split(",")]
    values = [v.strip() for v in args.values.split(",")]
    key = args.var.strip()
    root_dir = Path(args.root)

    if args.suffix:
        values = [f"{v}{args.suffix}" for v in values]

    env_to_value = {envs[i]: values[i] for i in range(min(len(envs), len(values)))}

    for env in envs:
        yaml_path = root_dir / f"values.{env}.yaml"
        if env not in env_to_value:
            continue
        log_info(f"Processing environment {env}...")
        update_env_in_yaml(yaml_path, services, key, env_to_value[env])


if __name__ == "__main__":
    main()
