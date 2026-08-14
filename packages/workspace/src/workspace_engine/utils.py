"""
workspace_engine.utils — Utilidades de terminal, colores, detección de entorno y procesos para Workspace Engine.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Optional, TextIO, Union

try:
    import fcntl
    _HAS_FCNTL = True
except ImportError:
    _HAS_FCNTL = False


# ==============================================================================
# Colores ANSI y Logging en Consola
# ==============================================================================

class Color:
    RED       = '\033[0;31m'
    GREEN     = '\033[0;32m'
    YELLOW    = '\033[1;33m'
    BLUE      = '\033[0;34m'
    MAGENTA   = '\033[0;35m'
    CYAN      = '\033[0;36m'
    WHITE     = '\033[1;37m'
    GRAY      = '\033[0;90m'
    BOLD      = '\033[1m'
    DIM       = '\033[2m'
    UNDERLINE = '\033[4m'
    RESET     = '\033[0m'
    END       = '\033[0m'

    HIGH_RED     = '\033[91m'
    HIGH_GREEN   = '\033[92m'
    HIGH_YELLOW  = '\033[93m'
    HIGH_BLUE    = '\033[94m'
    HIGH_MAGENTA = '\033[95m'
    HIGH_CYAN    = '\033[96m'
    HIGH_WHITE   = '\033[97m'


RED = Color.RED
GREEN = Color.GREEN
YELLOW = Color.YELLOW
BLUE = Color.BLUE
MAGENTA = Color.MAGENTA
CYAN = Color.CYAN
WHITE = Color.WHITE
GRAY = Color.GRAY
BOLD = Color.BOLD
DIM = Color.DIM
UNDERLINE = Color.UNDERLINE
RESET = Color.RESET
END = Color.END


def log_info(message: str, file: Optional[TextIO] = None) -> None:
    """Imprime un mensaje informativo en color azul."""
    target = file if file is not None else sys.stdout
    print(f"{Color.BLUE}ℹ {message}{Color.RESET}", file=target)


def log_success(message: str, file: Optional[TextIO] = None) -> None:
    """Imprime un mensaje de éxito en color verde."""
    target = file if file is not None else sys.stdout
    print(f"{Color.GREEN}✅ {message}{Color.RESET}", file=target)


def log_warning(message: str, file: Optional[TextIO] = None) -> None:
    """Imprime un mensaje de advertencia en color amarillo."""
    target = file if file is not None else sys.stdout
    print(f"{Color.YELLOW}⚠️ {message}{Color.RESET}", file=target)


def log_error(message: str, file: Optional[TextIO] = None) -> None:
    """Imprime un mensaje de error en color rojo."""
    target = file if file is not None else sys.stderr
    print(f"{Color.RED}❌ {message}{Color.RESET}", file=target)


def colorize(text: str, color: str) -> str:
    """Envuelve el texto con un código ANSI y resetea automáticamente."""
    return f"{color}{text}{Color.RESET}"


# ==============================================================================
# Ejecución de Comandos del Sistema
# ==============================================================================

def run_command(
    command: str,
    check: bool = True,
    capture_output: bool = True,
    show_command: bool = False,
    error_message: Optional[str] = None,
    shell: bool = False,
    env: Optional[dict] = None,
    cwd: Optional[Union[str, Path]] = None,
) -> Optional[str]:
    """Ejecuta un comando shell de forma determinista y retorna su salida."""
    if show_command:
        print(f"{Color.CYAN}🚀 Ejecutando: {command}{Color.RESET}")

    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)

    target_cmd = command
    if isinstance(command, str) and not shell:
        target_cmd = shlex.split(command)

    try:
        result = subprocess.run(
            target_cmd,
            shell=shell,
            check=check,
            text=True,
            stdout=subprocess.PIPE if capture_output else None,
            stderr=subprocess.PIPE if capture_output else None,
            env=merged_env,
            cwd=str(cwd) if cwd else None,
        )
        return result.stdout.strip() if capture_output else ""
    except subprocess.CalledProcessError as e:
        if error_message:
            log_error(error_message)
        if capture_output:
            log_error(f"Error ejecutando comando: {command}")
            if e.stderr:
                print(f"{Color.RED}{e.stderr.strip()}{Color.RESET}", file=sys.stderr)
        if check:
            raise
        return None
    except Exception as e:
        if error_message:
            log_error(error_message)
        log_error(f"Error inesperado: {str(e)}")
        if check:
            raise
        return None


# ==============================================================================
# Bloqueo de Archivos (File Locking)
# ==============================================================================

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


# ==============================================================================
# Búsqueda de Rutas y Parser de Entorno (.env)
# ==============================================================================

_EXPORT_PREFIX_RE = re.compile(r"^\s*export\s+")

def find_project_root(start_path: Optional[Path] = None) -> Path:
    """Encuentra la raíz del proyecto o workspace buscando .git o pyproject.toml."""
    current = Path(start_path or Path.cwd()).resolve()
    for parent in [current] + list(current.parents):
        if (parent / ".git").exists() or (parent / "pyproject.toml").exists():
            return parent
    return current


def parse_dotenv(dotenv_path: Path | str) -> Dict[str, str]:
    """Parsea un archivo .env a un diccionario de variables clave-valor."""
    env_vars: Dict[str, str] = {}
    path = Path(dotenv_path)
    if not path.is_file():
        return env_vars

    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return env_vars

    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, val = line.partition("=")
            key = _EXPORT_PREFIX_RE.sub("", key).strip()
            val = val.strip()
            if len(val) >= 2 and val[0] == val[-1] and val[0] in ('"', "'"):
                val = val[1:-1]
            env_vars[key] = val
    return env_vars


def resolve_local_env(repo_path: Path, repo_name: str) -> Optional[Path]:
    """Ubica el archivo .env de un repositorio específico dentro del workspace."""
    repo_path = Path(repo_path)
    repo_env = repo_path / ".env"
    if repo_env.is_file():
        return repo_env

    root = find_project_root(repo_path)
    workspace_env = root / "envs" / repo_name / ".env"
    if workspace_env.is_file():
        return workspace_env

    return None


# ==============================================================================
# Detector de Tecnologías y Tipos de Proyecto
# ==============================================================================

class ProjectType:
    SPRING_BOOT = "spring_boot"
    MAVEN = "maven"
    GRADLE = "gradle"
    GO = "go"
    NODE = "node"
    PYTHON = "python"
    UNKNOWN = "unknown"


def read_package_json(repo_path: Path) -> Optional[Dict[str, Any]]:
    """Parsea de forma segura package.json si existe."""
    pkg_file = repo_path / "package.json"
    if not pkg_file.is_file():
        return None
    try:
        with open(pkg_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def is_spring_boot_app(repo_path: Path) -> bool:
    """Determina si un repositorio es un microservicio Spring Boot Java."""
    if (repo_path / "src" / "main" / "resources" / "application.properties").is_file():
        return True
    if (repo_path / "src" / "main" / "resources" / "application.yml").is_file():
        return True
    if (repo_path / "src" / "main" / "resources" / "application.yaml").is_file():
        return True
    return False


def is_go_service(repo_path: Path) -> bool:
    """Determina si un repositorio es un servicio en Go."""
    return (repo_path / "go.mod").is_file()


def detect_fe_framework(repo_path: Path) -> Optional[str]:
    """Detecta el framework frontend (React, Next.js, Vue, Angular, Vite)."""
    pkg = read_package_json(repo_path)
    if not pkg:
        return None
    deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
    if "next" in deps:
        return "next"
    if "react" in deps or "react-dom" in deps:
        return "react"
    if "vue" in deps:
        return "vue"
    if "@angular/core" in deps:
        return "angular"
    if "vite" in deps:
        return "vite"
    return "node"


def detect_project_type(repo_path: Path) -> str:
    """Identifica la tecnología o build system principal de un proyecto."""
    repo_path = Path(repo_path)
    if is_spring_boot_app(repo_path):
        return ProjectType.SPRING_BOOT
    if (repo_path / "gradlew").is_file() or (repo_path / "build.gradle").is_file() or (repo_path / "build.gradle.kts").is_file():
        return ProjectType.GRADLE
    if (repo_path / "pom.xml").is_file():
        return ProjectType.MAVEN
    if is_go_service(repo_path):
        return ProjectType.GO
    if (repo_path / "package.json").is_file():
        return ProjectType.NODE
    if (repo_path / "pyproject.toml").is_file() or (repo_path / "requirements.txt").is_file():
        return ProjectType.PYTHON
    return ProjectType.UNKNOWN
