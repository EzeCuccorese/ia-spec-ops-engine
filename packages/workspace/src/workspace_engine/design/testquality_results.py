"""Part of ``testquality`` (split out, no behavior change)."""

from __future__ import annotations

import ast
import copy
from collections.abc import Callable
from dataclasses import dataclass

from .metrics import Violation
from .testquality_clike import (
    _clike_fingerprint,
    _clike_units,
    _sleep_hits,
    _trivial_clike,
    _unit_assertions,
)
from .testquality_parse import _MIN_DUPLICATE_LINES, Changed, Parsed, _parse


class _Normalizer(ast.NodeTransformer):
    def __init__(self, mapping: dict[str, str]) -> None:
        self.mapping = mapping

    def visit_Constant(self, node: ast.Constant) -> ast.AST:
        return ast.Constant(value="_")

    def visit_Name(self, node: ast.Name) -> ast.AST:
        return ast.Name(id=self.mapping.get(node.id, node.id), ctx=node.ctx)


def _py_body(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.stmt]:
    body = list(fn.body)
    first = body[0] if body else None
    if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
        body = body[1:]
    return body


def _py_fingerprint(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
    body = _py_body(fn)
    if len(body) < _MIN_DUPLICATE_LINES:
        return None
    stores = sorted(
        {
            (n.lineno, n.col_offset, n.id)
            for stmt in body
            for n in ast.walk(stmt)
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)
        }
    )
    mapping: dict[str, str] = {}
    for _, _, name in stores:
        mapping.setdefault(name, f"v{len(mapping)}")
    normalized = [ast.dump(_Normalizer(mapping).visit(copy.deepcopy(stmt))) for stmt in body]
    decorators = [ast.dump(d) for d in fn.decorator_list]
    return "|".join([ast.dump(fn.args), *decorators, "#", *normalized])


def _origin_range(changed: Changed, path: str, start: int, end: int) -> str:
    if changed is None or path not in changed:
        return "legacy"
    entry = changed[path]
    if entry is None or any(line in entry for line in range(start, end + 1)):
        return "new"
    return "legacy"


@dataclass(frozen=True)
class _Job:
    """What one file's checks need to build violations."""

    relative: str
    active: set[str]
    changed: Changed

    def violation(self, symbol: str, start: int, end: int, metric: str) -> Violation:
        origin = _origin_range(self.changed, self.relative, start, end)
        return Violation(self.relative, symbol, start, end, metric, 1, 0, origin)

    def line_hits(self, hits: list[tuple[int, str]], metric: str) -> list[Violation]:
        return [self.violation(text[:60], line, line, metric) for line, text in sorted(set(hits))]


@dataclass(frozen=True)
class _Case:
    """A test unit reduced to what the checks need, independent of language."""

    name: str
    start_line: int
    end_line: int
    kinds: tuple[str, ...]
    fingerprint: str | None
    group: int
    skip: bool = False
    asserting: bool = False


_CASE_RULES: dict[str, Callable[[_Case], bool]] = {
    "test-no-assert": lambda case: not case.kinds and not case.asserting,
    "test-mock-only": lambda case: bool(case.kinds) and set(case.kinds) == {"mock"},
}


def _duplicate_cases(cases: list[_Case]) -> list[_Case]:
    seen: set[tuple[int, str]] = set()
    repeats = []
    for case in cases:
        if case.fingerprint is None:
            continue
        key = (case.group, case.fingerprint)
        if key in seen:
            repeats.append(case)
        seen.add(key)
    return repeats


def _case_violations(job: _Job, cases: list[_Case]) -> list[Violation]:
    checked = [case for case in cases if not case.skip]
    flagged = [
        (case, metric)
        for metric, rule in _CASE_RULES.items()
        if metric in job.active
        for case in checked
        if rule(case)
    ]
    if "test-duplicate" in job.active:
        flagged.extend((case, "test-duplicate") for case in _duplicate_cases(checked))
    return [job.violation(c.name, c.start_line, c.end_line, metric) for c, metric in flagged]


def _clike_cases(p: Parsed) -> list[_Case]:
    cases = []
    for unit in _clike_units(p):
        cases.append(
            _Case(
                unit.name,
                p.line(unit.start),
                p.line(unit.end),
                tuple(_unit_assertions(p, unit)),
                _clike_fingerprint(p, unit),
                unit.group,
                unit.skip,
                unit.asserting,
            )
        )
    return cases


def _extra_violations(
    job: _Job, trivial: list[tuple[int, str]], sleeps: list[tuple[int, str]]
) -> list[Violation]:
    out: list[Violation] = []
    if "test-trivial-assert" in job.active:
        out.extend(job.line_hits(trivial, "test-trivial-assert"))
    if "test-sleep" in job.active:
        out.extend(job.line_hits(sleeps, "test-sleep"))
    return out


def _clike_violations(job: _Job, ext: str, source: str) -> list[Violation]:
    p = _parse(job.relative, ext, source)
    out = _case_violations(job, _clike_cases(p))
    return out + _extra_violations(job, _trivial_clike(p), _sleep_hits(p))
