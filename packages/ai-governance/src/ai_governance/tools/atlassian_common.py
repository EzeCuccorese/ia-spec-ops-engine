"""
atlassian_common.py — Shared authentication, configuration, and HTTP utilities
for Jira and Confluence command-line tools.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

from .._config_core import ConfigError
from ..paths import config_dir
from ..settings import effective

DEFAULT_TIMEOUT_SECONDS = 30.0
logger = logging.getLogger(__name__)


class AtlassianError(Exception):
    """Base exception for Atlassian client errors."""


class AtlassianConfigError(AtlassianError):
    """Raised when Atlassian configuration or credentials are invalid or missing."""


class AtlassianRequestError(AtlassianError):
    """Raised when an Atlassian API request fails due to HTTP, network, or timeout errors."""


class UnknownProfileError(AtlassianConfigError, LookupError):
    """Raised when a named Atlassian profile is not defined anywhere."""


def atlassian_timeout() -> float:
    """HTTP timeout in seconds: ``$ATLASSIAN_TIMEOUT``, ``[atlassian] timeout_seconds``, 30."""
    try:
        return float(str(effective()["atlassian.timeout_seconds"].value))
    except (ConfigError, ValueError):
        return DEFAULT_TIMEOUT_SECONDS


def _default_credentials() -> dict[str, str]:
    return {
        "email": os.environ.get("ATLASSIAN_EMAIL", ""),
        "token": os.environ.get("ATLASSIAN_API_TOKEN", ""),
        "url": os.environ.get("ATLASSIAN_URL", "").rstrip("/"),
    }


_CURRENT_PROFILE: str | None = None
_PROFILE_OVERRIDES: dict[str, dict[str, str]] = {}


def legacy_profiles_path() -> Path:
    """Pre-XDG profiles file, still read as a fallback."""
    return Path.home() / ".config" / "atlassian" / "profiles.json"


def set_profile(name: str | None) -> None:
    """Sets the active configuration profile for Atlassian operations."""
    global _CURRENT_PROFILE
    _CURRENT_PROFILE = name


def _profile_paths() -> list[Path]:
    paths: list[Path] = []
    if os.environ.get("ATLASSIAN_PROFILES_FILE"):
        paths.append(Path(os.environ["ATLASSIAN_PROFILES_FILE"]))
    paths.append(config_dir() / "atlassian.json")
    paths.append(legacy_profiles_path())
    return paths


def _read_profile_dict(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


def _load_profile_from_files(target: str) -> tuple[dict[str, str] | None, set[str]]:
    known: set[str] = set(_PROFILE_OVERRIDES)
    for path in _profile_paths():
        data = _read_profile_dict(path)
        if data is None:
            continue
        known.update(k for k, v in data.items() if isinstance(v, dict))
        prof = data.get(target)
        if isinstance(prof, dict):
            return (
                {
                    "email": prof.get("email", ""),
                    "token": prof.get("token", prof.get("api_token", "")),
                    "url": prof.get("url", "").rstrip("/"),
                },
                known,
            )
    return None, known


def _load_profile_from_env(target: str) -> dict[str, str] | None:
    p_upper = target.upper().replace("-", "_")
    email = os.environ.get(f"ATLASSIAN_{p_upper}_EMAIL") or os.environ.get(
        f"ATLASSIAN_EMAIL_{p_upper}"
    )
    token = os.environ.get(f"ATLASSIAN_{p_upper}_API_TOKEN") or os.environ.get(
        f"ATLASSIAN_API_TOKEN_{p_upper}"
    )
    url = os.environ.get(f"ATLASSIAN_{p_upper}_URL") or os.environ.get(f"ATLASSIAN_URL_{p_upper}")
    if not (email or token or url):
        return None
    fallback = _default_credentials()
    return {
        "email": email or fallback["email"],
        "token": token or fallback["token"],
        "url": (url or fallback["url"]).rstrip("/"),
    }


def load_profile_config(profile_name: str | None = None) -> dict[str, str]:
    """Loads configuration for the requested profile from memory, config files, or environment."""
    target = profile_name or _CURRENT_PROFILE or os.environ.get("ATLASSIAN_PROFILE")
    if not target or target.lower() == "default":
        return _default_credentials()

    if target in _PROFILE_OVERRIDES:
        return dict(_PROFILE_OVERRIDES[target])

    from_file, known = _load_profile_from_files(target)
    if from_file is not None:
        return from_file

    from_env = _load_profile_from_env(target)
    if from_env is not None:
        return from_env

    listed = ", ".join(["default", *sorted(known)])
    raise UnknownProfileError(
        f"Unknown Atlassian profile '{target}'. Known profiles: {listed}. "
        "Define it in the profiles file or via ATLASSIAN_<PROFILE>_EMAIL/_API_TOKEN/_URL."
    )


def get_base_url() -> str:
    cfg = load_profile_config()
    return cfg.get("url") or os.environ.get("ATLASSIAN_URL", "").rstrip("/")


def check_env() -> None:
    """Validates required environment variables or profile settings."""
    try:
        cfg = load_profile_config()
    except UnknownProfileError as exc:
        raise AtlassianConfigError(f"Error: {exc}") from exc
    missing: list[str] = []
    if not cfg.get("email"):
        missing.append("ATLASSIAN_EMAIL")
    if not cfg.get("token"):
        missing.append("ATLASSIAN_API_TOKEN")
    if not cfg.get("url"):
        missing.append("ATLASSIAN_URL")
    if missing:
        lines = [
            "Error: Missing required environment variables or profile configuration:",
            *(f'  export {v}="..."' for v in missing),
        ]
        raise AtlassianConfigError("\n".join(lines))


def auth_header() -> dict[str, str]:
    cfg = load_profile_config()
    email = cfg.get("email") or os.environ.get("ATLASSIAN_EMAIL", "")
    token = cfg.get("token") or os.environ.get("ATLASSIAN_API_TOKEN", "")
    cred = base64.b64encode(f"{email}:{token}".encode()).decode()
    return {
        "Authorization": f"Basic {cred}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def sanitize_secrets(msg: str) -> str:
    """Sanitizes sensitive tokens, auth headers, and secrets from error messages."""
    try:
        cfg = load_profile_config()
    except UnknownProfileError:
        cfg = {}
    tokens = [cfg.get("token"), os.environ.get("ATLASSIAN_API_TOKEN")]
    for t in tokens:
        if t and len(t) >= 4:
            msg = msg.replace(t, "[REDACTED_TOKEN]")
    msg = re.sub(r"Basic\s+[A-Za-z0-9+/=]+", "Basic [REDACTED]", msg)
    msg = re.sub(r"Bearer\s+[A-Za-z0-9._~+/-]+", "Bearer [REDACTED]", msg)
    return msg


def read_input_text(source: str, *, allow_bare_path: bool = True) -> str:
    """Reads text from literal string, stdin ('-'), or file path ('@path' or path if exists)."""
    if source == "-":
        return sys.stdin.read()
    if source.startswith("@"):
        path = Path(source[1:])
        if path.is_file():
            return path.read_text(encoding="utf-8")
    if allow_bare_path:
        p = Path(source)
        if p.is_file():
            return p.read_text(encoding="utf-8")
    return source


def _format_error_body(raw: str) -> str:
    try:
        msg = json.loads(raw)
        return json.dumps(msg, indent=2)
    except json.JSONDecodeError as exc:
        logger.debug("Atlassian error response is not JSON: %s", exc)
        return raw


def execute_request(
    method: str, url: str, payload: dict | list | None = None, timeout: float | None = None
) -> dict | list:
    check_env()
    req_timeout = timeout if timeout is not None else atlassian_timeout()
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, headers=auth_header(), method=method)
    try:
        with urllib.request.urlopen(req, timeout=req_timeout) as resp:
            body = resp.read().decode()
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as e:
        err = _format_error_body(e.read().decode())
        sanitized = sanitize_secrets(err)
        raise AtlassianRequestError(
            f"HTTP {e.code} Error calling {method} {url}:\n{sanitized}"
        ) from e
    except urllib.error.URLError as e:
        sanitized = sanitize_secrets(str(e.reason))
        raise AtlassianRequestError(
            f"Network error calling {method} {url}: {sanitized}"
        ) from e
    except TimeoutError as e:
        sanitized = sanitize_secrets(str(e))
        raise AtlassianRequestError(
            f"Timeout error calling {method} {url}: {sanitized}"
        ) from e
