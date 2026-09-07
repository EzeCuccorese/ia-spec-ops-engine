"""
workspace_engine.run_local.constants — Constantes, rutas y configuración para run_local.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from workspace_engine.utils import Color

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


def load_project_config() -> dict:
    global _CONFIG_LOADED
    default_config = {
        "project_name": "generic",
        "domain": "generic.com",
        "namespaces": [],
        "env_slugs": [],
        "environments": [],
        "artifact_registry_domain": "generic",
        "repositories_dir_env_var": "PROJECT_REPOSITORIES_DIR",
        "local_envs_dir_name": "local-envs",
        "workspaces_dir_name": "workspaces",
        "toolkit_dir_name": "project-toolkit",
        "url_pattern": r"https?://([a-z0-9-]+)\.(?:dev|prod)\.generic\.com(/[\S]*)?",
    }
    candidate_paths = [
        Path.cwd() / ".specops" / "config.json",
        Path.home() / ".config" / "specops" / "config.json",
    ]
    if "XDG_CONFIG_HOME" in os.environ:
        candidate_paths.insert(1, Path(os.environ["XDG_CONFIG_HOME"]) / "specops" / "config.json")
    candidate_paths.append(Path("config.json"))

    config_path = next((p for p in candidate_paths if p.exists()), Path("config.json"))

    if config_path.exists():
        try:
            with open(config_path, encoding="utf-8") as f:
                user_config = json.load(f)
                for k, v in user_config.items():
                    default_config[k] = v
                _CONFIG_LOADED = True
        except Exception:
            pass
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
# run-local.py — configuración de bases de datos locales
# Usada cuando DB=local para override de URIs en servicios Spring/Node.
local:
  mongodb: mongodb://localhost:27018
  postgresql: postgresql://localhost:5432
"""
