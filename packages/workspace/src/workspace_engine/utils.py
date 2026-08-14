"""
workspace_engine.utils — Utilidades de terminal, colores, detección de entorno y procesos para Workspace Engine.
Re-exporta y extiende utilidades de devscripts_common para mantener compatibilidad.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, Optional, Union

try:
    import fcntl
    _HAS_FCNTL = True
except ImportError:
    _HAS_FCNTL = False

from devscripts_common import (
    Color,
    RED,
    GREEN,
    YELLOW,
    BLUE,
    MAGENTA,
    CYAN,
    WHITE,
    GRAY,
    BOLD,
    DIM,
    UNDERLINE,
    RESET,
    END,
    log_info,
    log_success,
    log_warning,
    log_error,
    colorize,
    parse_dotenv,
    find_project_root,
    detect_project_type,
    read_package_json,
    is_spring_boot_app,
    is_go_service,
    detect_fe_framework,
    ProjectType,
    run_command,
    run_command_safe,
)


class FileLock:
    """Context manager para bloqueo seguro de archivos en operaciones atómicas."""

    def __init__(self, lock_file_path: Union[str, Path]):
        self.lock_file_path = Path(lock_file_path)
        self._fd = None

    def __enter__(self) -> FileLock:
        self.lock_file_path.parent.mkdir(parents=True, exist_ok=True)
        self._fd = open(self.lock_file_path, 'w')
        if _HAS_FCNTL:
            fcntl.flock(self._fd.fileno(), fcntl.LOCK_EX)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._fd:
            if _HAS_FCNTL:
                try:
                    fcntl.flock(self._fd.fileno(), fcntl.LOCK_UN)
                except OSError:
                    pass
            self._fd.close()
            self._fd = None


def resolve_local_env(repo_path: Union[Path, str], repo_name: str) -> Optional[Path]:
    """Ubica el archivo .env de un repositorio específico dentro del workspace."""
    p = Path(repo_path)
    repo_env = p / ".env"
    if repo_env.is_file():
        return repo_env

    root = find_project_root(p)
    workspace_env = root / "envs" / repo_name / ".env"
    if workspace_env.is_file():
        return workspace_env

    return None
