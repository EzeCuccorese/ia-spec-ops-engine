"""
workspace_engine.design.testquality — junk-test checks, applied to test files only.

Deterministic scanners (no external tools) enforcing the testing rule from the
ai-governance catalog: a test must assert observable behavior.

- ``test-no-assert``: a test function without any assertion.
- ``test-trivial-assert``: an assertion that can never fail (constant or self-comparison).
- ``test-mock-only``: every assertion of a test targets a mock; no result or state is checked.
- ``test-sleep``: a real sleep inside a test file.
- ``test-duplicate``: a test whose body repeats an earlier test of the same file.

Priority languages are Java/Kotlin (JUnit, AssertJ, Mockito), JS/TS (Jest/Vitest), Python
(``ast``) and Go (``testing``/testify). C#, PHP, Rust and Dart get the sleep check only.
Each finding is a ``Violation`` with ``value=1`` and ``limit=0``.
"""

from __future__ import annotations

import ast
import bisect
import copy
import re
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from .metrics import Violation

Changed = dict[str, set[int] | None] | None

TEST_CHECKS = (
    "test-no-assert",
    "test-trivial-assert",
    "test-mock-only",
    "test-sleep",
    "test-duplicate",
)

_JAVA_EXT = frozenset({"java", "kt", "kts"})
_JS_EXT = frozenset({"js", "jsx", "ts", "tsx", "mjs", "cjs"})
_CLIKE_EXT = _JAVA_EXT | _JS_EXT | {"go"}
_SLEEP_ONLY_EXT = frozenset({"cs", "php", "rs", "dart"})

_MIN_DUPLICATE_LINES = 3


# --- test-file detection -------------------------------------------------------------


def _in_segments(parts: list[str], *wanted: str) -> bool:
    size = len(wanted)
    return any(parts[i : i + size] == list(wanted) for i in range(len(parts) - size + 1))


def _java_test_path(name: str, directories: list[str], source: str) -> bool:
    return _in_segments(directories, "src", "test") or bool(
        re.search(r"(?:Tests?|IT)\.(?:java|kt)$", name)
    )


def _js_test_path(name: str, directories: list[str], source: str) -> bool:
    return bool(re.search(r"\.(?:test|spec)\.", name)) or "__tests__" in directories


def _py_test_path(name: str, directories: list[str], source: str) -> bool:
    return name.startswith("test_") or name.endswith("_test.py") or "tests" in directories


def _rust_test_path(name: str, directories: list[str], source: str) -> bool:
    return "#[test]" in source or "::test]" in source


def _suffix_rule(suffix: str) -> Callable[[str, list[str], str], bool]:
    return lambda name, directories, source: name.endswith(suffix)


_TEST_PATH_RULES: dict[str, Callable[[str, list[str], str], bool]] = {
    **dict.fromkeys(_JAVA_EXT, _java_test_path),
    **dict.fromkeys(_JS_EXT, _js_test_path),
    "py": _py_test_path,
    "go": _suffix_rule("_test.go"),
    "cs": _suffix_rule("Tests.cs"),
    "php": _suffix_rule("Test.php"),
    "dart": _suffix_rule("_test.dart"),
    "rs": _rust_test_path,
}


def is_test_file(relative: str, extension: str, source: str) -> bool:
    """Whether ``relative`` is a test file according to its language's conventions."""
    rule = _TEST_PATH_RULES.get(extension)
    parts = relative.split("/")
    return rule is not None and rule(parts[-1], parts[:-1], source)


# --- parsing helpers -----------------------------------------------------------------

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


# --- test units ----------------------------------------------------------------------


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


_JAVA_TEST_ANNOTATION = re.compile(
    r"@(?:[\w.]*\.)?(?:Test|ParameterizedTest|RepeatedTest|TestFactory|TestTemplate)\b"
)
_ANNOTATED_NAME = re.compile(r"(@?)(`[^`]*`|[\w.$]+)\s*$")
_SKIP_ANNOTATION = re.compile(r"@(?:Disabled|Ignore)\b")
_EXPECTED_ATTRIBUTE = re.compile(r"\bexpected\w*\s*=")


def _expression_end(masked: str, start: int) -> int:
    depth = 0
    for i in range(_skip_space(masked, start), len(masked)):
        ch = masked[i]
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif ch == "\n" and depth <= 0:
            follow = _skip_space(masked, i)
            if follow >= len(masked) or masked[follow] not in ".?":
                return i
    return len(masked)


