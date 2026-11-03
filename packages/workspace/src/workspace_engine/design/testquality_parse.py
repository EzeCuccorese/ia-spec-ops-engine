"""Part of ``testquality`` (split out, no behavior change)."""

from __future__ import annotations

import bisect
import re
from dataclasses import dataclass

Changed = dict[str, set[int] | None] | None

_JAVA_EXT = frozenset({"java", "kt", "kts"})


_JS_EXT = frozenset({"js", "jsx", "ts", "tsx", "mjs", "cjs"})


_CLIKE_EXT = _JAVA_EXT | _JS_EXT | {"go"}


_SLEEP_ONLY_EXT = frozenset({"cs", "php", "rs", "dart"})


_MIN_DUPLICATE_LINES = 3


_TOKEN = re.compile(
    r"//[^\n]*"
    r"|/\*.*?(?:\*/|\Z)"
    r'|""".*?(?:"""|\Z)'
    r'|"(?:\\.|[^"\\\n])*(?:"|(?=\n)|\Z)'
    r"|'(?:\\.|[^'\\\n])*(?:'|(?=\n)|\Z)"
    r"|`[^`]*(?:`|\Z)",
    re.S,
)


def _blank(text: str) -> str:
    return re.sub(r"[^\n]", " ", text)


def _mask(source: str) -> tuple[str, str]:
    """Returns ``(masked, code)``: ``code`` has comments blanked, ``masked`` also strings.

    Both keep the exact length and newlines of ``source`` so offsets stay comparable.
    """
    masked: list[str] = []
    code: list[str] = []
    last = 0
    for match in _TOKEN.finditer(source):
        text = match.group()
        for buffer in (masked, code):
            buffer.append(source[last : match.start()])
        last = match.end()
        if text.startswith(("//", "/*")):
            masked.append(_blank(text))
            code.append(_blank(text))
            continue
        code.append(text)
        masked.append(_mask_string(text))
    masked.append(source[last:])
    code.append(source[last:])
    return "".join(masked), "".join(code)


def _mask_string(text: str) -> str:
    if text.startswith('"""'):
        low, high = 3, len(text) - 3 if len(text) >= 6 and text.endswith('"""') else len(text)
    else:
        low, high = 1, len(text) - 1 if len(text) >= 2 and text.endswith(text[0]) else len(text)
    return text[:low] + _blank(text[low:high]) + text[high:]


def _matching(text: str, start: int, open_ch: str, close_ch: str) -> int:
    depth = 0
    for i in range(start, len(text)):
        ch = text[i]
        if ch == open_ch:
            depth += 1
        elif ch == close_ch:
            depth -= 1
            if depth == 0:
                return i
    return -1


@dataclass(frozen=True)
class Parsed:
    relative: str
    ext: str
    masked: str
    code: str
    newlines: tuple[int, ...]

    def line(self, pos: int) -> int:
        return bisect.bisect_right(self.newlines, pos) + 1


def _parse(relative: str, ext: str, source: str) -> Parsed:
    masked, code = _mask(source)
    newlines = tuple(i for i, ch in enumerate(source) if ch == "\n")
    return Parsed(relative, ext, masked, code, newlines)


def _split_args(masked: str, code: str, start: int, end: int) -> list[str]:
    args: list[str] = []
    depth = 0
    piece = start
    for i in range(start, end):
        ch = masked[i]
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif ch == "," and depth == 0:
            args.append(code[piece:i].strip())
            piece = i + 1
    tail = code[piece:end].strip()
    if tail or args:
        args.append(tail)
    return args


_IDENT = re.compile(r"[A-Za-z_$][\w$]*")


def _chain(p: Parsed, pos: int) -> list[tuple[str, list[str]]]:
    """Method chain after a call: ``.a(x).b`` gives ``[("a", ["x"]), ("b", [])]``."""
    masked = p.masked
    size = len(masked)
    links: list[tuple[str, list[str]]] = []
    i = pos
    while True:
        j = _skip_space(masked, i)
        if j >= size or masked[j] != ".":
            break
        found = _IDENT.match(masked, _skip_space(masked, j + 1))
        if not found:
            break
        k = _skip_space(masked, found.end())
        args: list[str] = []
        if k < size and masked[k] == "(":
            close = _matching(masked, k, "(", ")")
            if close < 0:
                break
            args = _split_args(masked, p.code, k + 1, close)
            k = close + 1
        links.append((found.group(), args))
        i = k
    return links


def _skip_space(text: str, i: int) -> int:
    while i < len(text) and text[i] in " \t\r\n":
        i += 1
    return i


@dataclass(frozen=True)
class CaseUnit:
    """One test function: offsets of the whole test and of its body."""

    name: str
    start: int
    end: int
    body_start: int
    body_end: int
    group: int = -1
    skip: bool = False
    asserting: bool = False
