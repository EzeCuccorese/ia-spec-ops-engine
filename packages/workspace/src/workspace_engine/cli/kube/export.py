"""
workspace_engine.cli.kube.export — Exportador seguro de variables de entorno con permisos 0o600.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Dict, Optional

from workspace_engine.common import log_info, log_success, log_error


def write_secret_file(file_path: Path | str, content: str) -> None:
    """
    Escribe un archivo de secretos (.env, set-env.sh) y le asigna
    permisos estrictos 0o600 (solo lectura/escritura para el dueño).
    """
    p = Path(file_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    os.chmod(p, stat.S_IRUSR | stat.S_IWUSR)


def export_dotenv(target_path: Path | str, env_vars: Dict[str, str]) -> None:
    """Exporta las variables a formato .env con permisos seguros."""
    lines = [f"{k}={v}" for k, v in sorted(env_vars.items())]
    content = "\n".join(lines) + "\n"
    write_secret_file(target_path, content)
    log_success(f"Archivo .env exportado de forma segura (chmod 600) en: {target_path}")


def export_set_env_sh(target_path: Path | str, env_vars: Dict[str, str]) -> None:
    """Exporta las variables a formato bash con 'export' y permisos 600."""
    lines = ["#!/usr/bin/env bash", ""]
    for k, v in sorted(env_vars.items()):
        # Escapar comillas dobles si las hay
        clean_v = v.replace('"', '\\"')
        lines.append(f'export {k}="{clean_v}"')
    lines.append("")
    content = "\n".join(lines)
    write_secret_file(target_path, content)
    log_success(f"Script set-env.sh exportado de forma segura (chmod 600) en: {target_path}")