def _paren_name(p: Parsed, open_paren: int, current: str) -> str:
    found = _ANNOTATED_NAME.search(p.code[max(0, open_paren - 200) : open_paren])
    return found.group(2) if found and not found.group(1) else current


def _signature_body(p: Parsed, i: int, name: str) -> tuple[str, int, int] | None:
    ch = p.masked[i]
    if ch == ";":
        return None
    if ch == "=":
        return name, i + 1, _expression_end(p.masked, i + 1)
    close = _matching(p.masked, i, "{", "}")
    return (name, i + 1, close) if close >= 0 else None


def _java_signature(p: Parsed, pos: int) -> tuple[str, int, int] | None:
    masked = p.masked
    name = "?"
    i = pos
    while i < len(masked):
        ch = masked[i]
        if ch == "(":
            close = _matching(masked, i, "(", ")")
            if close < 0:
                return None
            name = _paren_name(p, i, name)
            i = close + 1
        elif ch in "{;" or (ch == "=" and name != "?"):
            return _signature_body(p, i, name)
        else:
            i += 1
    return None


def _java_units(p: Parsed) -> list[CaseUnit]:
    units = []
    for match in _JAVA_TEST_ANNOTATION.finditer(p.masked):
        signature = _java_signature(p, match.end())
        if signature is None:
            continue
        name, body_start, body_end = signature
        header = p.code[match.start() : body_start]
        previous = "\n".join(p.code[: match.start()].splitlines()[-3:])
        units.append(
            CaseUnit(
                name.strip("`"),
                match.start(),
                body_end,
                body_start,
                body_end,
                skip=bool(_SKIP_ANNOTATION.search(previous + header)),
                asserting=bool(_EXPECTED_ATTRIBUTE.search(header)),
            )
        )
    return units


_JS_CASE = re.compile(r"(?<![\w.$])(?:it|test)((?:\s*\.\s*\w+)*)\s*[(`]")
_JS_GROUP = re.compile(r"(?<![\w.$])(?:describe|context|suite)((?:\s*\.\s*\w+)*)\s*[(`]")
_JS_SKIPPED = re.compile(r"\b(?:skip|todo|failing)\b")


def _js_call_span(masked: str, match: re.Match[str]) -> tuple[int, int] | None:
    """Span ``(open, close)`` of the argument list of a describe/it call."""
    pos = match.end() - 1
    if re.search(r"\beach\b", match.group(1)):
        if masked[pos] == "(":
            pos = _matching(masked, pos, "(", ")") + 1
        else:
            pos = masked.find("`", pos + 1) + 1
        pos = _skip_space(masked, pos)
        if pos <= 0 or pos >= len(masked) or masked[pos] != "(":
            return None
    if masked[pos] != "(":
        return None
    close = _matching(masked, pos, "(", ")")
    return (pos, close) if close >= 0 else None


def _js_groups(p: Parsed) -> list[tuple[int, int]]:
    spans = (_js_call_span(p.masked, m) for m in _JS_GROUP.finditer(p.masked))
    return [span for span in spans if span]


def _js_units(p: Parsed) -> list[CaseUnit]:
    groups = _js_groups(p)
    units = []
    for match in _JS_CASE.finditer(p.masked):
        span = _js_call_span(p.masked, match)
        if span is None or _JS_SKIPPED.search(match.group(1)):
            continue
        body = p.masked[span[0] + 1 : span[1]]
        if "=>" not in body and not re.search(r"\bfunction\b", body):
            continue
        enclosing = [g[0] for g in groups if g[0] < match.start() < g[1]]
        units.append(
            CaseUnit(
                _js_title(p, span[0] + 1),
                match.start(),
                span[1],
                span[0] + 1,
                span[1],
                group=max(enclosing, default=-1),
            )
        )
    return units


def _js_title(p: Parsed, pos: int) -> str:
    found = re.compile(r"\s*(['\"`])(.*?)\1", re.S).match(p.code, pos)
    return found.group(2)[:60] if found else "<test>"


_GO_TEST = re.compile(r"\bfunc\s+(\(\s*\w+\s+\*?\w+\s*\)\s*)?(Test\w*)\s*\(([^)]*)\)\s*\{")
_GO_SKIP = re.compile(r"\.\s*Skip(?:Now|f)?\s*\(")


