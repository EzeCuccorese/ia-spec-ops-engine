"""
atlassian_common.py — Shared authentication, configuration, and HTTP utilities
for Jira and Confluence command-line tools.
"""

from __future__ import annotations

import base64
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

from ..paths import config_dir

EMAIL = os.environ.get("ATLASSIAN_EMAIL", "")
TOKEN = os.environ.get("ATLASSIAN_API_TOKEN", "")
BASE_URL = os.environ.get("ATLASSIAN_URL", "").rstrip("/")
ATLASSIAN_TIMEOUT = float(os.environ.get("ATLASSIAN_TIMEOUT", "30.0"))

_CURRENT_PROFILE: str | None = None
_PROFILE_OVERRIDES: dict[str, dict[str, str]] = {}


def set_profile(name: str | None) -> None:
    """Sets the active configuration profile for Atlassian operations."""
    global _CURRENT_PROFILE
    _CURRENT_PROFILE = name


def load_profile_config(profile_name: str | None = None) -> dict[str, str]:
    """Loads configuration for the requested profile from memory, config files, or environment."""
    target = profile_name or _CURRENT_PROFILE or os.environ.get("ATLASSIAN_PROFILE")
    if not target or target.lower() == "default":
        return {
            "email": os.environ.get("ATLASSIAN_EMAIL", EMAIL),
            "token": os.environ.get("ATLASSIAN_API_TOKEN", TOKEN),
            "url": os.environ.get("ATLASSIAN_URL", BASE_URL).rstrip("/"),
        }

    # 1. Check in-memory overrides
    if target in _PROFILE_OVERRIDES:
        return dict(_PROFILE_OVERRIDES[target])

    # 2. Check profiles file
    profiles_paths: list[Path] = []
    if os.environ.get("ATLASSIAN_PROFILES_FILE"):
        profiles_paths.append(Path(os.environ["ATLASSIAN_PROFILES_FILE"]))
    profiles_paths.append(Path.home() / ".config" / "atlassian" / "profiles.json")
    profiles_paths.append(config_dir() / "atlassian.json")

    for p in profiles_paths:
        if p.is_file():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                if target in data and isinstance(data[target], dict):
                    prof = data[target]
                    return {
                        "email": prof.get("email", ""),
                        "token": prof.get("token", prof.get("api_token", "")),
                        "url": prof.get("url", "").rstrip("/"),
                    }
            except (json.JSONDecodeError, UnicodeDecodeError, OSError):
                continue

    # 3. Check environment variables: ATLASSIAN_{PROFILE}_EMAIL, etc.
    p_upper = target.upper().replace("-", "_")
    email = os.environ.get(f"ATLASSIAN_{p_upper}_EMAIL") or os.environ.get(
        f"ATLASSIAN_EMAIL_{p_upper}"
    )
    token = os.environ.get(f"ATLASSIAN_{p_upper}_API_TOKEN") or os.environ.get(
        f"ATLASSIAN_API_TOKEN_{p_upper}"
    )
    url = os.environ.get(f"ATLASSIAN_{p_upper}_URL") or os.environ.get(f"ATLASSIAN_URL_{p_upper}")

    return {
        "email": email or os.environ.get("ATLASSIAN_EMAIL", EMAIL),
        "token": token or os.environ.get("ATLASSIAN_API_TOKEN", TOKEN),
        "url": (url or os.environ.get("ATLASSIAN_URL", BASE_URL)).rstrip("/"),
    }


def get_base_url() -> str:
    cfg = load_profile_config()
    return cfg.get("url") or os.environ.get("ATLASSIAN_URL", BASE_URL).rstrip("/")


def check_env() -> None:
    """Validates required environment variables or profile settings."""
    cfg = load_profile_config()
    missing: list[str] = []
    if not cfg.get("email"):
        missing.append("ATLASSIAN_EMAIL")
    if not cfg.get("token"):
        missing.append("ATLASSIAN_API_TOKEN")
    if not cfg.get("url"):
        missing.append("ATLASSIAN_URL")
    if missing:
        print(
            "Error: Missing required environment variables or profile configuration:",
            file=sys.stderr,
        )
        for v in missing:
            print(f'  export {v}="..."', file=sys.stderr)
        sys.exit(1)


def auth_header() -> dict[str, str]:
    cfg = load_profile_config()
    email = cfg.get("email") or os.environ.get("ATLASSIAN_EMAIL", EMAIL)
    token = cfg.get("token") or os.environ.get("ATLASSIAN_API_TOKEN", TOKEN)
    cred = base64.b64encode(f"{email}:{token}".encode()).decode()
    return {
        "Authorization": f"Basic {cred}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def sanitize_secrets(msg: str) -> str:
    """Sanitizes sensitive tokens, auth headers, and secrets from error messages."""
    cfg = load_profile_config()
    tokens = [
        cfg.get("token"),
        os.environ.get("ATLASSIAN_API_TOKEN"),
        TOKEN,
    ]
    for t in tokens:
        if t and len(t) >= 4:
            msg = msg.replace(t, "[REDACTED_TOKEN]")
    msg = re.sub(r"Basic\s+[A-Za-z0-9+/=]+", "Basic [REDACTED]", msg)
    msg = re.sub(r"Bearer\s+[A-Za-z0-9._~+/-]+", "Bearer [REDACTED]", msg)
    return msg


def read_input_text(source: str) -> str:
    """Reads text from literal string, stdin ('-'), or file path ('@path' or path if exists)."""
    if source == "-":
        return sys.stdin.read()
    if source.startswith("@"):
        path = Path(source[1:])
        if path.is_file():
            return path.read_text(encoding="utf-8")
    p = Path(source)
    if p.is_file():
        return p.read_text(encoding="utf-8")
    return source


def execute_request(
    method: str, url: str, payload: dict | list | None = None, timeout: float | None = None
) -> dict | list:
    check_env()
    req_timeout = timeout if timeout is not None else ATLASSIAN_TIMEOUT
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, headers=auth_header(), method=method)
    try:
        with urllib.request.urlopen(req, timeout=req_timeout) as resp:
            body = resp.read().decode()
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as e:
        err = e.read().decode()
        try:
            msg = json.loads(err)
            err = json.dumps(msg, indent=2)
        except json.JSONDecodeError:
            pass
        sanitized = sanitize_secrets(err)
        print(f"HTTP {e.code} Error calling {method} {url}:\n{sanitized}", file=sys.stderr)
        sys.exit(1)
    except urllib.error.URLError as e:
        sanitized = sanitize_secrets(str(e.reason))
        print(f"Network error calling {method} {url}: {sanitized}", file=sys.stderr)
        sys.exit(1)
    except TimeoutError as e:
        sanitized = sanitize_secrets(str(e))
        print(f"Timeout error calling {method} {url}: {sanitized}", file=sys.stderr)
        sys.exit(1)
