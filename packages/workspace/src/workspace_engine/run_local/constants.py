"""
workspace_engine.run_local.constants — Constants, paths, and configuration for run_local.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from workspace_engine.common import Color

# ── ANSI Colors ───────────────────────────────────────────────────────────────
RED = Color.RED
GREEN = Color.GREEN
CYAN = Color.CYAN
YELLOW = Color.YELLOW
BOLD = Color.BOLD
DIM = Color.DIM
RESET = Color.RESET

# ── Directories and Files ─────────────────────────────────────────────────────
CONFIG_DIR = Path.home() / ".config" / "run-local"
DATA_DIR = Path.home() / ".local" / "share" / "run-local"
LOGS_DIR = DATA_DIR / "logs"
PIDS_DIR = DATA_DIR / "pids"
ENVS_DIR = DATA_DIR / "envs"
STATE_FILE = DATA_DIR / "state.json"
DB_CFG_FILE = CONFIG_DIR / "databases.yml"
PROFILES_FILE = CONFIG_DIR / "profiles.json"
LAST_CONFIGS_FILE = DATA_DIR / "last-configs.json"

LOG_MAX_BYTES = 100 * 1024 * 1024  # rotate log when it exceeds 100 MB
LOG_KEEP_BYTES = 20 * 1024 * 1024  # keep last 20 MB after rotation

# ── Project Configuration ──────────────────────────────────────────────────────
_CONFIG_LOADED = False


def find_project_root(
    start_dir: Path | None = None,
    boundary: Path | None = None,
) -> Path:
    """Walks upwards from start_dir (default: Path.cwd()) looking for a directory containing .workspace or .git.

    Does not escape into Path.home() or root filesystem when boundary is reached or when .git in $HOME is encountered.
    """
    current = Path(start_dir or Path.cwd()).resolve()
    if current.is_file():
        current = current.parent

    boundary_path = Path(boundary).resolve() if boundary is not None else None
    try:
        home_path = Path.home().resolve()
    except (OSError, RuntimeError):
        home_path = None
    try:
        import pwd

        real_home = Path(pwd.getpwuid(os.getuid()).pw_dir).resolve()
    except (OSError, KeyError):
        real_home = None

    def _is_home_or_root(p: Path) -> bool:
        if p == Path("/"):
            return True
        if home_path is not None and p == home_path:
            return True
        if real_home is not None and p == real_home:
            return True
        return p.parent in (Path("/Users"), Path("/home"), Path("/root"), Path("/var/root"))

    for parent in [current, *current.parents]:
        # If boundary is set, do not search beyond boundary
        if boundary_path is not None and (
            parent != boundary_path and not parent.is_relative_to(boundary_path)
        ):
            break

        # Stop before escaping user home or filesystem root if not starting directory
        if current != parent and _is_home_or_root(parent):
            break

        if (parent / ".workspace").exists() or (parent / ".git").exists():
            return parent

        if boundary_path is not None and parent == boundary_path:
            break

    return current


def config_candidates(root: Path) -> list[Path]:
    """Config files searched for ``root``, in order; the first that exists is used."""
    candidate_paths = [root / ".workspace" / "config.json"]
    if "XDG_CONFIG_HOME" in os.environ:
        candidate_paths.append(Path(os.environ["XDG_CONFIG_HOME"]) / "workspace" / "config.json")
    candidate_paths.append(Path.home() / ".config" / "workspace" / "config.json")
    candidate_paths.append(root / "config.json")
    return candidate_paths


def load_project_config(
    start_dir: Path | None = None,
    *,
    config_path: Path | None = None,
    custom_path: Path | None = None,
) -> dict:
    global _CONFIG_LOADED
    default_config = {
        "project_name": "generic",
        "domain": "generic.com",
        "namespaces": [],
        "environments": [],
        "repositories_dir_env_var": "PROJECT_REPOSITORIES_DIR",
        "local_envs_dir_name": "local-envs",
        "workspaces_dir_name": "workspaces",
        "toolkit_dir_name": "project-toolkit",
        "url_pattern": r"https?://([a-z0-9-]+)\.(?:dev|prod)\.generic\.com(/[\S]*)?",
    }

    explicit_path = config_path or custom_path
    target_path: Path | None
    if explicit_path is not None:
        target_path = Path(explicit_path).resolve()
        if not target_path.exists():
            raise FileNotFoundError(f"Config file not found: {target_path}")
    else:
        candidate_paths = config_candidates(find_project_root(start_dir))
        target_path = next((p for p in candidate_paths if p.exists()), None)

    if target_path is not None and target_path.exists():
        try:
            with open(target_path, encoding="utf-8") as f:
                user_config = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(
                f"Invalid JSON in config file '{target_path}': line {e.lineno}, column {e.colno} ({e.msg})"
            ) from e
        except OSError:
            pass
        else:
            if isinstance(user_config, dict):
                for k, v in user_config.items():
                    default_config[k] = v
                _CONFIG_LOADED = True
    return default_config


PROJECT_CONFIG = load_project_config()

# ── Environments ───────────────────────────────────────────────────────────────
LOCAL_ENV = {"id": "local", "cluster": None, "namespace": None, "label": "local — set-env-local.sh"}
KUBE_ENVS = PROJECT_CONFIG["environments"]
ENVIRONMENTS = [LOCAL_ENV] + KUBE_ENVS

# ── Noise filter ───────────────────────────────────────────────────────────────
_NOISE_EXACT = {
    "HOSTNAME",
    "HOME",
    "PATH",
    "USER",
    "SHELL",
    "SHLVL",
    "PWD",
    "OLDPWD",
    "LANG",
    "_",
    "TERM",
    "TERM_PROGRAM",
    "COLORTERM",
}
_NOISE_PREFIX = ("KUBERNETES_", "JAVA_", "LC_", "LS_COLORS", "JVM_")
_NOISE_SUFFIX = ("_SERVICE_HOST", "_SERVICE_PORT")

_DEFAULT_DB_CFG = """\
# ws run-local — local database configuration
# Used when DB=local to override URIs in Spring/Node services.
local:
  mongodb: mongodb://localhost:27018
  postgresql: postgresql://localhost:5432
"""