def _go_units(p: Parsed) -> list[CaseUnit]:
    units = []
    for match in _GO_TEST.finditer(p.masked):
        receiver, name, params = match.groups()
        if "testing.T" not in params and not (receiver and not params.strip()):
            continue
        open_brace = match.end() - 1
        close = _matching(p.masked, open_brace, "{", "}")
        if close < 0:
            continue
        skip = bool(_GO_SKIP.search(p.masked, open_brace, close))
        units.append(CaseUnit(name, match.start(), close, open_brace + 1, close, skip=skip))
    return units


def _clike_units(p: Parsed) -> list[CaseUnit]:
    if p.ext in _JAVA_EXT:
        return _java_units(p)
    if p.ext in _JS_EXT:
        return _js_units(p)
    return _go_units(p)


# --- assertions ----------------------------------------------------------------------

_KindRule = tuple[re.Pattern[str], str | Callable[[Parsed, re.Match[str]], str]]

_JAVA_MOCK = re.compile(
    r"\b(?:coVerify|verify)(?:NoMoreInteractions|NoInteractions|ZeroInteractions|All|Order"
    r"|Sequence|Ordering)?\s*[({]"
)
_JAVA_THEN = re.compile(r"(?<![\w.$])then\s*\(|\bBDDMockito\s*\.\s*then\s*\(")
_JAVA_STATE = re.compile(
    r"(?<![\w$])(?:assert\w*|expect\w*|check\w*|verify\w*|fail)\s*\("
    r"|\.\s*andExpect\w*\s*\("
    r"|\bshould(?!HaveNo)[A-Z]\w*"
)

_JS_EXPECT = re.compile(r"(?<![\w$])expect\s*\(")
_JS_SINON = re.compile(
    r"(?<![\w$])assert\s*\.\s*(?:called\w*|notCalled|callCount|neverCalledWith\w*"
    r"|alwaysCalledWith\w*)"
)
_JS_STATE = re.compile(
    r"(?<![\w$])(?:assert\w*\s*[.(]|expect\w+\s*[(.]|expect\s*\.|check\w*\s*[(.]"
    r"|verify\w*\s*[(.]|fail\s*\()"
    r"|\.\s*(?:rejects|resolves|should)\b|\bshould\s*\."
    r"|\b(?:get|find)(?:All)?By\w+\s*\("
    r"|(?<![\w$])t\s*\.\s*(?:ok|is|not|equal|notEqual|deepEqual|true|false|truthy|falsy"
    r"|throws|throwsAsync|rejects|pass|same|like|snapshot)\s*\("
)
_JS_MOCK_MATCHER = re.compile(
    r"^(?:toHaveBeen(?:Last|Nth)?Called\w*|toBeCalled\w*|(?:last|nth)CalledWith"
    r"|toHaveReturned\w*|toHave(?:Last|Nth)ReturnedWith|toReturn\w*|called\w*|notCalled)$"
)

_GO_MOCK = re.compile(
    r"(?<=\.)(?:AssertExpectations|AssertCalled|AssertNotCalled|AssertNumberOfCalls"
    r"|AssertExpectationsForObjects)\s*\(|\bEXPECT\s*\(\s*\)"
)
_GO_STATE = re.compile(
    r"\b(?:assert|require)\s*\.\s*\w+"
    r"|(?<![\w$])(?:[Aa]ssert|[Ee]xpect|[Cc]heck|[Vv]erify)\w*\s*\("
    r"|\b(?:s|suite)\s*\.\s*(?:Equal|NotEqual|True|False|Nil|NotNil|NoError|Error|Len|Contains"
    r"|Empty|NotEmpty|Zero|Panics|EqualError|ErrorIs|Require|Assert)\w*\s*\("
    r"|\.\s*T\(\)\s*\.\s*(?:Errorf?|Fatalf?)\s*\("
)
_GO_T_NAME = re.compile(r"(\w+)\s+\*testing\.[TB]\b")


def _then_kind(p: Parsed, match: re.Match[str]) -> str:
    open_paren = match.end() - 1
    close = _matching(p.masked, open_paren, "(", ")")
    links = _chain(p, close + 1) if close >= 0 else []
    return "mock" if links and links[0][0].startswith("should") else "state"


def _expect_kind(p: Parsed, match: re.Match[str]) -> str:
    open_paren = match.end() - 1
    close = _matching(p.masked, open_paren, "(", ")")
    links = _chain(p, close + 1) if close >= 0 else []
    return "mock" if any(_JS_MOCK_MATCHER.match(name) for name, _ in links) else "state"


