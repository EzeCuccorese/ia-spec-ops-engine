"""
workspace_engine.design.config — Configuration for ``ws design``.

Reads the optional ``[design]`` table of ``<root>/.ai-governance/config.toml``. This
table is the contract shared with ai-governance: ai-governance may read and render
it, but ``ws design`` never reads or writes the repository's own linter configs
(eslint, checkstyle, ruff, golangci-lint, ...) to decide its limits.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from workspace_engine._config_core import merge_tables, read_table, xdg_dir

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
        repo = _read_repo_table(root / ".ai-governance" / "config.toml")
        raw_profiles = repo.get("profiles", [])
        profiles = tuple(str(p) for p in raw_profiles) if isinstance(raw_profiles, list) else ()
        table = _design_table(user, "user config"), _design_table(repo, "[design]")
        if not any(t is not None for t in table):
            return cls(profiles=profiles)
        table = merge_tables(*(t for t in table if t is not None))
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
