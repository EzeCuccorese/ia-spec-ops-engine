"""
workspace_engine.design.metrics — Per-function complexity metrics via ``lizard``.

One engine (lizard) covers Java, JavaScript/TypeScript/TSX/JSX, Python, Go, Kotlin,
C#, PHP, Rust, Swift, Scala, Ruby, C/C++, Dart and more.
Nesting depth is computed by ``workspace_engine.design.nesting`` instead of lizard's
own ``max_nested_structures``, which is too noisy to use as a metric.

Legacy ratchet: with an optional ``changed`` line map (``design.changes``) and the
merge-base ``base``, a function absent at the base (new, renamed, moved) is ``new`` and must
meet the limits. A touched function that existed at the base is ``legacy`` with a
``base_value``: it never blocks, but a metric that grew is reported first. An untouched
function is ``legacy``. The base version is read with ``git show`` and analysed in memory;
functions match by path, ``long_name`` (which carries the parameter signature) and occurrence
order. Without a ``changed`` map (a plain scan) everything is ``legacy``.
"""

from __future__ import annotations

import sys
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

import lizard

from workspace_engine.common import run_command_safe

from . import nesting
from .config import DesignConfig

_PYTHON_IMPLICIT_PARAMS = {"self", "cls"}
FUNCTION_METRICS = frozenset({"complexity", "length", "args", "nesting"})


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
    base_value: int | None = None

    @property
    def blocking(self) -> bool:
        """Only new code blocks; legacy never does, however much it changed."""
        return self.origin == "new"

    @property
    def worsened(self) -> bool:
        """A touched legacy function whose metric grew past the base value."""
        return self.base_value is not None and self.value > self.base_value


def supported(path: str | Path) -> bool:
    """Whether ``path``'s extension is analyzable by lizard."""
    suffix = Path(path).suffix.lstrip(".")
    return suffix in SUPPORTED_EXTENSIONS


def _advance_quote(ch: str, in_string: str | None, escape: bool) -> tuple[str | None, bool]:
    if escape:
        return in_string, False
    if ch == "\\" and in_string:
        return in_string, True
    if in_string and ch == in_string:
        return None, False
    if in_string is None and ch in ('"', "'"):
        return ch, False
    return in_string, False


def _extract_php_param_list(text: str) -> str:
    paren_idx = text.find("(")
    if paren_idx == -1:
        return ""
    depth = 0
    in_string: str | None = None
    escape = False
    param_text: list[str] = []
    for ch in text[paren_idx:]:
        in_string, escape = _advance_quote(ch, in_string, escape)
        if in_string:
            if depth >= 1:
                param_text.append(ch)
            continue
        if ch == "(":
            depth += 1
            if depth == 1:
                continue
        elif ch == ")":
            depth -= 1
            if depth == 0:
                break
        if depth >= 1:
            param_text.append(ch)
    return "".join(param_text).strip()


def _count_top_level_commas(text: str) -> int:
    text = text.rstrip().rstrip(",").strip()
    if not text:
        return 0
    depths = {"(": 0, "[": 0, "{": 0}
    matching = {")": "(", "]": "[", "}": "{"}
    in_string: str | None = None
    escape = False
    commas = 0
    for ch in text:
        in_string, escape = _advance_quote(ch, in_string, escape)
        if in_string:
            continue
        if ch in depths:
            depths[ch] += 1
        elif ch in matching and depths[matching[ch]] > 0:
            depths[matching[ch]] -= 1
        elif ch == "," and all(v == 0 for v in depths.values()):
            commas += 1
    return commas + 1


def _php_parameter_count(source: str, start_line: int, fn_name: str) -> int:
    """Extracts the parameter count directly from PHP source around ``start_line``."""
    lines = source.splitlines(keepends=True)
    if start_line < 1 or start_line > len(lines):
        return 0
    sub_source = "".join(lines[start_line - 1 :])
    base_name = fn_name.split("::")[-1]
    idx = sub_source.find(base_name)
    sub = sub_source[idx + len(base_name) :] if idx != -1 else sub_source
    param_text = _extract_php_param_list(sub)
    return _count_top_level_commas(param_text)


def _parameter_count(fn: Any, extension: str, source: str = "") -> int:
    if extension == "php":
        return _php_parameter_count(source, int(fn.start_line), str(fn.name))
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
        except SyntaxError as exc:
            print(
                f"⚠ ws design: skipping {relative} (syntax error: {exc.msg})",
                file=sys.stderr,
            )
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
            args=_parameter_count(fn, extension, source),
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
    except (OSError, UnicodeDecodeError) as exc:
        print(f"⚠ ws design: skipping {path} ({exc})", file=sys.stderr)
        return None
    relative = path.resolve().relative_to(root.resolve()).as_posix()
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


def _is_test_path(path: str) -> bool:
    """Whether ``path`` is a Python test file or lives under a ``tests/`` directory."""
    parts = path.replace("\\", "/").split("/")
    name = parts[-1]
    directories = parts[:-1]
    return (
        (name.startswith("test_") and name.endswith(".py"))
        or name.endswith("_test.py")
        or "tests" in directories
    )


