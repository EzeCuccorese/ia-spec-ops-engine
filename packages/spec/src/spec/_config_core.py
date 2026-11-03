"""Shared configuration core: XDG directories, layered settings and agent-mode detection.

This file is copied byte-for-byte into ``ai_governance``, ``workspace_engine`` and ``spec``
so the packages stay independently installable without importing each other. Edit one
copy, then copy it over the other two; a root test fails when they drift.

Precedence, lowest to highest: default < user < repo < env < flag.

* user: ``<config dir>/config.toml`` (legacy ``config.json`` is still read, with a notice)
* repo: ``<repo root>/<repo dir>/config.toml`` (legacy ``config.json`` likewise)
* env:  the variable named by the setting
* flag: values passed by the CLI

Settings are flat dotted keys (``frugality.threshold_chars``); in files they are the
nested TOML tables (``[frugality] threshold_chars = 4000``).
"""

from __future__ import annotations

import json
import os
import sys
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

ORIGINS = ("default", "user", "repo", "env", "flag")

# Environment variables set by supported agents for the commands they spawn.
AGENT_ENV_MARKERS: tuple[str, ...] = (
    "CLAUDE_CODE_CHILD_SESSION",  # Claude Code (tool and hook subprocesses)
    "CLAUDECODE",  # Claude Code (any subprocess)
    "CODEX_SANDBOX",  # OpenAI Codex (spawned commands; experimental upstream)
    "ANTIGRAVITY_AGENT",  # Google Antigravity agent terminal
)

_XDG = {
    "config": ("XDG_CONFIG_HOME", (".config",)),
    "state": ("XDG_STATE_HOME", (".local", "state")),
    "data": ("XDG_DATA_HOME", (".local", "share")),
}
_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off", ""}


class ConfigError(ValueError):
    """A configuration file or value is invalid."""


def _prefix(app: str) -> str:
    return app.upper().replace("-", "_")


def xdg_dir(kind: str, app: str) -> Path:
    """``$<APP>_<KIND>_DIR``, else ``$XDG_<KIND>_HOME/<app>``, else ``~/<xdg default>/<app>``."""
    explicit = os.environ.get(f"{_prefix(app)}_{kind.upper()}_DIR")
    if explicit:
        return Path(explicit).expanduser()
    variable, fallback = _XDG[kind]
    base = os.environ.get(variable) or str(Path.home().joinpath(*fallback))
    return Path(base).expanduser() / app


def is_agent_mode(app: str) -> bool:
    """True when output should be compact/plain for an AI agent.

    ``$<APP>_AGENT=1`` forces it on and ``=0`` off; otherwise any agent marker turns it on.
    """
    forced = os.environ.get(f"{_prefix(app)}_AGENT")
    if forced == "1":
        return True
    if forced == "0":
        return False
    return any(os.environ.get(name) for name in AGENT_ENV_MARKERS)


@dataclass(frozen=True)
class Setting:
    key: str
    default: object
    env: str | None = None
    help: str = ""
    # True when the variable is read by a shell that treats an empty value as unset
    # (``${VAR:-default}``); numbers also treat "" as unset since "" is not a number.
    empty_env_is_unset: bool = False


@dataclass(frozen=True)
class Value:
    value: object
    origin: str
    source: str


_NOTIFIED: set[Path] = set()


def _notify_legacy(path: Path, app: str) -> None:
    """One stderr line per legacy JSON file, only for humans on a terminal."""
    if path in _NOTIFIED or not sys.stderr.isatty() or is_agent_mode(app):
        return
    _NOTIFIED.add(path)
    print(f"note: {path} is a legacy JSON config; move it to config.toml", file=sys.stderr)


def read_table(path: Path, app: str = "") -> dict:
    """Parses a TOML or JSON config file; a missing file is an empty table."""
    if not path.is_file():
        return {}
    try:
        if path.suffix == ".json":
            if app:
                _notify_legacy(path, app)
            data = json.loads(path.read_text(encoding="utf-8"))
        else:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        raise ConfigError(f"Invalid config file {path}: {exc}") from exc
    except OSError:
        return {}
    if not isinstance(data, dict):
        raise ConfigError(f"Invalid config file {path}: expected a table")
    return data


def flatten(table: Mapping[str, object], prefix: str = "") -> dict[str, object]:
    flat: dict[str, object] = {}
    for key, value in table.items():
        name = f"{prefix}{key}"
        if isinstance(value, Mapping):
            flat.update(flatten(value, f"{name}."))
        else:
            flat[name] = value
    return flat


def merge_tables(*tables: Mapping[str, object]) -> dict[str, object]:
    """Key-by-key merge of whole tables; later tables win."""
    merged: dict[str, object] = {}
    for table in tables:
        merged.update(table)
    return merged


