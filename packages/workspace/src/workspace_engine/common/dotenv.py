"""
workspace_engine.common.dotenv — Parser robusto y determinista de archivos .env y set-env.sh.
"""

from __future__ import annotations

import re
from pathlib import Path

_EXPORT_PREFIX_RE = re.compile(r"^\s*export\s+")


def parse_dotenv(dotenv_path: Path | str) -> dict[str, str]:
    """
    Parsea un archivo .env o set-env.sh a un diccionario clave-valor.
    Soporta prefijos 'export', comentarios, y remueve comillas envolventes.
    """
    env_vars: dict[str, str] = {}
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
