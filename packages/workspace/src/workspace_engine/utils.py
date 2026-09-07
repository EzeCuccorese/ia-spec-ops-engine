"""
workspace_engine.utils — Utilidades de terminal, colores, detección de entorno y procesos para Workspace Engine.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

try:
    import fcntl

    _HAS_FCNTL = True
except ImportError:
    _HAS_FCNTL = False

import contextlib

from workspace_engine.common import (
    BLUE,
    BOLD,
    CYAN,
    DEFAULT_COMMAND_TIMEOUT,
    DIM,
    END,
    GRAY,
    GREEN,
    MAGENTA,
    RED,
    RESET,
    UNDERLINE,
    WHITE,
    YELLOW,
    Color,
    ProjectType,
    colorize,
    console,
    detect_fe_framework,
    detect_project_type,
    err_console,
    find_project_root,
    is_go_service,
    is_rust_service,
    is_spring_boot_app,
    log_error,
    log_info,
    log_success,
    log_warning,
    parse_dotenv,
    parse_frontmatter,
    read_package_json,
    run_command,
    run_command_safe,
)


class FileLock:
    """Context manager para bloqueo seguro de archivos en operaciones atómicas."""

    def __init__(self, lock_file_path: str | Path):
        self.lock_file_path = Path(lock_file_path)
        self._fd = None

    def __enter__(self) -> FileLock:
        self.lock_file_path.parent.mkdir(parents=True, exist_ok=True)
        self._fd = open(self.lock_file_path, "w")
        if _HAS_FCNTL:
            fcntl.flock(self._fd.fileno(), fcntl.LOCK_EX)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._fd:
            if _HAS_FCNTL:
                with contextlib.suppress(OSError):
                    fcntl.flock(self._fd.fileno(), fcntl.LOCK_UN)
            self._fd.close()
            self._fd = None


def run_git(repo_path: str | Path, *args: str) -> subprocess.CompletedProcess:
    """Ejecuta comandos git de forma hermética, aislando variables ambientales de subshells."""
    clean_env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    clean_env["GIT_CONFIG_GLOBAL"] = "/dev/null"
    clean_env["GIT_CONFIG_SYSTEM"] = "/dev/null"
    clean_env.setdefault("GIT_AUTHOR_NAME", "Workspace User")
    clean_env.setdefault("GIT_AUTHOR_EMAIL", "workspace@example.com")
    clean_env.setdefault("GIT_COMMITTER_NAME", "Workspace User")
    clean_env.setdefault("GIT_COMMITTER_EMAIL", "workspace@example.com")
    return subprocess.run(
        ["git", "-C", str(repo_path)] + list(args),
        capture_output=True,
        text=True,
        env=clean_env,
    )


def resolve_local_env(repo_path: Path | str, repo_name: str) -> Path | None:
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


__all__ = [
    "BLUE",
    "BOLD",
    "CYAN",
    "DEFAULT_COMMAND_TIMEOUT",
    "DIM",
    "END",
    "FileLock",
    "GRAY",
    "GREEN",
    "MAGENTA",
    "RED",
    "RESET",
    "UNDERLINE",
    "WHITE",
    "YELLOW",
    "Color",
    "ProjectType",
    "colorize",
    "console",
    "detect_fe_framework",
    "detect_project_type",
    "err_console",
    "find_project_root",
    "is_go_service",
    "is_rust_service",
    "is_spring_boot_app",
    "log_error",
    "log_info",
    "log_success",
    "log_warning",
    "parse_dotenv",
    "parse_frontmatter",
    "read_package_json",
    "resolve_local_env",
    "run_command",
    "run_command_safe",
    "run_git",
]