def violations_for(
    fm: FunctionMetrics,
    config: DesignConfig,
    origin: str = "legacy",
    previous: FunctionMetrics | None = None,
) -> list[Violation]:
    checks: list[tuple[str, int, int]] = [
        ("complexity", fm.complexity, config.max_complexity),
        ("length", fm.length, config.max_function_lines),
    ]
    if not _is_test_path(fm.path):
        checks.append(("args", fm.args, config.max_args))
    if fm.nesting is not None:
        checks.append(("nesting", fm.nesting, config.max_nesting))
    return [
        Violation(
            fm.path,
            fm.symbol,
            fm.start_line,
            fm.end_line,
            metric,
            value,
            limit,
            origin,
            getattr(previous, metric) if previous else None,
        )
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


_FunctionKey = tuple[str, int]


def _base_name(symbol: str) -> str:
    return symbol.split("(", 1)[0].strip()


def _unique_by_base_name(functions: list[FunctionMetrics]) -> dict[str, FunctionMetrics]:
    """Maps base function name to metrics only for names appearing once in the file."""
    named = [(name, fm) for fm in functions if (name := _base_name(fm.symbol))]
    counts = Counter(name for name, _ in named)
    return {name: fm for name, fm in named if counts[name] == 1}


@dataclass(frozen=True)
class _BaseSnapshot:
    by_key: dict[_FunctionKey, FunctionMetrics]
    unique_by_name: dict[str, FunctionMetrics]

    def match(self, key: _FunctionKey, allow_name_fallback: bool) -> FunctionMetrics | None:
        previous = self.by_key.get(key)
        if previous is not None or not allow_name_fallback:
            return previous
        return self.unique_by_name.get(_base_name(key[0]))


def _keyed(functions: list[FunctionMetrics]) -> list[tuple[_FunctionKey, FunctionMetrics]]:
    """Functions keyed by ``(signature, occurrence)`` so duplicate names stay distinct."""
    seen: Counter[str] = Counter()
    keyed = []
    for fm in functions:
        keyed.append(((fm.symbol, seen[fm.symbol]), fm))
        seen[fm.symbol] += 1
    return keyed


def _base_functions(root: Path, base: str, relative: str) -> _BaseSnapshot:
    """The file's functions as of ``base``; empty when it did not exist or cannot be parsed."""
    code, source, _ = run_command_safe(
        ["git", "show", f"{base}:./{relative}"], cwd=root, isolated_git=True
    )
    if code != 0:
        return _BaseSnapshot({}, {})
    extension = Path(relative).suffix.lstrip(".")
    functions = analyze_source(relative, extension, source)
    return _BaseSnapshot(dict(_keyed(functions)), _unique_by_base_name(functions))


@dataclass(frozen=True)
class DiffScope:
    """What a scoped run compares against: changed lines and the merge-base commit."""

    changed: dict[str, set[int] | None]
    base: str | None


def _function_violations(
    entry: tuple[_FunctionKey, FunctionMetrics],
    config: DesignConfig,
    scope: DiffScope | None,
    lookup: Callable[[_FunctionKey], FunctionMetrics | None],
) -> list[Violation]:
    key, fm = entry
    found = violations_for(fm, config)
    if not found or scope is None:
        return found
    if not _touches(scope.changed, fm.path, fm.start_line, fm.end_line):
        return found
    previous = lookup(key)
    return violations_for(fm, config, "new" if previous is None else "legacy", previous)


def _file_violations(
    root: Path, path: Path, config: DesignConfig, scope: DiffScope | None
) -> list[Violation]:
    relative = path.resolve().relative_to(root).as_posix()
    functions = analyze_file(root, path)
    if not functions:
        return []
    unique_current = frozenset(_unique_by_base_name(functions))
    base = scope.base if scope else None

    @cache
    def at_base() -> _BaseSnapshot:
        return _base_functions(root, base, relative) if base else _BaseSnapshot({}, {})

    def lookup(key: _FunctionKey) -> FunctionMetrics | None:
        return at_base().match(key, _base_name(key[0]) in unique_current)

    violations: list[Violation] = []
    for entry in _keyed(functions):
        violations.extend(_function_violations(entry, config, scope, lookup))
    return violations


def measure(
    root: Path, paths: list[Path], config: DesignConfig, scope: DiffScope | None = None
) -> list[Violation]:
    """Measures ``paths`` (files, resolved) under ``root`` and returns limit violations.

    ``scope`` turns on the ratchet; without it, every violation is ``legacy``.
    """
    root_resolved = root.resolve()
    violations: list[Violation] = []
    for path in paths:
        if not path.is_file() or not supported(path):
            continue
        violations.extend(_file_violations(root_resolved, path, config, scope))
    violations.sort(key=lambda v: (v.path, v.start_line, v.metric))
    return violations
