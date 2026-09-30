"""
workspace_engine.design.hygiene — empty-catch, todo-ticket, commented-code checks.

Deterministic, line-based scanners (no external tools) enforcing rule 01 ("never
swallow exceptions") and rule 11 ("self-documenting code": ticketed TODOs, no
commented-out code) from the ai-governance catalog. Each finding is a ``Violation``
with ``value=1``, ``limit=0``, classified ``new``/``legacy`` like the other metrics.
"""

from __future__ import annotations

import ast
import re
import textwrap
from pathlib import Path

from .metrics import Violation

TICKET_RE = re.compile(r"[A-Z][A-Z0-9]+-\d+|#\d+|https?://\S+")
TODO_RE = re.compile(r"\b(TODO|FIXME|XXX)\b", re.IGNORECASE)

_STATEMENT_KEYWORDS = (
    "return",
    "if",
    "for",
    "while",
    "import",
    "def",
    "class",
    "const",
    "let",
    "var",
    "public",
    "private",
    "protected",
    "function",
    "func",
    "package",
    "throw",
    "try",
    "switch",
    "case",
)
_CODE_END_CHARS = (";", "{", "}", ")")

_C_STYLE_EXTENSIONS = frozenset(
    {
        "java",
        "kt",
        "kts",
        "js",
        "jsx",
        "ts",
        "tsx",
        "mjs",
        "cjs",
        "cs",
        "php",
        "dart",
        "swift",
        "scala",
        "go",
        "rs",
    }
)
_HASH_STYLE_EXTENSIONS = frozenset({"py", "rb"})

_CATCH_EXTENSIONS = frozenset(
    {
        "java",
        "kt",
        "kts",
        "js",
        "jsx",
        "ts",
        "tsx",
        "mjs",
        "cjs",
        "cs",
        "php",
        "dart",
        "swift",
        "scala",
    }
)

_CATCH_OPEN = re.compile(r"\bcatch\s*(?:\([^)]*\))?\s*\{")
_GO_ERR_IF = re.compile(r"\bif\s+err\s*!=\s*nil\s*\{")
_RUST_ERR_ARM = re.compile(r"Err\s*\(\s*_?\s*\)\s*=>\s*(\{\s*\}|\(\s*\))")

_C_LINE_COMMENT_FULL = re.compile(r"^\s*//(.*)$")
_C_LINE_COMMENT_TRAILING = re.compile(r"//(.*)$")
_HASH_LINE_COMMENT_FULL = re.compile(r"^\s*#(.*)$")
_HASH_LINE_COMMENT_TRAILING = re.compile(r"#(.*)$")


def _looks_like_code(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    if stripped.rstrip().endswith(_CODE_END_CHARS):
        return True
    first_word = re.split(r"[\s(]", stripped, maxsplit=1)[0].lower()
    return first_word in _STATEMENT_KEYWORDS


def _touches(changed: dict[str, set[int] | None] | None, path: str, line: int) -> bool:
    if changed is None or path not in changed:
        return False
    entry = changed[path]
    return entry is None or line in entry


def _origin(changed: dict[str, set[int] | None] | None, path: str, line: int) -> str:
    return "new" if _touches(changed, path, line) else "legacy"


# --- empty-catch -------------------------------------------------------------------


def _strip_c_comments(text: str) -> str:
    without_block = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"//.*$", "", without_block, flags=re.M)


def _matching_brace(source: str, open_index: int) -> int | None:
    depth = 0
    for i in range(open_index, len(source)):
        if source[i] == "{":
            depth += 1
        elif source[i] == "}":
            depth -= 1
            if depth == 0:
                return i
    return None


def _empty_catch_c_style(
    relative: str, source: str, changed: dict[str, set[int] | None] | None
) -> list[Violation]:
    violations = []
    for match in _CATCH_OPEN.finditer(source):
        open_brace = match.end() - 1
        close = _matching_brace(source, open_brace)
        if close is None:
            continue
        body = source[open_brace + 1 : close]
        if not _strip_c_comments(body).strip():
            line = source.count("\n", 0, match.start()) + 1
            violations.append(
                Violation(
                    relative,
                    "catch",
                    line,
                    line,
                    "empty-catch",
                    1,
                    0,
                    _origin(changed, relative, line),
                )
            )
    return violations


def _empty_body(source: str, open_re: re.Pattern[str]) -> list[int]:
    lines = []
    for match in open_re.finditer(source):
        open_brace = match.end() - 1
        close = _matching_brace(source, open_brace)
        if close is None:
            continue
        body = source[open_brace + 1 : close]
        if not _strip_c_comments(body).strip():
            lines.append(source.count("\n", 0, match.start()) + 1)
    return lines


def _empty_go_err(
    relative: str, source: str, changed: dict[str, set[int] | None] | None
) -> list[Violation]:
    return [
        Violation(
            relative,
            "if err != nil",
            line,
            line,
            "empty-catch",
            1,
            0,
            _origin(changed, relative, line),
        )
        for line in _empty_body(source, _GO_ERR_IF)
    ]


def _empty_rust_err(
    relative: str, source: str, changed: dict[str, set[int] | None] | None
) -> list[Violation]:
    violations = []
    for match in _RUST_ERR_ARM.finditer(source):
        line = source.count("\n", 0, match.start()) + 1
        violations.append(
            Violation(
                relative,
                "Err(_)",
                line,
                line,
                "empty-catch",
                1,
                0,
                _origin(changed, relative, line),
            )
        )
    return violations


