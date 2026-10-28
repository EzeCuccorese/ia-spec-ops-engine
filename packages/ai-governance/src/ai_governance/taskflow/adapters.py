"""Headless runners for each agent CLI.

Every agent runs with full permissions (local repositories, by the user's decision); the
limit for reader roles goes in the prompt, and the engine detects any change they make by
comparing the tree fingerprint before and after. Flags were checked against each CLI's
``--help``: Antigravity has no ``--mode agent`` (only ``plan|accept-edits|auto``), Codex
``-o`` keeps only the final message (stdout/stderr are saved separately), and Claude's
``-p`` is print mode, so full permissions need their own flag.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .models import JsonDict

READ_ONLY_LIMIT = (
    "Do not modify files, commit, push or run commands that change the repository or the "
    "environment. Do not delegate to subagents. Mark each claim as seen/assumed/unknown.\n\n"
)
VERDICT_INSTRUCTION = (
    "\n\nEnd your answer with one line exactly like `VERDICT: pass`, `VERDICT: concerns` or "
    "`VERDICT: block` (block = changes required or evidence missing)."
)
AGENTS: tuple[str, ...] = ("antigravity", "codex", "claude")
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


@dataclass(frozen=True)
class RunResult:
    command: list[str]
    exit_code: int
    answer: str
    raw_log: str
    timed_out: bool = False


def build_command(
    agent: str, model: str, prompt: str, *, cwd: Path, writes: bool, answer_file: Path
) -> list[str]:
    if agent == "antigravity":
        command = ["agy"]
        if model:
            command += ["--model", model]
        mode = "accept-edits" if writes else "plan"
        return [*command, "--mode", mode, "--dangerously-skip-permissions", f"--print={prompt}"]
    if agent == "codex":
        command = [
            "codex",
            "exec",
            "-C",
            str(cwd),
            "-s",
            "danger-full-access" if writes else "read-only",
            "-o",
            str(answer_file),
        ]
        if model:
            command += ["-m", model]
        return [*command, prompt]
    if agent == "claude":
        command = ["claude", "-p", "--dangerously-skip-permissions"]
        if model:
            command += ["--model", model]
        return [*command, prompt]
    raise ValueError(f"Unknown agent '{agent}': use one of {', '.join(AGENTS)} (or 'human')")


def run_agent(
    role_config: JsonDict, prompt: str, *, cwd: Path, writes: bool, workdir: Path, timeout: int
) -> RunResult:
    agent = str(role_config.get("agent", ""))
    answer_file = workdir / "answer.txt"
    answer_file.unlink(missing_ok=True)
    command = build_command(
        agent,
        str(role_config.get("model", "")),
        prompt,
        cwd=cwd,
        writes=writes,
        answer_file=answer_file,
    )
    try:
        proc = subprocess.run(
            command,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        partial = (
            (exc.stdout or b"").decode(errors="replace")
            if isinstance(exc.stdout, bytes)
            else (exc.stdout or "")
        )
        return RunResult(command, -1, partial, partial, timed_out=True)
    except FileNotFoundError as exc:
        raise ValueError(f"'{command[0]}' is not installed or not on PATH") from exc
    raw = proc.stdout + ("\n--- stderr ---\n" + proc.stderr if proc.stderr.strip() else "")
    answer = answer_file.read_text(encoding="utf-8") if answer_file.exists() else proc.stdout
    return RunResult(command, proc.returncode, answer, raw)


def parse_verdict(answer: str) -> str:
    """Last verdict line in the answer; ``info`` when there is none."""
    found = _VERDICT.findall(answer)
    if not found:
        return "info"
    return _VERDICT_MAP.get(found[-1].lower(), "block")
