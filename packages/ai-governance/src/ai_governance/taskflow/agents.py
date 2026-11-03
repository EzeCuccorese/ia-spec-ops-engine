"""Agent identities: which provider an agent id belongs to and which agents a repository allows.

``taskflow.allowed_agents`` (user level) is narrowed by each bound repository's
``.ai-governance/config.toml`` ``[taskflow] allowed_agents``: a repository file can only remove
agents. Every malformed value fails closed (no agent is allowed until the file is fixed).
"""

from __future__ import annotations

import errno
import json
import os
import re
import stat
import tomllib
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from .models import Task

HUMAN = "human"
ALIASES = {"agy": "antigravity"}
AGENT_ID = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
REPO_FILE = Path(".ai-governance") / "config.toml"
ROLE_NAMES = ("planner", "validator", "builder", "judge")
# Roles whose provider must differ from the builder's (the coordinating session).
INDEPENDENT_ROLES = ("validator", "judge")
# Fallback order for a role whose default agent is not allowed in a repository.
PREFERENCE: dict[str, tuple[str, ...]] = {
    "planner": ("claude", "codex"),
    "validator": ("codex", "claude"),
    "builder": ("claude", "codex"),
    "judge": ("codex", "claude"),
}
# Default model of each built-in agent (mirrors the ``taskflow.<role>_model`` defaults).
DEFAULT_MODELS = {"antigravity": "gemini-4-argon-high", "codex": "gpt-6.1-sol", "claude": ""}


class AllowedAgentsError(ValueError):
    pass


def provider(agent: str) -> str:
    """Provider of an agent id: lower-cased text before ``/`` (``codex/gpt-6.1-sol`` -> ``codex``),
    with ``agy`` meaning ``antigravity``. An unknown id is its own provider (a heuristic: the
    provider a worker really ran as is what a later collect step compares)."""
    name = str(agent).strip().lower().split("/", 1)[0]
    return ALIASES.get(name, name)


@dataclass(frozen=True)
class Allowed:
    """The agents a repository set permits; ``problems`` non-empty means everything is blocked."""

    agents: frozenset[str]
    problems: tuple[str, ...] = ()
    narrowed_by: tuple[str, ...] = ()

    def permits(self, agent: str) -> bool:
        name = provider(agent)
        return name == HUMAN or (not self.problems and name in self.agents)

    def errors(self) -> list[str]:
        if self.problems:
            return list(self.problems)
        if not self.agents:
            return ["taskflow.allowed_agents allows no agent (only 'human' can act)"]
        return []


def _ids(raw: object, where: str, *, csv: bool = False) -> frozenset[str]:
    """Agent ids of a list value (a comma-separated string too when ``csv``); anything else is
    an error naming ``where``."""
    items = [i.strip() for i in raw.split(",")] if csv and isinstance(raw, str) else raw
    if not isinstance(items, list | tuple):
        raise AllowedAgentsError(f"{where}: allowed_agents must be a list of agent ids")
    found: set[str] = set()
    for item in items:
        if not isinstance(item, str):
            raise AllowedAgentsError(f"{where}: allowed_agents holds a non-string item {item!r}")
        if not AGENT_ID.fullmatch(item):
            raise AllowedAgentsError(f"{where}: '{item}' is not a valid agent id")
        found.add(provider(item))
    return frozenset(found)


def read_regular_text(path: Path) -> str:
    """Text of a regular file (a symlink to one is followed), read through one descriptor.

    The file is opened without blocking and checked with ``fstat`` before any read, so a FIFO,
    socket, device or directory is rejected (``OSError``) instead of hanging the caller or
    being read; a swap after an earlier check cannot get past the descriptor test."""
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_NOCTTY", 0))
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise OSError(errno.EINVAL, "not a regular file", str(path))
        with os.fdopen(fd, "rb", closefd=False) as handle:
            return handle.read().decode("utf-8")
    finally:
        os.close(fd)


