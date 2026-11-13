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


def _visit_if(node: ast.If, depth: int) -> int:
    inner_depth = depth + 1
    best = max(inner_depth, _visit_body(node.body, inner_depth))
    if len(node.orelse) == 1 and isinstance(node.orelse[0], ast.If):
        return max(best, _visit(node.orelse[0], depth))  # elif: same level as its if
    return max(best, _visit_body(node.orelse, inner_depth))


def _visit_nest(node: ast.AST, depth: int) -> int:
    inner_depth = depth + 1
    best = inner_depth
    for attr in ("body", "orelse", "finalbody"):
        best = max(best, _visit_body(getattr(node, attr, []) or [], inner_depth))
    for handler in getattr(node, "handlers", []) or []:
        best = max(best, _visit_body(handler.body, inner_depth))
    for case in getattr(node, "cases", []) or []:
        best = max(best, _visit_body(case.body, inner_depth))
    return best


def _visit(node: ast.AST, depth: int) -> int:
    if isinstance(node, _PY_SCOPE_NODE_TYPES):
        return depth  # measured as its own function
    if isinstance(node, ast.If):
        return _visit_if(node, depth)
    if isinstance(node, _PY_NEST_NODE_TYPES):
        return _visit_nest(node, depth)
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


def _skip_line_comment(text: str, i: int) -> int:
    n = len(text)
    while i < n and text[i] != "\n":
        i += 1
    return i


def _skip_block_comment(text: str, i: int) -> int:
    n = len(text)
    i += 2
    while i < n and text[i : i + 2] != "*/":
        i += 1
    return i + 2


def _skip_quoted(text: str, i: int, quote: str) -> int:
    n = len(text)
    i += 1
    while i < n and text[i] != quote:
        i += 2 if text[i] == "\\" and i + 1 < n else 1
    return i + 1


def _strip_strings_and_comments(text: str) -> str:
    out: list[str] = []
    i, n = 0, len(text)
    while i < n:
        two = text[i : i + 2]
        if two == "//":
            i = _skip_line_comment(text, i)
            continue
        if two == "/*":
            i = _skip_block_comment(text, i)
            continue
        char = text[i]
        if char in ("'", '"', "`"):
            i = _skip_quoted(text, i, char)
            continue
        out.append(char)
        i += 1
    return "".join(out)


def _open_brace(buffer: str, depth: int, max_depth: int, stack: list[bool]) -> tuple[int, int]:
    normalized = re.sub(r"\s+", " ", buffer.strip())
    is_control = bool(_CHAIN_CONTINUATION.match(normalized)) or bool(
        _CONTROL_KEYWORDS.search(buffer)
    )
    stack.append(is_control)
    if is_control:
        depth += 1
        max_depth = max(max_depth, depth)
    return depth, max_depth


def _close_brace(depth: int, stack: list[bool]) -> int:
    was_control = stack.pop() if stack else False
    return depth - 1 if was_control else depth


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
        elif char == ")":
            paren_depth = max(0, paren_depth - 1)
            buffer += char
        elif char == "{":
            depth, max_depth = _open_brace(buffer, depth, max_depth, stack)
            buffer = ""
        elif char == "}":
            depth = _close_brace(depth, stack)
            buffer = ""
        elif char == ";" and paren_depth == 0:
            buffer = ""
        else:
            buffer += char
    return max_depth
