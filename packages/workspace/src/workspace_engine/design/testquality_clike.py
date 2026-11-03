"""Part of ``testquality`` (split out, no behavior change)."""

from __future__ import annotations

import re
from collections.abc import Callable
from functools import lru_cache

from .testquality_parse import (
    _JAVA_EXT,
    _JS_EXT,
    _MIN_DUPLICATE_LINES,
    CaseUnit,
    Parsed,
    _chain,
    _matching,
    _skip_space,
    _split_args,
)

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