def source_problem(path: Path) -> str | None:
    """Why a config file that may feed ``taskflow.allowed_agents`` cannot be trusted to say
    nothing, else None. Only a genuinely absent file is fine."""
    try:
        text = read_regular_text(path)
        if path.suffix == ".json":
            json.loads(text)
        else:
            tomllib.loads(text)
    except FileNotFoundError as exc:
        return str(_unreadable(str(path), exc)) if os.path.lexists(path) else None
    except (OSError, ValueError) as exc:  # includes JSON/TOML/Unicode decode errors
        return str(_unreadable(str(path), exc))
    return None


def user_source_problems(paths: Iterable[Path]) -> tuple[str, ...]:
    return tuple(p for path in paths if (p := source_problem(path)))


def _unreadable(where: str, exc: Exception) -> AllowedAgentsError:
    return AllowedAgentsError(
        f"{where}: cannot read it ({exc}); agents stay blocked until it is fixed"
    )


def read_repo_allowed(repo: Path) -> frozenset[str] | None:
    """The repository's ``allowed_agents``; None when it states none (unrestricted).

    Strict on purpose: a file that exists but cannot be read or understood blocks agents (it
    raises) instead of reading as unrestricted.
    """
    path = repo / REPO_FILE
    where = str(path)
    try:
        os.lstat(path.parent)
    except FileNotFoundError:
        return None  # no .ai-governance entry at all: nothing restricts this repository
    except OSError as exc:
        raise _unreadable(where, exc) from exc
    data = _read_repo_toml(path)
    if data is None:
        return None
    table = data.get("taskflow")
    if table is None or (isinstance(table, dict) and "allowed_agents" not in table):
        return None
    if not isinstance(table, dict):
        raise AllowedAgentsError(f"{where}: [taskflow] must be a table")
    return _ids(table["allowed_agents"], where)


def _read_repo_toml(path: Path) -> dict[str, object] | None:
    """The parsed repo file; None only when it is genuinely absent (raises when unreadable)."""
    try:
        return tomllib.loads(read_regular_text(path))
    except FileNotFoundError as exc:
        # Only a genuinely absent file is "no restriction": a dangling link is present but broken.
        if not os.path.lexists(path) and os.path.isdir(path.parent):
            return None
        raise _unreadable(str(path), exc) from exc
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise _unreadable(str(path), exc) from exc


def resolve_allowed(
    user: object, repos: Iterable[Path], user_problems: Sequence[str] = ()
) -> Allowed:
    """User set intersected with every repository's set (a repository can only remove).
    ``user_problems``: user config files that exist but cannot be read block every agent."""
    if user_problems:
        return Allowed(frozenset(), tuple(user_problems))
    try:
        allowed = _ids(user, "taskflow.allowed_agents (user setting)", csv=True)
    except AllowedAgentsError as exc:
        return Allowed(frozenset(), (str(exc),))
    narrowed: list[str] = []
    for repo in repos:
        try:
            theirs = read_repo_allowed(repo)
        except AllowedAgentsError as exc:
            return Allowed(frozenset(), (str(exc),))
        if theirs is not None and not allowed <= theirs:
            allowed &= theirs
            narrowed.append(str(repo / REPO_FILE))
    return Allowed(allowed, (), tuple(narrowed))


def fallback_agent(role: str, current: str, allowed: Allowed, builder: str) -> str:
    """The default agent of ``role`` when it is allowed; else the first allowed one in the
    role's preference order (never the builder's provider for the validator and judge)."""
    if allowed.permits(current):
        return current
    for candidate in PREFERENCE[role]:
        clash = role in INDEPENDENT_ROLES and provider(candidate) == provider(builder)
        if allowed.permits(candidate) and not clash:
            return candidate
    return current


def builder_providers(task: Task, configured_builder: str) -> set[str]:
    """Providers that wrote code: the configured builder plus any legacy builder round."""
    used = {provider(str(r.get("agent", ""))) for r in task.rounds if r.get("role") == "builder"}
    return {provider(configured_builder), *used} - {""}