@lru_cache(maxsize=64)
def _go_receiver_rule(names: tuple[str, ...]) -> re.Pattern[str]:
    joined = "|".join(re.escape(n) for n in names)
    return re.compile(rf"\b(?:{joined})\s*\.\s*(?:Errorf?|Fatalf?|Fail|FailNow)\s*\(")


def _rules(p: Parsed, unit: CaseUnit) -> list[_KindRule]:
    if p.ext in _JAVA_EXT:
        return [
            (_JAVA_MOCK, "mock"),
            (_JAVA_THEN, _then_kind),
            (_JAVA_STATE, "state"),
        ]
    if p.ext in _JS_EXT:
        return [
            (_JS_SINON, "mock"),
            (_JS_EXPECT, _expect_kind),
            (_JS_STATE, "state"),
        ]
    names = {"t"} | set(_GO_T_NAME.findall(p.masked[unit.start : unit.body_start]))
    names |= set(_GO_T_NAME.findall(p.masked[unit.body_start : unit.body_end]))
    return [
        (_GO_MOCK, "mock"),
        (_GO_STATE, "state"),
        (_go_receiver_rule(tuple(sorted(names))), "state"),
    ]


def _unit_assertions(p: Parsed, unit: CaseUnit) -> list[str]:
    """Kinds (``"state"`` or ``"mock"``) of the assertions found in one test unit."""
    found: dict[int, str] = {}
    for pattern, kind in _rules(p, unit):
        for match in pattern.finditer(p.masked, unit.body_start, unit.body_end):
            resolved = kind if isinstance(kind, str) else kind(p, match)
            found.setdefault(match.start(), resolved)
    return list(found.values())


# --- trivial assertions --------------------------------------------------------------

_CALL = re.compile(r"((?:[A-Za-z_$][\w$]*\s*\.\s*)*)([A-Za-z_$][\w$]*)\s*\(")
_TRUE_ANY = frozenset({"assertTrue"})
_FALSE_ANY = frozenset({"assertFalse"})
_EQUAL_ANY = frozenset(
    {"assertEquals", "assertEqual", "assertSame", "assertArrayEquals", "assertIterableEquals"}
)
_NULL_ANY = frozenset({"assertNull"})
_ASSERT_RECEIVERS = frozenset(
    {"assert", "require", "a", "r", "is", "s", "suite", "Assert", "Assertions", "chai"}
)
_TRUE_RECEIVER = frozenset({"True", "ok", "isTrue"})
_FALSE_RECEIVER = frozenset({"False", "isFalse"})
_EQUAL_RECEIVER = frozenset(
    {
        "Equal",
        "EqualValues",
        "Exactly",
        "Same",
        "equal",
        "strictEqual",
        "deepEqual",
        "deepStrictEqual",
        "eq",
        "equals",
        "isEqual",
    }
)
_NULL_RECEIVER = frozenset({"Nil", "isNull"})

_SUBJECT = re.compile(r"(?<![\w$])(assertThat|expect|then)\s*\(")
_NEGATIONS = frozenset({"not", "isNot", "isNotEqualTo", "isNotSameAs", "notToBe"})
_EQUAL_MATCHERS = frozenset(
    {"toBe", "toEqual", "toStrictEqual", "isEqualTo", "isSameAs", "equal", "equals", "eql", "eq"}
)
_TRUE_MATCHERS = frozenset({"toBeTruthy", "isTrue", "toBeTrue", "beTrue"})
_FALSE_MATCHERS = frozenset({"toBeFalsy", "isFalse", "toBeFalse", "beFalse"})
_TEST_HANDLE = re.compile(r"^(?:t|tb|tt|s\.T\(\))$")


def _squash(text: str) -> str:
    return re.sub(r"\s+", "", text)


def _same(left: str, right: str) -> bool:
    if not left or "(" in left or "++" in left or "--" in left:
        return False
    return _squash(left) == _squash(right)


def _has_same_neighbours(args: list[str]) -> bool:
    return any(_same(args[i], args[i + 1]) for i in range(len(args) - 1))


_CALL_RULES: tuple[tuple[frozenset[str], frozenset[str], Callable[[list[str]], bool]], ...] = (
    (_TRUE_ANY, _TRUE_RECEIVER, lambda args: "true" in args),
    (_FALSE_ANY, _FALSE_RECEIVER, lambda args: "false" in args),
    (_NULL_ANY, _NULL_RECEIVER, lambda args: any(a in ("null", "nil") for a in args)),
    (_EQUAL_ANY, _EQUAL_RECEIVER, _has_same_neighbours),
)


