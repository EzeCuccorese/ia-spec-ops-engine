"""
workspace_engine.design.metrics — Per-function complexity metrics via ``lizard``.

One engine (lizard) covers Java, JavaScript/TypeScript/TSX/JSX, Python, Go, Kotlin,
C#, PHP, Rust, Swift, Scala, Ruby, C/C++ and more. Dart is not supported by lizard.
Nesting depth is computed by ``workspace_engine.design.nesting`` instead of lizard's
own ``max_nested_structures``, which is too noisy to use as a metric.
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import lizard

from . import nesting
from .config import DesignConfig

_PYTHON_IMPLICIT_PARAMS = {"self", "cls"}


def _supported_extensions() -> frozenset[str]:
    from lizard_languages import languages

    return frozenset(ext.lstrip(".") for reader in languages() for ext in reader.ext)


SUPPORTED_EXTENSIONS = _supported_extensions()


@dataclass(frozen=True)
class Violation:
    path: str
    symbol: str
    start_line: int
    end_line: int
    metric: str
    value: int
    limit: int


def supported(path: str | Path) -> bool:
    """Whether ``path``'s extension is analyzable by lizard."""
    suffix = Path(path).suffix.lstrip(".")
    return suffix in SUPPORTED_EXTENSIONS


def _excluded(relative: str, patterns: tuple[str, ...]) -> bool:
    candidate = f"/{relative}"
    return any(fnmatch.fnmatch(candidate, pattern) for pattern in patterns)


def _parameter_count(fn: Any, extension: str) -> int:
    parameters = list(fn.parameters or [])
    if extension == "py":
        parameters = [p for p in parameters if p not in _PYTHON_IMPLICIT_PARAMS]
    return len(parameters)


def _nesting_value(
    fn: Any, extension: str, source: str, python_depths: dict[int, int]
) -> int | None:
    """Max nesting depth for ``fn``, or ``None`` when the language is not supported."""
    if extension in nesting.PYTHON_EXTENSIONS:
        return python_depths.get(int(fn.start_line))
    if extension in nesting.BRACE_EXTENSIONS:
        lines = source.splitlines(keepends=True)
        segment = "".join(lines[int(fn.start_line) - 1 : int(fn.end_line)])
        return nesting.brace_nesting(segment)
    return None


def _function_violations(
    fn: Any,
    relative: str,
    config: DesignConfig,
    extension: str,
    source: str,
    python_depths: dict[int, int],
) -> list[Violation]:
    symbol = str(fn.long_name or fn.name)
    start = int(fn.start_line)
    end = int(fn.end_line)
    checks = [
        ("complexity", int(fn.cyclomatic_complexity), config.max_complexity),
        ("length", int(fn.nloc), config.max_function_lines),
        ("args", _parameter_count(fn, extension), config.max_args),
    ]
    nesting_value = _nesting_value(fn, extension, source, python_depths)
    if nesting_value is not None:
        checks.append(("nesting", nesting_value, config.max_nesting))
    return [
        Violation(relative, symbol, start, end, metric, value, limit)
        for metric, value, limit in checks
        if value > limit
    ]


def measure(root: Path, paths: list[Path], config: DesignConfig) -> list[Violation]:
    """Measures ``paths`` (files, resolved) under ``root`` and returns limit violations."""
    analyzer = lizard.FileAnalyzer(lizard.get_extensions([]))
    violations: list[Violation] = []
    for path in paths:
        if not path.is_file():
            continue
        relative = path.resolve().relative_to(root).as_posix()
        if _excluded(relative, config.exclude) or not supported(path):
            continue
        extension = path.suffix.lstrip(".")
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        python_depths: dict[int, int] = {}
        if extension in nesting.PYTHON_EXTENSIONS:
            try:
                python_depths = nesting.python_nesting(source)
            except SyntaxError:
                continue
        info = analyzer.analyze_source_code(relative, source)
        for fn in info.function_list:
            violations.extend(
                _function_violations(fn, relative, config, extension, source, python_depths)
            )
    violations.sort(key=lambda v: (v.path, v.start_line, v.metric))
    return violations
