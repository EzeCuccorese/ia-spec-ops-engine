"""
workspace_engine.run_local.profiles — Gestión de perfiles y persistencia de configuraciones para run_local.
"""

from __future__ import annotations

import json
from pathlib import Path

from workspace_engine.run_local import constants
from workspace_engine.run_local.service_wiring import assign_port


def load_profiles() -> dict:
    if not constants.PROFILES_FILE.exists():
        return {}
    try:
        return json.loads(constants.PROFILES_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def save_profiles(profiles: dict) -> None:
    constants.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    constants.PROFILES_FILE.write_text(json.dumps(profiles, indent=2))


def save_last_configs(configs: list) -> None:
    """Persist the last launched config for --start headless mode."""
    entries = []
    for c in configs:
        entries.append(
            {
                "name": c["name"],
                "path": str(c["path"]),
                "type": c.get("type") or c.get("service", {}).get("type", ""),
                "port": c["port"],
                "base_env": c.get("base_env", "local"),
                "db_env": c.get("db_env", "local"),
                "up_mode": c.get("up_mode", "auto"),
                "cmd": c.get("service", {}).get("cmd", []),
                "port_var": c.get("service", {}).get("port_var", "PORT"),
            }
        )
    try:
        constants.DATA_DIR.mkdir(parents=True, exist_ok=True)
        constants.LAST_CONFIGS_FILE.write_text(json.dumps(entries, indent=2))
    except OSError:
        pass


def load_last_configs() -> list:
    if not constants.LAST_CONFIGS_FILE.exists():
        return []
    try:
        entries = json.loads(constants.LAST_CONFIGS_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return []
    env_by_id = {e["id"]: e for e in constants.ENVIRONMENTS}
    configs = []
    for e in entries:
        path = Path(e["path"])
        base_env = e.get("base_env", "local")
        svc_type = e.get("type", "node")
        configs.append(
            {
                "name": e["name"],
                "path": path,
                "port": e.get("port") or assign_port(e["name"]),
                "type": svc_type,
                "env": env_by_id.get(base_env, constants.LOCAL_ENV),
                "base_env": base_env,
                "db_env": e.get("db_env", "local"),
                "up_mode": e.get("up_mode", "auto"),
                "service": {
                    "type": svc_type,
                    "cmd": e.get("cmd", []),
                    "port_var": e.get("port_var", "PORT"),
                },
            }
        )
    return configs
