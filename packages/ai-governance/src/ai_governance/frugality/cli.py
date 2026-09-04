"""
cli.py — Entrypoint for `frugal` hooks.
Invoked via Claude Code hooks PreToolUse and PostToolUse for Bash.
Fail-open: never breaks agent execution.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from .output_trimmer import OutputTrimmer
from .pre_check import PreCheck
from .test_trimmer import TestTrimmer

DEFAULT_CONFIG = {
    "umbral_chars": 12000,
    "min_lineas_listado": 120,
    "prefijo_homogeneo_pct": 0.7,
    "head_lineas": 30,
    "tail_lineas": 20,
    "test_umbral_chars": 2000,
    "test_head_lineas": 3,
    "test_tail_lineas": 15,
    "test_contexto_antes": 3,
    "test_contexto_despues": 30,
}


def get_runtime_dir() -> Path:
    base = os.environ.get("CLAUDE_USAGE_DIR") or str(
        Path.home() / ".claude" / "usage-monitor"
    )
    p = Path(base)
    p.mkdir(parents=True, exist_ok=True)
    return p


def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    cfg_file = get_runtime_dir() / "frugal.json"
    if cfg_file.exists():
        try:
            cfg.update(json.loads(cfg_file.read_text(encoding="utf-8")))
        except Exception:
            pass
    return cfg


def run_pre_bash(cfg: dict) -> None:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return

    command = (payload.get("tool_input") or {}).get("command", "")
    session_id = payload.get("session_id")
    advice = PreCheck.check_command(command, session_id=session_id, runtime_dir=get_runtime_dir())
    if advice:
        print(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "allow",
                        "additionalContext": advice,
                    }
                }
            )
        )


def run_post_bash(cfg: dict) -> None:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return

    command = (payload.get("tool_input") or {}).get("command", "")
    if "#nofrugal" in command or os.environ.get("FRUGAL") == "0":
        return

    resp = payload.get("tool_response")
    if isinstance(resp, dict):
        stdout = resp.get("stdout") or ""
        interrupted = bool(resp.get("interrupted"))
        persisted = resp.get("persistedOutputPath")
    else:
        stdout = payload.get("tool_output") or ""
        interrupted = False
        persisted = None

    if interrupted or not stdout:
        return

    is_test = TestTrimmer.is_test_command(command)
    threshold = cfg["test_umbral_chars"] if is_test else cfg["umbral_chars"]

    if len(stdout) <= threshold:
        return
    if not is_test and OutputTrimmer.should_skip(command):
        return

    ref = f"full output: {persisted}" if persisted else ""

    if is_test:
        new_output = TestTrimmer.trim(stdout, cfg, ref)
    else:
        new_output = OutputTrimmer.trim_listing(stdout, cfg, ref)

    if new_output and len(new_output) < len(stdout):
        print(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "PostToolUse",
                        "updatedToolOutput": new_output,
                    }
                }
            )
        )


def main() -> int:
    args = sys.argv[1:]
    cfg = load_config()
    try:
        if "--post-bash" in args:
            run_post_bash(cfg)
        elif "--pre-bash" in args:
            run_pre_bash(cfg)
        else:
            print("SpecOps Frugal Context Optimizer")
            print("Usage: frugal --post-bash | frugal --pre-bash")
    except Exception:
        pass  # Never disrupt active agent execution
    return 0


if __name__ == "__main__":
    sys.exit(main())
