"""
workspace_engine.common.dotenv — Robust, deterministic parser for .env and set-env.sh files.
"""

from __future__ import annotations

import re
from pathlib import Path

_EXPORT_PREFIX_RE = re.compile(r"^\s*export\s+")


def parse_dotenv(dotenv_path: Path | str) -> dict[str, str]:
    """
    Parses a .env or set-env.sh file into a key-value dictionary.
    Handles 'export' prefixes and comments, and strips surrounding quotes.
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
