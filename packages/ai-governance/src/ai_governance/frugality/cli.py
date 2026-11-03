"""Frugality hooks: pre-shell advice and post-shell output condensing (via ``ws``).

Invoked through ``ai-governance hook <agent> <event>``. Fail-open: never breaks
agent execution.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from .._config_core import ConfigError
from ..paths import state_dir
from ..settings import SETTINGS, effective
from .pre_check import PreCheck, replacement_patterns

# Condense outputs above threshold_chars down to budget_chars (~600 tokens).
DEFAULT_CONFIG = {
    s.key.split(".", 1)[1]: s.default for s in SETTINGS if s.key.startswith("frugality.")
}


def get_runtime_dir() -> Path:
    p = state_dir() / "frugal"
    p.mkdir(parents=True, exist_ok=True)
    return p


def load_config() -> dict:
    """Condense thresholds (``[frugality]``); fail-open: a broken file keeps the defaults."""
    try:
        values = effective()
    except ConfigError:
        return dict(DEFAULT_CONFIG)
    return {name: values[f"frugality.{name}"].value for name in DEFAULT_CONFIG}


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


def _condense_timeout() -> float:
    try:
        return float(effective()["frugality.condense_timeout_seconds"].value)  # type: ignore[arg-type]
    except ConfigError:
        return 30.0


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
            timeout=_condense_timeout(),
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


def post_bash_output(payload: dict, cfg: dict) -> dict | None:
    """PostToolUse(Bash) fields that replace large output with the ws summary."""
    replaced = condensed_output(payload, cfg)
    return None if replaced is None else {"updatedToolOutput": replaced[1]}


def run_post_bash(cfg: dict) -> None:
    """Claude Code PostToolUse(Bash): replace large output with the ws summary."""
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, UnicodeDecodeError, OSError):
        return
    fields = post_bash_output(payload, cfg)
    if fields:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", **fields}}))