def _empty_python_except(
    relative: str, source: str, changed: dict[str, set[int] | None] | None
) -> list[Violation]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    violations = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        trivial = all(
            isinstance(stmt, ast.Pass)
            or (
                isinstance(stmt, ast.Expr)
                and isinstance(stmt.value, ast.Constant)
                and stmt.value.value is Ellipsis
            )
            for stmt in node.body
        )
        if trivial:
            violations.append(
                Violation(
                    relative,
                    "except",
                    node.lineno,
                    node.lineno,
                    "empty-catch",
                    1,
                    0,
                    _origin(changed, relative, node.lineno),
                )
            )
    return violations


def empty_catch_violations(
    relative: str, extension: str, source: str, changed: dict[str, set[int] | None] | None = None
) -> list[Violation]:
    if extension == "py":
        return _empty_python_except(relative, source, changed)
    if extension == "go":
        return _empty_go_err(relative, source, changed)
    if extension == "rs":
        return _empty_rust_err(relative, source, changed)
    if extension in _CATCH_EXTENSIONS:
        return _empty_catch_c_style(relative, source, changed)
    return []


# --- todo-ticket ---------------------------------------------------------------------


def _comment_style(extension: str) -> str | None:
    if extension in _HASH_STYLE_EXTENSIONS:
        return "hash"
    if extension in _C_STYLE_EXTENSIONS:
        return "c"
    return None


def _trailing_comment(line: str, style: str) -> str | None:
    pattern = _C_LINE_COMMENT_TRAILING if style == "c" else _HASH_LINE_COMMENT_TRAILING
    match = pattern.search(line)
    return match.group(1) if match else None


def todo_ticket_violations(
    relative: str, extension: str, source: str, changed: dict[str, set[int] | None] | None = None
) -> list[Violation]:
    style = _comment_style(extension)
    if style is None:
        return []
    violations = []
    for i, line in enumerate(source.splitlines(), start=1):
        text = _trailing_comment(line, style)
        if text is None:
            continue
        if TODO_RE.search(text) and not TICKET_RE.search(text):
            violations.append(
                Violation(
                    relative,
                    text.strip()[:60],
                    i,
                    i,
                    "todo-ticket",
                    1,
                    0,
                    _origin(changed, relative, i),
                )
            )
    return violations


# --- commented-code ------------------------------------------------------------------


def _full_line_comments(source: str, style: str) -> list[tuple[int, str]]:
    pattern = _C_LINE_COMMENT_FULL if style == "c" else _HASH_LINE_COMMENT_FULL
    result = []
    for i, line in enumerate(source.splitlines(), start=1):
        match = pattern.match(line)
        if match:
            result.append((i, match.group(1)))
    return result


def _group_consecutive(comments: list[tuple[int, str]]) -> list[list[tuple[int, str]]]:
    groups: list[list[tuple[int, str]]] = []
    current: list[tuple[int, str]] = []
    for line, text in comments:
        if current and line != current[-1][0] + 1:
            groups.append(current)
            current = []
        current.append((line, text))
    if current:
        groups.append(current)
    return groups


def _is_trivial_expr_stmt(stmt: ast.stmt) -> bool:
    return isinstance(stmt, ast.Expr) and isinstance(stmt.value, (ast.Name, ast.Constant))


def _block_looks_like_python(texts: list[str]) -> bool:
    dedented = textwrap.dedent("\n".join(texts))
    try:
        tree = ast.parse(dedented)
    except SyntaxError:
        return False
    # A bare word/prose line (e.g. "Notes", "TODO") parses as a Name/Constant expression
    # statement; require at least one real statement (Assign, Call, def, if/for, ...).
    return any(not _is_trivial_expr_stmt(stmt) for stmt in tree.body)


def commented_code_violations(
    relative: str, extension: str, source: str, changed: dict[str, set[int] | None] | None = None
) -> list[Violation]:
    style = _comment_style(extension)
    if style is None:
        return []
    groups = _group_consecutive(_full_line_comments(source, style))
    violations = []
    for group in groups:
        if len(group) < 2:
            continue
        texts = [text for _, text in group]
        is_code = (
            _block_looks_like_python(texts)
            if extension == "py"
            else any(_looks_like_code(text) for text in texts)
        )
        if not is_code:
            continue
        start_line = group[0][0]
        violations.append(
            Violation(
                relative,
                "comment block",
                start_line,
                group[-1][0],
                "commented-code",
                1,
                0,
                _origin(changed, relative, start_line),
            )
        )
    return violations


# --- driver ----------------------------------------------------------------------


_CHECK_FUNCS = {
    "empty-catch": empty_catch_violations,
    "todo-ticket": todo_ticket_violations,
    "commented-code": commented_code_violations,
}


def hygiene_violations(
    root: Path,
    paths: list[Path],
    checks: tuple[str, ...],
    changed: dict[str, set[int] | None] | None = None,
) -> list[Violation]:
    """Runs the enabled hygiene checks (``empty-catch``/``todo-ticket``/``commented-code``)."""
    active = [name for name in ("empty-catch", "todo-ticket", "commented-code") if name in checks]
    if not active:
        return []
    violations: list[Violation] = []
    for path in paths:
        if not path.is_file():
            continue
        extension = path.suffix.lstrip(".")
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        relative = path.resolve().relative_to(root).as_posix()
        for name in active:
            violations.extend(_CHECK_FUNCS[name](relative, extension, source, changed))
    violations.sort(key=lambda v: (v.path, v.start_line, v.metric))
    return violations
