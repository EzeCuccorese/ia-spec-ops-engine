"""
workspace_engine.design.nesting — Deterministic nesting-depth metric.

lizard's own ``max_nested_structures`` (the "ns" extension) is noisy: on real code it
returns values that do not reflect the actual nesting of control structures (observed
values in the hundreds for functions with a handful of real nested blocks). This module
computes nesting depth ourselves instead:

- Python: exact, via ``ast`` — max depth of If/For/AsyncFor/While/With/AsyncWith/Try/
  TryStar/Match nodes inside the function. Nested ``def``/``lambda`` bodies are not
  descended into (they are measured as their own functions); ``elif`` is the same
  depth as its ``if`` (Python represents it as a nested ``If`` in ``orelse``, which we
  special-case).
- Brace languages (Java, JS/TS/TSX/JSX, Go, Kotlin, C#, PHP, Rust, Swift, Scala, C/C++):
  a best-effort scan over the function's source lines. Strings and comments are
  stripped, then a stack of braces is tracked; a ``{`` counts as a control level only
  if the buffered text since the previous ``;``/``{``/``}`` contains a control keyword.
  ``else``/``catch``/``finally`` continuing a previous block reuse that block's level
  instead of nesting one level deeper.
- Anything else (Ruby, Lua, ...): nesting is not computed; callers must treat that as
  "no nesting violation" rather than 0.
"""

from __future__ import annotations

import ast
import re

PYTHON_EXTENSIONS = frozenset({"py"})

BRACE_EXTENSIONS = frozenset(
    {
        "java",
        "js",
        "cjs",
        "mjs",
        "jsx",
        "ts",
        "tsx",
        "go",
        "kt",
        "kts",
        "cs",
        "php",
        "rs",
        "swift",
        "scala",
        "c",
        "cpp",
        "cc",
        "cxx",
        "h",
        "hpp",
    }
)

_CONTROL_KEYWORDS = re.compile(
    r"\b(if|else|for|foreach|while|do|switch|when|match|try|catch|finally|loop|select)\b"
)
_CHAIN_CONTINUATION = re.compile(r"^(else(\s+if\b.*)?|catch\b.*|finally)$")

_PY_NEST_NODE_TYPES: tuple[type, ...] = (
    ast.If,
    ast.For,
    ast.AsyncFor,
    ast.While,
    ast.With,
    ast.AsyncWith,
    ast.Try,
)
if hasattr(ast, "TryStar"):
    _PY_NEST_NODE_TYPES += (ast.TryStar,)
if hasattr(ast, "Match"):
    _PY_NEST_NODE_TYPES += (ast.Match,)

_PY_SCOPE_NODE_TYPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)


def _visit_body(stmts: list[ast.stmt], depth: int) -> int:
    best = depth
    for stmt in stmts:
        best = max(best, _visit(stmt, depth))
    return best


def _visit(node: ast.AST, depth: int) -> int:
    if isinstance(node, _PY_SCOPE_NODE_TYPES):
        return depth  # measured as its own function
    if isinstance(node, ast.If):
        inner_depth = depth + 1
        best = inner_depth
        best = max(best, _visit_body(node.body, inner_depth))
        if len(node.orelse) == 1 and isinstance(node.orelse[0], ast.If):
            best = max(best, _visit(node.orelse[0], depth))  # elif: same level as its if
        else:
            best = max(best, _visit_body(node.orelse, inner_depth))
        return best
    if isinstance(node, _PY_NEST_NODE_TYPES):
        inner_depth = depth + 1
        best = inner_depth
        for attr in ("body", "orelse", "finalbody"):
            best = max(best, _visit_body(getattr(node, attr, []) or [], inner_depth))
        for handler in getattr(node, "handlers", []) or []:
            best = max(best, _visit_body(handler.body, inner_depth))
        for case in getattr(node, "cases", []) or []:
            best = max(best, _visit_body(case.body, inner_depth))
        return best
    best = depth
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.stmt):
            best = max(best, _visit(child, depth))
    return best


def python_nesting(source: str) -> dict[int, int]:
    """Maps each function's ``def``/``async def`` line to its max nesting depth."""
    tree = ast.parse(source)
    results: dict[int, int] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            results[node.lineno] = _visit_body(node.body, 0)
    return results


def _strip_strings_and_comments(text: str) -> str:
    out: list[str] = []
    i, n = 0, len(text)
    while i < n:
        two = text[i : i + 2]
        if two == "//":
            while i < n and text[i] != "\n":
                i += 1
            continue
        if two == "/*":
            i += 2
            while i < n and text[i : i + 2] != "*/":
                i += 1
            i += 2
            continue
        char = text[i]
        if char in ("'", '"', "`"):
            i += 1
            while i < n and text[i] != char:
                i += 2 if text[i] == "\\" and i + 1 < n else 1
            i += 1
            continue
        out.append(char)
        i += 1
    return "".join(out)


def brace_nesting(text: str) -> int:
    """Max control-structure nesting depth in a brace-language source snippet."""
    stripped = _strip_strings_and_comments(text)
    depth = 0
    max_depth = 0
    stack: list[bool] = []
    buffer = ""
    paren_depth = 0
    for char in stripped:
        if char == "(":
            paren_depth += 1
            buffer += char
            continue
        if char == ")":
            paren_depth = max(0, paren_depth - 1)
            buffer += char
            continue
        if char == "{":
            normalized = re.sub(r"\s+", " ", buffer.strip())
            if _CHAIN_CONTINUATION.match(normalized):
                depth += 1
                stack.append(True)
                max_depth = max(max_depth, depth)
            else:
                is_control = bool(_CONTROL_KEYWORDS.search(buffer))
                stack.append(is_control)
                if is_control:
                    depth += 1
                    max_depth = max(max_depth, depth)
            buffer = ""
        elif char == "}":
            was_control = stack.pop() if stack else False
            if was_control:
                depth -= 1
            buffer = ""
        elif char == ";" and paren_depth == 0:
            buffer = ""
        else:
            buffer += char
    return max_depth
