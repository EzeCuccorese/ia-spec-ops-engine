"""
workspace_engine.config.init_config — Auto-bootstrapping and configuration generator for SpecOps.
Generates project-local (.specops/config.json) or user-global (~/.config/specops/config.json) configurations.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

from rich.console import Console

console = Console()


def generate_default_config(project_name: str, domain: str, *, enterprise: bool = False) -> dict:
    """Returns a SpecOps configuration dictionary (minimal by default, or full enterprise profile)."""
    cfg = {
        "project_name": project_name,
        "domain": domain,
        "namespaces": ["core", "services", "tools"],
        "env_slugs": ["dev", "staging", "prod"],
        "repositories_dir_env_var": "PROJECT_REPOSITORIES_DIR",
        "local_envs_dir_name": "local-envs",
        "workspaces_dir_name": "workspaces",
        "toolkit_dir_name": "project-toolkit",
        "url_pattern": rf"https?://([a-z0-9-]+)\.(?:dev|prod)\.{re.escape(domain)}(/[^\s]*)?",
    }
    if enterprise:
        cfg["environments"] = [
            {
                "id": "dev",
                "cluster": "dev",
                "namespace": "dev",
                "label": "Local / Development",
                "description": [
                    "Local development environment.",
                    "Used for daily workflows, test suites, and microservices.",
                ],
            },
            {
                "id": "staging",
                "cluster": "staging",
                "namespace": "staging",
                "label": "Staging",
                "description": [
                    "Staging validation environment.",
                    "Reflects production configuration for pre-release verification.",
                ],
            },
            {
                "id": "prod",
                "cluster": "prod",
                "namespace": "production",
                "label": "Production",
                "description": [
                    "Production environment.",
                    "Restricted access; monitored and governed.",
                ],
            },
        ]
        cfg["artifact_registry_domain"] = "generic"
        cfg["vpn"] = {
            "config_dev": "~/project-dev.ovpn",
            "config_prod": "~/project-prd.ovpn",
            "session_name_dev": f"{project_name}-dev-session",
            "session_name_prod": f"{project_name}-prd-session",
            "internal_host": f"internal.service.{domain}",
            "validation_timeout": 3,
        }
    return cfg


def resolve_config_target(
    *,
    is_local: bool = False,
    is_global: bool = False,
    custom_path: Path | None = None,
    cwd: Path | None = None,
) -> Path:
    """Determines the target path for config.json based on scope flags."""
    if is_local and is_global:
        raise ValueError("Flags --local and --global are mutually exclusive.")

    if custom_path:
        return custom_path

    current_dir = cwd or Path.cwd()
    if is_local:
        return current_dir / ".specops" / "config.json"

    # Default to global configuration unless local was explicitly requested
    xdg_home = os.environ.get("XDG_CONFIG_HOME")
    if xdg_home:
        return Path(xdg_home) / "specops" / "config.json"
    return Path.home() / ".config" / "specops" / "config.json"


def init_config(
    *,
    is_local: bool = False,
    is_global: bool = False,
    custom_path: Path | None = None,
    project_name: str | None = None,
    domain: str | None = None,
    force: bool = False,
    non_interactive: bool = False,
    cwd: Path | None = None,
    enterprise: bool = False,
    devops: bool = False,
) -> Path:
    """Initializes a new SpecOps config.json file.

    Returns the Path to the written configuration file.
    """
    current_dir = cwd or Path.cwd()
    target = resolve_config_target(
        is_local=is_local, is_global=is_global, custom_path=custom_path, cwd=current_dir
    )

    if target.exists() and not force:
        if non_interactive or not sys.stdin.isatty():
            console.print(
                f"[yellow]⚠ Configuration already exists at [cyan]{target}[/cyan]. Use --force to overwrite.[/yellow]"
            )
            return target
        confirm = input(f"Configuration file {target} already exists. Overwrite? [y/N]: ").strip()
        if confirm.lower() not in ("y", "yes"):
            console.print("[dim]Aborted configuration initialization.[/dim]")
            return target

    # Resolve project name
    if not project_name:
        default_name = current_dir.name or "specops-project"
        if non_interactive or not sys.stdin.isatty():
            project_name = default_name
        else:
            prompt_name = input(f"Project name [{default_name}]: ").strip()
            project_name = prompt_name or default_name

    # Resolve domain
    if not domain:
        default_domain = "local.dev"
        if non_interactive or not sys.stdin.isatty():
            domain = default_domain
        else:
            prompt_domain = input(f"Base domain [{default_domain}]: ").strip()
            domain = prompt_domain or default_domain

    is_enterprise = enterprise or devops
    config_data = generate_default_config(project_name, domain, enterprise=is_enterprise)

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(config_data, indent=2) + "\n", encoding="utf-8")

    console.print(
        f"[bold green]✓[/bold green] Initialized SpecOps configuration at [bold cyan]{target}[/bold cyan]"
    )
    return target


def run_config_init(argv: list[str] | None = None) -> int:
    """CLI runner for `specops config init` and `ws config init`."""
    parser = argparse.ArgumentParser(
        prog="specops config init",
        description="Initialize SpecOps configuration (.specops/config.json or ~/.config/specops/config.json).",
    )
    scope_group = parser.add_mutually_exclusive_group()
    scope_group.add_argument(
        "--local",
        action="store_true",
        help="Initialize project-local configuration (.specops/config.json)",
    )
    scope_group.add_argument(
        "--global",
        dest="is_global",
        action="store_true",
        help="Initialize user-global configuration (~/.config/specops/config.json)",
    )
    parser.add_argument(
        "--enterprise",
        "--devops",
        dest="enterprise",
        action="store_true",
        help="Generate full enterprise configuration with environments, VPN, and ArtifactRegistry",
    )
    parser.add_argument(
        "--path",
        type=Path,
        default=None,
        help="Explicit custom destination path for config.json",
    )
    parser.add_argument(
        "--name",
        type=str,
        default=None,
        help="Project name (defaults to current directory name)",
    )
    parser.add_argument(
        "--domain",
        type=str,
        default=None,
        help="Project base domain (defaults to local.dev)",
    )
    parser.add_argument(
        "--yes",
        "-y",
        dest="non_interactive",
        action="store_true",
        help="Run non-interactively using defaults",
    )
    parser.add_argument(
        "--force",
        "-f",
        action="store_true",
        help="Overwrite existing configuration file without confirmation",
    )

    args = parser.parse_args(argv)

    try:
        init_config(
            is_local=args.local,
            is_global=args.is_global,
            custom_path=args.path,
            project_name=args.name,
            domain=args.domain,
            force=args.force,
            non_interactive=args.non_interactive,
            enterprise=args.enterprise,
        )
        return 0
    except Exception as exc:
        console.print(f"[bold red]Error initializing configuration:[/bold red] {exc}")
        return 1
