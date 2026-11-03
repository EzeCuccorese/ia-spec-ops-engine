"""Part of ``testquality`` (split out, no behavior change)."""

from __future__ import annotations

import ast
import re
from collections.abc import Callable

from .metrics import Violation
from .testquality_results import _Case, _case_violations, _extra_violations, _Job, _py_fingerprint

_PY_TEST_NAME = re.compile(r"^test(?:_|[A-Z])")


_PY_MOCK = re.compile(
    r"^assert_(?:called|awaited|any_call|any_await|has_calls|has_awaits|not_called|not_awaited)"
)


_PY_STATE = re.compile(r"^_*(?:assert|expect|check|verify)")


_PY_RAISING = frozenset({"raises", "warns", "deprecated_call", "fail"})


_PY_EQUAL_CALLS = frozenset(
    {
        "assertEqual",
        "assertEquals",
        "assertIs",
        "assertSequenceEqual",
        "assertListEqual",
        "assertTupleEqual",
        "assertDictEqual",
        "assertSetEqual",
        "assertCountEqual",
    }
)


PyFunction = ast.FunctionDef | ast.AsyncFunctionDef


def _py_test_functions(tree: ast.Module) -> list[tuple[PyFunction, int]]:
    found: list[tuple[PyFunction, int]] = []

    def visit(body: list[ast.stmt], key: int) -> None:
        for node in body:
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                if _PY_TEST_NAME.match(node.name):
                    found.append((node, key))
            elif isinstance(node, ast.ClassDef):
                visit(node.body, node.lineno)

    visit(tree.body, -1)
    return found


def _py_leaf(func: ast.expr) -> str:
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return ""


def _py_assertion_kind(node: ast.AST) -> str | None:
    if isinstance(node, ast.Assert):
        return "state"
    if isinstance(node, ast.Raise) and node.exc is not None:
        target = node.exc.func if isinstance(node.exc, ast.Call) else node.exc
        return "state" if _py_leaf(target) == "AssertionError" else None
    if not isinstance(node, ast.Call):
        return None
    leaf = _py_leaf(node.func)
    if _PY_MOCK.match(leaf):
        return "mock"
    if _PY_STATE.match(leaf) or leaf in _PY_RAISING:
        return "state"
    return None


def _py_assertions(fn: PyFunction) -> tuple[str, ...]:
    kinds = (_py_assertion_kind(node) for node in ast.walk(fn))
    return tuple(kind for kind in kinds if kind)


def _is_skipped(fn: PyFunction) -> bool:
    return any("skip" in ast.unparse(d) for d in fn.decorator_list)


def _py_cases(tree: ast.Module) -> list[_Case]:
    return [
        _Case(
            fn.name,
            fn.lineno,
            fn.end_lineno or fn.lineno,
            _py_assertions(fn),
            _py_fingerprint(fn),
            key,
            _is_skipped(fn),
        )
        for fn, key in _py_test_functions(tree)
    ]


def _py_const_truthy(node: ast.expr) -> bool:
    if isinstance(node, ast.Constant):
        return bool(node.value)
    return (
        isinstance(node, ast.UnaryOp)
        and isinstance(node.op, ast.Not)
        and isinstance(node.operand, ast.Constant)
        and not node.operand.value
    )


def _py_pure_equal(left: ast.expr, right: ast.expr) -> bool:
    if any(isinstance(n, ast.Call | ast.Await | ast.NamedExpr) for n in ast.walk(left)):
        return False
    return ast.dump(left) == ast.dump(right)


def _py_trivial_assert(node: ast.Assert) -> bool:
    test = node.test
    if _py_const_truthy(test):
        return True
    if isinstance(test, ast.Compare) and len(test.ops) == 1:
        return isinstance(test.ops[0], ast.Eq | ast.Is) and _py_pure_equal(
            test.left, test.comparators[0]
        )
    return False


def _is_const(node: ast.expr, test: Callable[[object], bool]) -> bool:
    return isinstance(node, ast.Constant) and test(node.value)


def _py_trivial_call(node: ast.Call) -> bool:
    leaf = _py_leaf(node.func)
    args = node.args
    if leaf in _PY_EQUAL_CALLS:
        return len(args) >= 2 and _py_pure_equal(args[0], args[1])
    single: dict[str, Callable[[ast.expr], bool]] = {
        "assertTrue": _py_const_truthy,
        "assertFalse": lambda arg: _is_const(arg, lambda value: not value),
        "assertIsNone": lambda arg: _is_const(arg, lambda value: value is None),
    }
    return leaf in single and bool(args) and single[leaf](args[0])


def _py_trivial(tree: ast.Module) -> list[tuple[int, str]]:
    hits = []
    for node in ast.walk(tree):
        trivial = (isinstance(node, ast.Assert) and _py_trivial_assert(node)) or (
            isinstance(node, ast.Call) and _py_trivial_call(node)
        )
        if trivial:
            hits.append((node.lineno, ast.unparse(node).splitlines()[0]))  # type: ignore[attr-defined]
    return hits


def _py_is_sleep(node: ast.Call, imported: bool) -> bool:
    func = node.func
    named = (
        isinstance(func, ast.Attribute)
        and func.attr == "sleep"
        and isinstance(func.value, ast.Name)
        and func.value.id == "time"
    ) or (imported and isinstance(func, ast.Name) and func.id == "sleep")
    zero = bool(node.args) and isinstance(node.args[0], ast.Constant) and node.args[0].value == 0
    return named and not zero


def _imports_sleep(tree: ast.Module) -> bool:
    return any(
        isinstance(n, ast.ImportFrom)
        and n.module == "time"
        and any(a.name == "sleep" for a in n.names)
        for n in ast.walk(tree)
    )


def _inside_while(tree: ast.Module) -> set[int]:
    """Ids of every node inside a `while` loop: a sleep there is polling with a deadline,
    which the rule recommends."""
    return {id(n) for loop in ast.walk(tree) if isinstance(loop, ast.While) for n in ast.walk(loop)}


def _py_sleeps(tree: ast.Module) -> list[tuple[int, str]]:
    imported = _imports_sleep(tree)
    polling = _inside_while(tree)
    return [
        (node.lineno, "time.sleep")
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and _py_is_sleep(node, imported) and id(node) not in polling
    ]


def _python_violations(job: _Job, source: str) -> list[Violation]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    out = _case_violations(job, _py_cases(tree))
    return out + _extra_violations(job, _py_trivial(tree), _py_sleeps(tree))
