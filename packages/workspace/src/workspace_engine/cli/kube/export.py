"""
workspace_engine.cli.kube.export — Secure environment variable exporter with 0o600 permissions.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

from workspace_engine.common import log_success


def write_secret_file(file_path: Path | str, content: str) -> None:
    """
    Writes a secrets file (.env, set-env.sh) and assigns it
    strict 0o600 permissions (read/write for the owner only).
    """
    p = Path(file_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    os.chmod(p, stat.S_IRUSR | stat.S_IWUSR)


def export_dotenv(target_path: Path | str, env_vars: dict[str, str]) -> None:
    """Exports the variables to .env format with secure permissions."""
    lines = [f"{k}={v}" for k, v in sorted(env_vars.items())]
    content = "\n".join(lines) + "\n"
    write_secret_file(target_path, content)
    log_success(f".env file exported securely (chmod 600) to: {target_path}")


def export_set_env_sh(target_path: Path | str, env_vars: dict[str, str]) -> None:
    """Exports the variables to bash format with 'export' and 600 permissions."""
    lines = ["#!/usr/bin/env bash", ""]
    for k, v in sorted(env_vars.items()):
        # Escape double quotes if present
        clean_v = v.replace('"', '\\"')
        lines.append(f'export {k}="{clean_v}"')
    lines.append("")
    content = "\n".join(lines)
    write_secret_file(target_path, content)
    log_success(f"set-env.sh script exported securely (chmod 600) to: {target_path}")
