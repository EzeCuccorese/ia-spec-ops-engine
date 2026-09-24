"""Frugality hooks: pre-shell advice and post-shell output condensing (via ``ws``).

Invoked through ``ai-governance hook <agent> <event>``. Fail-open: never breaks
agent execution.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from ..paths import config_dir, state_dir
from .pre_check import PreCheck, replacement_patterns

# Condense outputs above threshold_chars down to budget_chars (~600 tokens).
DEFAULT_CONFIG = {"threshold_chars": 4000, "budget_chars": 2500}


def get_runtime_dir() -> Path:
    p = state_dir() / "frugal"
    p.mkdir(parents=True, exist_ok=True)
    return p


def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    cfg_file = config_dir() / "frugal.json"
    if cfg_file.exists():
        with contextlib.suppress(json.JSONDecodeError, UnicodeDecodeError, OSError):
            cfg.update(json.loads(cfg_file.read_text(encoding="utf-8")))
    return cfg


def run_pre_bash(cfg: dict) -> None:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, UnicodeDecodeError, OSError):
        return

    command = (payload.get("tool_input") or {}).get("command", "")
    session_id = payload.get("session_id")

    advice = PreCheck.check_command(
        command,
        session_id=session_id,
        runtime_dir=get_runtime_dir(),
        extra_patterns=replacement_patterns(),
    )
    if advice:
        print(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "additionalContext": advice,
                    }
                }
            )
        )


# Output the agent asked for explicitly (diffs, file dumps) is never condensed.
SKIP_CONDENSE = re.compile(
    r"^\s*(git\s+(diff|show|log\s+-p|grep)|cat|head|tail|sed\s+-n|jq|grep|rg|nl|awk|ws\s+log)\b"
)


def condense_with_ws(text: str, command: str, budget: int) -> dict | None:
    """Condenses via the ``ws condense --json`` contract; None when ws is unavailable."""
    ws = shutil.which("ws")
    if ws is None:
        return None
    try:
        proc = subprocess.run(
            [ws, "condense", "--json", "--command", command, "--budget", str(budget)],
            input=text,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        result = json.loads(proc.stdout)
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    if proc.returncode != 0 or result.get("schema_version") != 1:
        return None
    return result


def condensed_output(payload: dict, cfg: dict) -> tuple[str, dict | str] | None:
    """Returns (condensed text, replacement tool response) or None to keep the original."""
    command = (payload.get("tool_input") or {}).get("command", "")
    if "#nofrugal" in command or os.environ.get("FRUGAL") == "0" or SKIP_CONDENSE.match(command):
        return None
    resp = payload.get("tool_response")
    if isinstance(resp, dict):
        stdout, stderr = resp.get("stdout") or "", resp.get("stderr") or ""
    else:
        stdout, stderr = payload.get("tool_output") or (resp if isinstance(resp, str) else ""), ""
    text = stdout + (f"\n{stderr}" if stderr else "")
    if len(text) <= cfg["threshold_chars"]:
        return None
    result = condense_with_ws(text, command, cfg["budget_chars"])
    if not result or not result.get("truncated") or len(result["text"]) >= len(text):
        return None
    note = f"\n[condensed by ws: ws log {result['log_id']} --grep RE | --lines A-B]"
    condensed = result["text"] + (note if result.get("log_id") else "")
    if isinstance(resp, dict):
        return condensed, {**resp, "stdout": condensed, "stderr": ""}
    return condensed, condensed


def run_post_bash(cfg: dict) -> None:
    """Claude Code PostToolUse(Bash): replace large output with the ws summary."""
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, UnicodeDecodeError, OSError):
        return
    replaced = condensed_output(payload, cfg)
    if replaced is None:
        return
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PostToolUse",
                    "updatedToolOutput": replaced[1],
                }
            }
        )
    )
