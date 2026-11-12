"""
workspace_engine.design.config — Configuration for ``ws design``.

Reads the optional ``[design]`` table from the unified workspace config files:
user global (~/.config/workspace/config.toml), in-repo (<root>/.workspace/config.toml),
and personal per-repo (~/.config/workspace/repos/<repo-name>.toml).
"""

from __future__ import annotations

import tomllib
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from workspace_engine._config_core import read_table, xdg_dir
from workspace_engine.settings import personal_repo_config_path

MODES = ("block", "warn", "off")

DEFAULT_EXCLUDE = (
    "**/node_modules/**",
    "**/vendor/**",
    "**/dist/**",
    "**/build/**",
    "**/target/**",
    "**/.venv/**",
    "**/generated/**",
    "**/*.min.js",
)

_FIELDS = {
    "mode",
    "max_complexity",
    "max_function_lines",
    "max_args",
    "max_nesting",
    "exclude",
    "layers",
    "checks",
    "profiles",
}
_LAYERS_FIELDS = {"order", "paths"}

CHECKS = (
    "complexity",
    "length",
    "args",
    "nesting",
    "empty-catch",
    "todo-ticket",
    "commented-code",
    "test-no-assert",
    "test-trivial-assert",
    "test-mock-only",
    "test-sleep",
    "test-duplicate",
)


@dataclass(frozen=True)
class LayersConfig:
    """``[design.layers]`` — architecture layers, outermost to innermost.

    A layer may import only itself and layers listed after it in ``order``; an inner
    layer (e.g. ``domain``) importing an outer one (e.g. ``adapters``) is a violation.
    """

    order: tuple[str, ...]
    paths: dict[str, tuple[str, ...]]

    def globs_for(self, layer: str) -> tuple[str, ...]:
        return self.paths.get(layer, (f"**/{layer}/**",))


def _parse_layers(table: object) -> LayersConfig:
    if not isinstance(table, dict):
        raise ValueError("[design.layers] must be a table")
    unknown = set(table) - _LAYERS_FIELDS
    if unknown:
        raise ValueError(f"[design.layers] has unknown key(s): {', '.join(sorted(unknown))}")
    order = table.get("order")
    if not isinstance(order, list) or not order:
        raise ValueError("[design.layers].order must be a non-empty list")
    raw_paths = table.get("paths", {})
    if not isinstance(raw_paths, dict):
        raise ValueError("[design.layers.paths] must be a table")
    paths = {str(name): tuple(globs) for name, globs in raw_paths.items()}
    return LayersConfig(order=tuple(str(name) for name in order), paths=paths)


def _read_repo_table(path: Path) -> dict:
    return tomllib.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def _design_table(data: dict, where: str) -> dict | None:
    table = data.get("design")
    if table is not None and not isinstance(table, dict):
        raise ValueError(f"[design] must be a table ({where})")
    return table


def _extract_exclude(table: dict | None) -> list[str]:
    if not table:
        return []
    raw = table.get("exclude")
    if raw is None:
        return []
    if isinstance(raw, list | tuple):
        return [str(item) for item in raw]
    return [str(raw)]


def _accumulate_exclude(*sources: Sequence[object] | object) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for item in DEFAULT_EXCLUDE:
        if item not in seen:
            seen.add(item)
            result.append(item)
    for source in sources:
        if not source:
            continue
        items: Sequence[object] = source if isinstance(source, list | tuple) else [source]
        for raw in items:
            s = str(raw)
            if s not in seen:
                seen.add(s)
                result.append(s)
    return tuple(result)


def _merge_design_tables(
    user: dict | None, repo: dict | None, personal: dict | None = None
) -> dict:
    merged: dict = {}
    if user:
        merged.update(user)
    if repo:
        merged.update(repo)
    if personal:
        merged.update(personal)
    user_exc = _extract_exclude(user)
    repo_exc = _extract_exclude(repo)
    personal_exc = _extract_exclude(personal)
    merged["exclude"] = _accumulate_exclude(user_exc, repo_exc, personal_exc)
    return merged


@dataclass(frozen=True)
class DesignConfig:
    mode: str = "block"
    max_complexity: int = 10
    max_function_lines: int = 40
    max_args: int = 4
    max_nesting: int = 3
    exclude: tuple[str, ...] = field(default_factory=lambda: DEFAULT_EXCLUDE)
    layers: LayersConfig | None = None
    profiles: tuple[str, ...] = field(default_factory=tuple)
    checks: tuple[str, ...] = field(default_factory=lambda: CHECKS)

    @classmethod
    def load(cls, root: Path) -> DesignConfig:
        user = read_table(xdg_dir("config", "workspace") / "config.toml")
        repo = _read_repo_table(root / ".workspace" / "config.toml")
        personal = read_table(personal_repo_config_path(root))

        user_table = _design_table(user, "user config")
        repo_table = _design_table(repo, "[design]")
        personal_table = _design_table(personal, "personal config")

        raw_profiles: list[object] = []
        for src in (user, repo, personal, user_table, repo_table, personal_table):
            if src is not None:
                p = src.get("profiles")
                if isinstance(p, list):
                    raw_profiles = p
        profiles = tuple(str(p) for p in raw_profiles)

        if user_table is None and repo_table is None and personal_table is None:
            return cls(profiles=profiles)
        table: dict = _merge_design_tables(user_table, repo_table, personal_table)
        unknown = set(table) - _FIELDS
        if unknown:
            raise ValueError(f"[design] has unknown key(s): {', '.join(sorted(unknown))}")
        mode = str(table.get("mode", cls.mode))
        if mode not in MODES:
            raise ValueError(f"[design].mode must be one of {MODES}, got {mode!r}")
        exclude = table.get("exclude")
        layers_table = table.get("layers")
        raw_checks = table.get("checks")
        if raw_checks is not None:
            checks = tuple(str(c) for c in raw_checks)
            unknown_checks = set(checks) - set(CHECKS)
            if unknown_checks:
                raise ValueError(
                    f"[design].checks has unknown check(s): {', '.join(sorted(unknown_checks))}"
                )
        else:
            checks = CHECKS
        return cls(
            mode=mode,
            max_complexity=int(table.get("max_complexity", cls.max_complexity)),
            max_function_lines=int(table.get("max_function_lines", cls.max_function_lines)),
            max_args=int(table.get("max_args", cls.max_args)),
            max_nesting=int(table.get("max_nesting", cls.max_nesting)),
            exclude=tuple(exclude) if exclude is not None else DEFAULT_EXCLUDE,
            layers=_parse_layers(layers_table) if layers_table is not None else None,
            profiles=profiles,
            checks=checks,
        )