def _trivial_call(receiver: str, leaf: str, args: list[str]) -> bool:
    scoped = receiver in _ASSERT_RECEIVERS
    if scoped and args and _TEST_HANDLE.match(args[0]):
        args = args[1:]
    for any_names, receiver_names, check in _CALL_RULES:
        if leaf in any_names or (scoped and leaf in receiver_names):
            return check(args)
    return leaf == "assert" and not receiver and "true" in args


def _link_is_trivial(subject: str, name: str, args: list[str]) -> bool:
    if name in _EQUAL_MATCHERS:
        return len(args) == 1 and _same(subject, args[0])
    return (name in _TRUE_MATCHERS and subject == "true") or (
        name in _FALSE_MATCHERS and subject == "false"
    )


def _trivial_chain(subject: str, links: list[tuple[str, list[str]]]) -> bool:
    if any(name in _NEGATIONS for name, _ in links):
        return False
    return any(_link_is_trivial(subject, name, args) for name, args in links)


def _trivial_clike(p: Parsed) -> list[tuple[int, str]]:
    hits: list[tuple[int, str]] = []
    for match in _CALL.finditer(p.masked):
        open_paren = match.end() - 1
        close = _matching(p.masked, open_paren, "(", ")")
        if close < 0:
            continue
        receiver = re.split(r"\s*\.\s*", match.group(1).strip().rstrip("."))[-1].strip()
        args = _split_args(p.masked, p.code, open_paren + 1, close)
        if _trivial_call(receiver, match.group(2), args):
            hits.append((p.line(match.start(2)), _squash(p.code[match.start(2) : close + 1])))
    for match in _SUBJECT.finditer(p.masked):
        open_paren = match.end() - 1
        close = _matching(p.masked, open_paren, "(", ")")
        if close < 0:
            continue
        args = _split_args(p.masked, p.code, open_paren + 1, close)
        if len(args) == 1 and _trivial_chain(args[0], _chain(p, close + 1)):
            hits.append((p.line(match.start()), _squash(p.code[match.start() : close + 1])))
    return hits


# --- sleep ---------------------------------------------------------------------------

_SLEEP_PATTERNS: dict[str, tuple[str, ...]] = {
    "java": (r"\bThread\s*\.\s*sleep\s*\(", r"\bTimeUnit\s*\.\s*\w+\s*\.\s*sleep\s*\("),
    "go": (r"\btime\s*\.\s*Sleep\s*\(",),
    "cs": (r"\bThread\s*\.\s*Sleep\s*\(", r"\bTask\s*\.\s*Delay\s*\("),
    "php": (r"(?<![\w>:$])u?sleep\s*\(",),
    "rs": (r"\bthread\s*::\s*sleep\s*\(",),
    "dart": (r"\bFuture\s*\.\s*delayed\s*\(",),
}
_JS_SLEEP = re.compile(
    r"\bawait\s+(?:timers\s*\.\s*)?(?:setTimeout|sleep|delay)\s*\("
    r"|\bwaitForTimeout\s*\(|\bcy\s*\.\s*wait\s*\(\s*\d"
)
_JS_PROMISE = re.compile(r"\bawait\s+new\s+Promise\s*\(")
_FAKE_TIMERS = re.compile(r"\b(?:useFakeTimers|fakeTimers|FakeTimers)\b")


def _sleep_family(ext: str) -> str:
    return "java" if ext in _JAVA_EXT else ext


def _js_sleeps(p: Parsed) -> list[tuple[int, str]]:
    if _FAKE_TIMERS.search(p.masked):
        return []
    hits = [
        (p.line(m.start()), _squash(m.group().rstrip("("))) for m in _JS_SLEEP.finditer(p.masked)
    ]
    for match in _JS_PROMISE.finditer(p.masked):
        close = _matching(p.masked, match.end() - 1, "(", ")")
        if close > 0 and re.search(r"\bsetTimeout\s*\(", p.masked[match.end() : close]):
            hits.append((p.line(match.start()), "await new Promise(setTimeout)"))
    return hits


