"""Prompt text and verdict parsing shared by dispatched rounds and judges.

The engine never launches an agent: a reader round is a spec file an Orca worker reads and
an answer file the engine parses afterwards. This module holds the two sentences every
reader spec carries, the cross-examination block of a rebuttal round, and the parsers of the
verdict line and the ``CHANGE:`` lines a validator or judge writes.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

READ_ONLY_LIMIT = (
    "Do not modify files, commit, push or run commands that change the repository or the "
    "environment. Do not delegate to subagents. Mark each claim as seen/assumed/unknown.\n\n"
)
CROSS_EXAMINATION = (
    "\n\nCross-examination: before answering, read these earlier rounds of this task in full:\n"
    "{rounds}\n"
    "Structure your answer as: A) what each of them gets right and wrong, citing their text "
    "and refuting weak claims with evidence (code, a command you ran, a counterexample); "
    "B) the evidence you produced yourself; C) your final position after absorbing the "
    "strongest opposing arguments. Say explicitly where you changed your mind."
)
THESIS_INSTRUCTION = (
    "\n\nYou are one seat in a design debate. Other agents answer the same question without seeing your answer. "
    "Take a position and defend it with evidence you produced (code you read, a command or throwaway script you ran in the scratch directory). "
    "List the assumptions that would change your mind. End with one line exactly like `POSITION: <one sentence>`."
)
CROSS_INSTRUCTION = (
    "\n\nFor each claim of another seat you address, write one line exactly like\n"
    "`REBUT: round <NNN> | <their claim> | <your evidence> | refuted|agreed|open`.\n"
    "For each change in your own position write\n"
    "`CHANGED: <what you changed> | round <NNN>`.\n"
    "End with one line exactly like `POSITION: <one sentence>`."
)
WEB_INSTRUCTION = "\n\nYou may research the web. Every claim that rests on an external source carries its URL; a claim with no URL counts as assumed."
_CHANGE = re.compile(r"^\s*[-*]?\s*CHANGE:\s*(\S.*?)\s*$", re.MULTILINE)
_ANSWER_HEADING = re.compile(r"^## Answer[ \t]*(?:\r?\n|$)", re.MULTILINE)
_REQUEST_HEADING = re.compile(r"^## Request[ \t]*(?:\r?\n|$)", re.MULTILINE)
_FOOTER_ANSWER_BOUNDARY = re.compile(r"\n\(task [^)\n]+\)\s*\n+## Answer[ \t]*(?:\r?\n|$)")
_ROUND_ENVELOPE_HEADER = re.compile(
    r"^# Round \d{3} · [^\n]+\r?\n\r?\n- Date: [^\n]+\r?\n- Code stamp: "
)
_BULLET_PREFIX = re.compile(r"^([-*]\s+)(.*)$")
_BOLD_KEYWORD = re.compile(r"^\*\*(REBUT|CHANGED|POSITION)(?::\*\*|\*\*:)")
_POSITION = re.compile(r"^\s*(?:[-*]\s*)?POSITION:\s*(.+?)\s*$", re.MULTILINE)
_REBUT_LINE = re.compile(r"^\s*[-*]?\s*REBUT:(.*)$")
_CHANGED_LINE = re.compile(r"^\s*[-*]?\s*CHANGED:(.*)$")
_ROUND_REF = re.compile(r"^round\s+(\d+)$", re.IGNORECASE)
_REBUT_OUTCOMES = frozenset({"refuted", "agreed", "open"})


@dataclass(frozen=True)
class RebutLine:
    target: int
    claim: str
    evidence: str
    outcome: str


@dataclass(frozen=True)
class ChangedLine:
    change: str
    target: int


def parse_changes(answer: str) -> list[str]:
    """The ``CHANGE: <path>:<line> - <fix>`` lines of an answer, in order."""
    return _CHANGE.findall(answer)


def cross_examination(rounds: list[tuple[int, str, str]]) -> str:
    """The cross-examination block for ``(number, agent, file)`` of each round to refute."""
    lines = "\n".join(f"- round {n:03d} ({agent}): {path}" for n, agent, path in rounds)
    return CROSS_EXAMINATION.format(rounds=lines)


def artifact_instruction(paths: Sequence[str | Path]) -> str:
    """Instruction requiring the worker to inspect each attached artifact before citing it."""
    if not paths:
        return ""
    return (
        "\n\nOpen each of these files and describe what you saw before using it as evidence; "
        "do not argue from the file name:\n" + "\n".join(f"- {p}" for p in paths)
    )


def answer_section(text: str) -> str:
    """Text after the round's ``## Answer`` boundary, or ``text`` when already unwrapped."""
    if boundary := _FOOTER_ANSWER_BOUNDARY.search(text):
        return text[boundary.end() :]
    if (
        _ROUND_ENVELOPE_HEADER.match(text.lstrip()) is not None
        and (request := _REQUEST_HEADING.search(text))
        and (answer := _ANSWER_HEADING.search(text, request.end()))
    ):
        return text[answer.end() :]
    return text


