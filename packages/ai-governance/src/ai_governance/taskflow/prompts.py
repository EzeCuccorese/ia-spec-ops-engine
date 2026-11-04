"""Prompt text and verdict parsing shared by dispatched rounds and judges.

The engine never launches an agent: a reader round is a spec file an Orca worker reads and
an answer file the engine parses afterwards. This module holds the two sentences every
reader spec carries and the parser of the verdict line a validator or judge must end with.
"""

from __future__ import annotations

import re

READ_ONLY_LIMIT = (
    "Do not modify files, commit, push or run commands that change the repository or the "
    "environment. Do not delegate to subagents. Mark each claim as seen/assumed/unknown.\n\n"
)
VERDICT_INSTRUCTION = (
    "\n\nEnd your answer with one line exactly like `VERDICT: pass`, `VERDICT: concerns` or "
    "`VERDICT: block` (block = changes required or evidence missing)."
)
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
