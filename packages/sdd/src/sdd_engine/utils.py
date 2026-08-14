"""
sdd_engine.utils — Utilidades privadas para sdd_engine (colores, logging, ejecución de comandos, búsqueda de raíz y detección de proyectos).
"""

from __future__ import annotations

import os
import subprocess
import sys
from enum import Enum
from pathlib import Path
from typing import Optional, Tuple


class Color:
    RED = '\033[0;31m'
    GREEN = '\033[0;32m'
    YELLOW = '\033[1;33m'
    BLUE = '\033[0;34m'
    MAGENTA = '\033[0;35m'
    CYAN = '\033[0;36m'
    BOLD = '\033[1m'
    DIM = '\033[2m'
    RESET = '\033[0m'


def log_info(msg: str) -> None:
    print(f"{Color.CYAN}ℹ {msg}{Color.RESET}")


def log_success(msg: str) -> None:
    print(f"{Color.GREEN}✔ {msg}{Color.RESET}")


def log_warning(msg: str) -> None:
    print(f"{Color.YELLOW}⚠ {msg}{Color.RESET}")


def log_error(msg: str) -> None:
    print(f"{Color.RED}✖ {msg}{Color.RESET}", file=sys.stderr)


def find_project_root(start_dir: Optional[Path] = None) -> Path:
    """Busca el directorio raíz del proyecto (.specify, .git, pyproject.toml)."""
    curr = (start_dir or Path.cwd()).resolve()
    for parent in [curr] + list(curr.parents):
        if (parent / ".specify").is_dir() or (parent / ".git").exists() or (parent / "pyproject.toml").is_file():
            return parent
    return curr


def run_command_safe(
    cmd: list[str],
    cwd: Optional[Path] = None,
    env: Optional[dict] = None,
) -> Tuple[int, str, str]:
    """Ejecuta un comando de forma segura retornando (returncode, stdout, stderr)."""
    try:
        res = subprocess.run(cmd, cwd=str(cwd) if cwd else None, env=env, capture_output=True, text=True)
        return res.returncode, res.stdout, res.stderr
    except Exception as e:
        return 1, "", str(e)



class ProjectType(str, Enum):
    GRADLE = "gradle"
    MAVEN = "maven"
    SPRING_BOOT = "spring_boot"
    NODE = "node"
    PYTHON = "python"
    GO = "go"
    UNKNOWN = "unknown"



def detect_project_type(root_dir: Path) -> ProjectType:
    """Detecta el tipo de proyecto analizando la presencia de archivos clave."""
    p = Path(root_dir)
    if (p / "gradlew").is_file() or (p / "build.gradle").is_file() or (p / "build.gradle.kts").is_file():
        return ProjectType.GRADLE
    if (p / "pom.xml").is_file():
        return ProjectType.MAVEN
    if (p / "package.json").is_file():
        return ProjectType.NODE
    if (p / "go.mod").is_file():
        return ProjectType.GO
    if (p / "pyproject.toml").is_file() or (p / "requirements.txt").is_file() or (p / "setup.py").is_file():
        return ProjectType.PYTHON
    return ProjectType.UNKNOWN