def _sleep_hits(p: Parsed) -> list[tuple[int, str]]:
    if p.ext in _JS_EXT:
        return _js_sleeps(p)
    hits: list[tuple[int, str]] = []
    for pattern in _SLEEP_PATTERNS.get(_sleep_family(p.ext), ()):
        hits.extend(
            (p.line(m.start()), _squash(m.group().rstrip("(")))
            for m in re.finditer(pattern, p.masked)
        )
    return hits


# --- duplicates ----------------------------------------------------------------------

_DECLARATIONS = (
    re.compile(r"\b(?:const|let|var|val|final)\s+(\w+)"),
    re.compile(
        r"\b(?:[A-Z]\w*(?:<[^;=()]*>)?|int|long|double|float|boolean|char|byte|short|var)"
        r"(?:\[\])*\s+(\w+)\s*="
    ),
    re.compile(r"\b(\w+(?:\s*,\s*\w+)*)\s*:="),
    re.compile(r"\b(\w+)\s*(?:->|=>)"),
)
_STRING_BLANK = re.compile(r"\"[ \n]*\"|'[ ]*'|`[ \n]*`")


def _local_names(text: str) -> list[str]:
    found: list[tuple[int, str]] = []
    for pattern in _DECLARATIONS:
        for match in pattern.finditer(text):
            for offset, name in _split_names(match):
                found.append((offset, name))
    ordered: dict[str, None] = {}
    for _, name in sorted(found):
        ordered.setdefault(name, None)
    return list(ordered)


def _split_names(match: re.Match[str]) -> list[tuple[int, str]]:
    names = re.findall(r"\w+", match.group(1))
    return [(match.start(1), name) for name in names]


_CONTINUATION = re.compile(r"^\s*(?:[.)\]}+?:]|&&|\|\|)")


def _statement_count(body: str) -> int:
    """Lines that start a statement: not blank and not a continuation of the previous one."""
    lines = body.splitlines()
    return sum(1 for line in lines if re.search(r"\w", line) and not _CONTINUATION.match(line))


def _clike_fingerprint(p: Parsed, unit: CaseUnit) -> str | None:
    body = p.masked[unit.body_start : unit.body_end]
    if _statement_count(body) < _MIN_DUPLICATE_LINES:
        return None
    text = _STRING_BLANK.sub("S", body)
    text = re.sub(r"\b\d[\w.]*", "N", text)
    locals_ = _local_names(text)
    if locals_:
        mapping = {name: f"V{i}" for i, name in enumerate(locals_)}
        text = re.sub(
            r"\b(?:" + "|".join(map(re.escape, mapping)) + r")\b",
            lambda m: mapping[m.group()],
            text,
        )
    return re.sub(r"\s+", " ", text).strip()


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


# --- results -------------------------------------------------------------------------


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


# --- python --------------------------------------------------------------------------

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


def _py_sleeps(tree: ast.Module) -> list[tuple[int, str]]:
    imported = any(
        isinstance(n, ast.ImportFrom)
        and n.module == "time"
        and any(a.name == "sleep" for a in n.names)
        for n in ast.walk(tree)
    )
    return [
        (node.lineno, "time.sleep")
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and _py_is_sleep(node, imported)
    ]


def _python_violations(job: _Job, source: str) -> list[Violation]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    out = _case_violations(job, _py_cases(tree))
    return out + _extra_violations(job, _py_trivial(tree), _py_sleeps(tree))


# --- driver --------------------------------------------------------------------------


def _file_violations(job: _Job, ext: str, source: str) -> list[Violation]:
    if ext == "py":
        return _python_violations(job, source)
    if ext in _CLIKE_EXT:
        return _clike_violations(job, ext, source)
    if ext in _SLEEP_ONLY_EXT and "test-sleep" in job.active:
        return job.line_hits(_sleep_hits(_parse(job.relative, ext, source)), "test-sleep")
    return []


def junk_test_violations(
    root: Path, paths: list[Path], checks: tuple[str, ...], changed: Changed = None
) -> list[Violation]:
    """Runs the enabled ``test-*`` checks over the test files among ``paths``."""
    active = {name for name in TEST_CHECKS if name in checks}
    if not active:
        return []
    violations: list[Violation] = []
    for path in paths:
        if not path.is_file():
            continue
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        relative = path.resolve().relative_to(root).as_posix()
        ext = path.suffix.lstrip(".")
        if is_test_file(relative, ext, source):
            violations.extend(_file_violations(_Job(relative, active, changed), ext, source))
    violations.sort(key=lambda v: (v.path, v.start_line, v.metric))
    return violations
