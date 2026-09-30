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

_FIELDS = {"mode", "max_complexity", "max_function_lines", "max_args", "max_nesting", "exclude"}


@dataclass(frozen=True)
class DesignConfig:
    mode: str = "block"
    max_complexity: int = 10
    max_function_lines: int = 40
    max_args: int = 4
    max_nesting: int = 3
    exclude: tuple[str, ...] = field(default_factory=lambda: DEFAULT_EXCLUDE)

    @classmethod
    def load(cls, root: Path) -> DesignConfig:
        path = root / ".ai-governance" / "config.toml"
        if not path.is_file():
            return cls()
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        table = data.get("design")
        if table is None:
            return cls()
        if not isinstance(table, dict):
            raise ValueError("[design] must be a table")
        unknown = set(table) - _FIELDS
        if unknown:
            raise ValueError(f"[design] has unknown key(s): {', '.join(sorted(unknown))}")
        mode = str(table.get("mode", cls.mode))
        if mode not in MODES:
            raise ValueError(f"[design].mode must be one of {MODES}, got {mode!r}")
        exclude = table.get("exclude")
        return cls(
            mode=mode,
            max_complexity=int(table.get("max_complexity", cls.max_complexity)),
            max_function_lines=int(table.get("max_function_lines", cls.max_function_lines)),
            max_args=int(table.get("max_args", cls.max_args)),
            max_nesting=int(table.get("max_nesting", cls.max_nesting)),
            exclude=tuple(exclude) if exclude is not None else DEFAULT_EXCLUDE,
        )
