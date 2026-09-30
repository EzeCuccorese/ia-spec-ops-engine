"""
workspace_engine.design.metrics — Per-function complexity metrics via ``lizard``.

One engine (lizard) covers Java, JavaScript/TypeScript/TSX/JSX, Python, Go, Kotlin,
C#, PHP, Rust, Swift, Scala, Ruby, C/C++ and more. Dart is not supported by lizard.
Nesting depth is computed by ``workspace_engine.design.nesting`` instead of lizard's
own ``max_nested_structures``, which is too noisy to use as a metric.

Each measured function is also classified ``new`` or ``legacy`` (``Violation.origin``)
against an optional ``changed`` line map from ``workspace_engine.design.changes``: a
function is ``new`` when its ``[start_line, end_line]`` overlaps changed lines, or its
file is wholly new. Without a ``changed`` map (a plain, non-scoped scan) everything is
``legacy``.
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
class FunctionMetrics:
    path: str
    symbol: str
    start_line: int
    end_line: int
    complexity: int
    length: int
    args: int
    nesting: int | None


@dataclass(frozen=True)
class Violation:
    path: str
    symbol: str
    start_line: int
    end_line: int
    metric: str
    value: int
    limit: int
    origin: str = "legacy"


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


def analyze_source(relative: str, extension: str, source: str) -> list[FunctionMetrics]:
    """Raw per-function metrics for one file's already-read ``source``."""
    python_depths: dict[int, int] = {}
    if extension in nesting.PYTHON_EXTENSIONS:
        try:
            python_depths = nesting.python_nesting(source)
        except SyntaxError:
            return []
    analyzer = lizard.FileAnalyzer(lizard.get_extensions([]))
    info = analyzer.analyze_source_code(relative, source)
    return [
        FunctionMetrics(
            path=relative,
            symbol=str(fn.long_name or fn.name),
            start_line=int(fn.start_line),
            end_line=int(fn.end_line),
            complexity=int(fn.cyclomatic_complexity),
            length=int(fn.nloc),
            args=_parameter_count(fn, extension),
            nesting=_nesting_value(fn, extension, source, python_depths),
        )
        for fn in info.function_list
    ]


def analyze_file(root: Path, path: Path) -> list[FunctionMetrics] | None:
    """Per-function metrics for one file, or ``None`` if unreadable/unsupported."""
    if not path.is_file() or not supported(path):
        return None
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    relative = path.resolve().relative_to(root).as_posix()
    return analyze_source(relative, path.suffix.lstrip("."), source)


def function_at(root: Path, path: Path, line: int) -> FunctionMetrics | None:
    """The innermost measured function whose range contains ``line``, if any."""
    functions = analyze_file(root, path)
    if not functions:
        return None
    candidates = [fm for fm in functions if fm.start_line <= line <= fm.end_line]
    if not candidates:
        return None
    return min(candidates, key=lambda fm: fm.end_line - fm.start_line)


def violations_for(
    fm: FunctionMetrics, config: DesignConfig, origin: str = "legacy"
) -> list[Violation]:
    checks: list[tuple[str, int, int]] = [
        ("complexity", fm.complexity, config.max_complexity),
        ("length", fm.length, config.max_function_lines),
        ("args", fm.args, config.max_args),
    ]
    if fm.nesting is not None:
        checks.append(("nesting", fm.nesting, config.max_nesting))
    return [
        Violation(fm.path, fm.symbol, fm.start_line, fm.end_line, metric, value, limit, origin)
        for metric, value, limit in checks
        if value > limit and metric in config.checks
    ]


def _touches(changed: dict[str, set[int] | None], path: str, start: int, end: int) -> bool:
    if path not in changed:
        return False
    entry = changed[path]
    if entry is None:
        return True
    return any(start <= line <= end for line in entry)


def measure(
    root: Path,
    paths: list[Path],
    config: DesignConfig,
    changed: dict[str, set[int] | None] | None = None,
) -> list[Violation]:
    """Measures ``paths`` (files, resolved) under ``root`` and returns limit violations.

    ``changed`` (from ``design.changes.changed_lines``) classifies each violation's
    ``origin``; without it, every violation is ``legacy``.
    """
    violations: list[Violation] = []
    for path in paths:
        if not path.is_file():
            continue
        relative = path.resolve().relative_to(root).as_posix()
        if _excluded(relative, config.exclude) or not supported(path):
            continue
        functions = analyze_file(root, path)
        if not functions:
            continue
        for fm in functions:
            origin = "legacy"
            if changed is not None and _touches(changed, fm.path, fm.start_line, fm.end_line):
                origin = "new"
            violations.extend(violations_for(fm, config, origin))
    violations.sort(key=lambda v: (v.path, v.start_line, v.metric))
    return violations
