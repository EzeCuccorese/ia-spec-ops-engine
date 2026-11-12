"""Prompt text and verdict parsing shared by dispatched rounds and judges.

The engine never launches an agent: a reader round is a spec file an Orca worker reads and
an answer file the engine parses afterwards. This module holds the two sentences every
reader spec carries, the cross-examination block of a rebuttal round, and the parsers of the
verdict line and the ``CHANGE:`` lines a validator or judge writes.
"""

from __future__ import annotations

import re

READ_ONLY_LIMIT = (
    "Do not modify files, commit, push or run commands that change the repository or the "
    "environment. Do not delegate to subagents. Mark each claim as seen/assumed/unknown.\n\n"
)
VERDICT_INSTRUCTION = (
    "\n\nBefore a `concerns` or `block` verdict, list every required change on its own line "
    "as `CHANGE: <path>:<line> - <what to change>`.\n"
    "End your answer with one line exactly like `VERDICT: pass`, `VERDICT: concerns` or "
    "`VERDICT: block` (block = changes required or evidence missing)."
)
CROSS_EXAMINATION = (
    "\n\nCross-examination: before answering, read these earlier rounds of this task in full:\n"
    "{rounds}\n"
    "Structure your answer as: A) what each of them gets right and wrong, citing their text "
    "and refuting weak claims with evidence (code, a command you ran, a counterexample); "
    "B) the evidence you produced yourself; C) your final position after absorbing the "
    "strongest opposing arguments. Say explicitly where you changed your mind."
)
_CHANGE = re.compile(r"^\s*[-*]?\s*CHANGE:\s*(\S.*?)\s*$", re.MULTILINE)
_VERDICT = re.compile(
    r"(?:verdict|dictamen|veredicto)\W{0,6}"
    r"(pass|aprobado|approved|concerns|block|requiere cambios|requires changes|"
    r"changes required|falta evidencia|missing evidence)",
    re.IGNORECASE,
)
_VERDICT_MAP = {
    "pass": "pass",
    "aprobado": "pass",
    "approved": "pass",
    "concerns": "concerns",
}


def parse_verdict(answer: str) -> str:
    """Last verdict line in the answer; ``info`` when there is none."""
    found = _VERDICT.findall(answer)
    if not found:
        return "info"
    return _VERDICT_MAP.get(found[-1].lower(), "block")


def parse_changes(answer: str) -> list[str]:
    """The ``CHANGE: <path>:<line> - <fix>`` lines of an answer, in order."""
    return _CHANGE.findall(answer)


def cross_examination(rounds: list[tuple[int, str, str]]) -> str:
    """The cross-examination block for ``(number, agent, file)`` of each round to refute."""
    lines = "\n".join(f"- round {n:03d} ({agent}): {path}" for n, agent, path in rounds)
    return CROSS_EXAMINATION.format(rounds=lines)
