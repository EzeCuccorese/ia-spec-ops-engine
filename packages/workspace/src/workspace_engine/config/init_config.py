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
    cfg: dict[str, object] = {
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
        from workspace_engine.run_local.constants import find_project_root

        root = find_project_root(current_dir)
        return root / ".specops" / "config.json"

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
        from workspace_engine.run_local.constants import find_project_root

        resolved_root = find_project_root(current_dir) if is_local else current_dir
        default_name = resolved_root.name or current_dir.name or "specops-project"
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


def add_config_arguments(parser: argparse.ArgumentParser) -> None:
    """Registers the real `ws config` subcommands and options on the given parser.

    Called from `cli.main` so that `ws config --help` / `ws config init --help`
    show the actual accepted arguments instead of an opaque REMAINDER blob.
    """
    config_subparsers = parser.add_subparsers(dest="config_command", help="Config subcommands")

    p_init = config_subparsers.add_parser(
        "init",
        help="Initialize SpecOps configuration (.specops/config.json or ~/.config/specops/config.json)",
    )
    scope_group = p_init.add_mutually_exclusive_group()
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
    p_init.add_argument(
        "--enterprise",
        "--devops",
        dest="enterprise",
        action="store_true",
        help="Generate full enterprise configuration with environments, VPN, and ArtifactRegistry",
    )
    p_init.add_argument(
        "--path",
        type=Path,
        default=None,
        help="Explicit custom destination path for config.json",
    )
    p_init.add_argument(
        "--name",
        type=str,
        default=None,
        help="Project name (defaults to current directory name)",
    )
    p_init.add_argument(
        "--domain",
        type=str,
        default=None,
        help="Project base domain (defaults to local.dev)",
    )
    p_init.add_argument(
        "--yes",
        "-y",
        dest="non_interactive",
        action="store_true",
        help="Run non-interactively using defaults",
    )
    p_init.add_argument(
        "--force",
        "-f",
        action="store_true",
        help="Overwrite existing configuration file without confirmation",
    )


def run_config(args: argparse.Namespace) -> int:
    """Executes the `ws config` command from parsed CLI arguments.

    `args.config_command` is `None` when `ws config` is invoked with no
    subcommand (defaults to `init` for backward-compatible behaviour).
    """
    config_command = getattr(args, "config_command", None) or "init"

    if config_command == "init":
        try:
            init_config(
                is_local=getattr(args, "local", False),
                is_global=getattr(args, "is_global", False),
                custom_path=getattr(args, "path", None),
                project_name=getattr(args, "name", None),
                domain=getattr(args, "domain", None),
                force=getattr(args, "force", False),
                non_interactive=getattr(args, "non_interactive", False),
                enterprise=getattr(args, "enterprise", False),
            )
            return 0
        except (OSError, ValueError) as exc:
            console.print(f"[bold red]Error initializing configuration:[/bold red] {exc}")
            return 1

    console.print(f"[bold red]Unknown config subcommand:[/bold red] {config_command}")
    return 1


def run_config_init(argv: list[str] | None = None) -> int:
    """Backward-compatible CLI runner kept for callers/tests invoking `ws config init`
    directly with a raw argv list (e.g. ``["init", "--local", "--yes"]``).
    """
    parser = argparse.ArgumentParser(prog="ws config")
    add_config_arguments(parser)
    args = parser.parse_args(argv)
    return run_config(args)