def _unwrap_backticks(text: str) -> str:
    if len(text) >= 2 and text.startswith("`") and text.endswith("`") and text.count("`") == 2:
        return text[1:-1].strip()
    return text


def _normalize_structured_line(line: str) -> str:
    stripped = line.strip()
    prefix = ""
    content = stripped
    if match := _BULLET_PREFIX.match(stripped):
        prefix, content = match.group(1), match.group(2)
    content = _unwrap_backticks(content)
    content = _BOLD_KEYWORD.sub(r"\1:", content)
    return prefix + content


def parse_position(answer: str, *, unwrapped: bool = False) -> str:
    """Last valid ``POSITION: <sentence>`` line in ``answer``, or empty string."""
    body = answer if unwrapped else answer_section(answer)
    last = ""
    for line in body.splitlines():
        match = _POSITION.match(_normalize_structured_line(line))
        if match is None:
            continue
        cleaned = _unwrap_backticks(match.group(1).strip())
        if cleaned and cleaned != "<one sentence>":
            last = cleaned
    return last


def _parse_round_ref(field: str) -> int | None:
    match = _ROUND_REF.fullmatch(field.strip())
    return int(match.group(1)) if match else None


def _normalize_outcome(raw: str) -> str:
    token = raw.strip()
    had_dot = token.endswith(".")
    if had_dot:
        token = token[:-1].strip()
    token = _unwrap_backticks(token)
    if len(token) > 4 and token.startswith("**") and token.endswith("**"):
        token = token[2:-2].strip()
    token = _unwrap_backticks(token)
    if not had_dot and token.endswith("."):
        token = token[:-1].strip()
    return token.lower()


def _parse_rebut_body(body: str) -> RebutLine | None:
    parts = [part.strip() for part in body.split("|")]
    if len(parts) != 4:
        return None
    target = _parse_round_ref(parts[0])
    claim, evidence, outcome = parts[1], parts[2], _normalize_outcome(parts[3])
    if target is None or not claim or not evidence or outcome not in _REBUT_OUTCOMES:
        return None
    return RebutLine(target=target, claim=claim, evidence=evidence, outcome=outcome)


def parse_rebuts(answer: str, *, unwrapped: bool = False) -> tuple[list[RebutLine], list[str]]:
    """Valid ``REBUT:`` entries and raw malformed ``REBUT:`` lines from ``answer``."""
    body = answer if unwrapped else answer_section(answer)
    valid: list[RebutLine] = []
    malformed: list[str] = []
    for line in body.splitlines():
        match = _REBUT_LINE.match(_normalize_structured_line(line))
        if match is None:
            continue
        parsed = _parse_rebut_body(match.group(1))
        if parsed is not None:
            valid.append(parsed)
        else:
            malformed.append(line.strip())
    return valid, malformed


def _parse_changed_body(body: str) -> ChangedLine | None:
    parts = [part.strip() for part in body.split("|")]
    if len(parts) != 2:
        return None
    change, target = parts[0], _parse_round_ref(parts[1])
    if not change or target is None:
        return None
    return ChangedLine(change=change, target=target)


def parse_changed(answer: str, *, unwrapped: bool = False) -> tuple[list[ChangedLine], list[str]]:
    """Valid ``CHANGED:`` entries and raw malformed ``CHANGED:`` lines from ``answer``."""
    body = answer if unwrapped else answer_section(answer)
    valid: list[ChangedLine] = []
    malformed: list[str] = []
    for line in body.splitlines():
        match = _CHANGED_LINE.match(_normalize_structured_line(line))
        if match is None:
            continue
        parsed = _parse_changed_body(match.group(1))
        if parsed is not None:
            valid.append(parsed)
        else:
            malformed.append(line.strip())
    return valid, malformed