def _split_items(raw: object) -> list[str]:
    items = raw.split(",") if isinstance(raw, str) else list(raw)  # type: ignore[call-overload]
    return [str(item).strip() for item in items if str(item).strip()]


def _convert(raw: object, like: object) -> object:
    if isinstance(like, bool):
        return _to_bool(raw)
    if isinstance(like, int):
        return raw if isinstance(raw, int) else int(str(raw))
    if isinstance(like, float):
        return float(str(raw))
    if isinstance(like, list | tuple):
        return _split_items(raw)
    return raw if like is None else str(raw)


def coerce(raw: object, like: object, key: str) -> object:
    """Converts a file or environment value to the type of the setting's default."""
    try:
        return _convert(raw, like)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"Invalid value for {key}: {raw!r}") from exc


def _to_bool(raw: object) -> bool:
    text = str(raw).strip().lower()
    if text in _TRUE:
        return True
    if text in _FALSE:
        return False
    raise ValueError(raw)


@dataclass(frozen=True)
class Layers:
    """Flat key/value maps of each file layer plus the file each key came from."""

    user: dict[str, object]
    repo: dict[str, object]
    user_files: dict[str, Path]
    repo_files: dict[str, Path]


def _load_layer(paths: Sequence[Path], app: str) -> tuple[dict[str, object], dict[str, Path]]:
    values: dict[str, object] = {}
    sources: dict[str, Path] = {}
    for path in paths:  # lowest priority first: the legacy JSON file, then TOML
        for key, value in flatten(read_table(path, app)).items():
            values[key] = value
            sources[key] = path
    return values, sources


def load_layers(
    app: str,
    repo_root: Path | None,
    repo_dir: str | None = None,
    *,
    legacy_json: bool = True,
) -> Layers:
    """Reads the user and repo files. ``repo_dir`` defaults to ``.<app>``.

    ``legacy_json=False`` ignores ``config.json`` for apps whose JSON file is something
    else (``ws``: the ``run-local`` project file).
    """

    def files(folder: Path) -> list[Path]:
        return [*([folder / "config.json"] if legacy_json else []), folder / "config.toml"]

    user, user_files = _load_layer(files(xdg_dir("config", app)), app)
    repo: dict[str, object] = {}
    repo_files: dict[str, Path] = {}
    if repo_root is not None:
        repo, repo_files = _load_layer(files(repo_root / (repo_dir or f".{app}")), app)
    return Layers(user, repo, user_files, repo_files)


def _env_value(setting: Setting, env: Mapping[str, str]) -> str | None:
    """The variable's value; set-but-empty counts (an empty list, text or false) except where
    "" means unset: numbers, and settings flagged ``empty_env_is_unset``."""
    raw = env.get(setting.env) if setting.env else None
    if raw != "":
        return raw
    numeric = isinstance(setting.default, int | float) and not isinstance(setting.default, bool)
    return None if numeric or setting.empty_env_is_unset else raw


def resolve(
    settings: Sequence[Setting],
    layers: Layers,
    *,
    flags: Mapping[str, object] | None = None,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Value]:
    """Effective value of every setting, with the layer (and file or variable) it came from."""
    env = os.environ if environ is None else environ
    given = flags or {}
    resolved: dict[str, Value] = {}
    for setting in settings:
        key, like = setting.key, setting.default
        found = Value(like, "default", "")
        if key in layers.user:
            found = Value(coerce(layers.user[key], like, key), "user", str(layers.user_files[key]))
        if key in layers.repo:
            found = Value(coerce(layers.repo[key], like, key), "repo", str(layers.repo_files[key]))
        from_env = _env_value(setting, env)
        if from_env is not None:
            found = Value(coerce(from_env, like, key), "env", setting.env or "")
        if given.get(key) is not None:
            found = Value(coerce(given[key], like, key), "flag", f"--{key}")
        resolved[key] = found
    return resolved


def render_show(values: Mapping[str, Value], *, origin: bool = False, as_json: bool = False) -> str:
    """Text or JSON listing of the effective configuration."""
    if as_json:
        body = {
            key: ({"value": v.value, "origin": v.origin, "source": v.source} if origin else v.value)
            for key, v in values.items()
        }
        return json.dumps(body, indent=2, sort_keys=True, default=list)
    lines = []
    for key in sorted(values):
        found = values[key]
        line = f"{key} = {json.dumps(found.value, default=list)}"
        if origin:
            where = f" ({found.source})" if found.source else ""
            line += f"  # {found.origin}{where}"
        lines.append(line)
    return "\n".join(lines)
