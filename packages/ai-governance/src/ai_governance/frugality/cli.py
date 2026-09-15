"""
cli.py — Entrypoint for `frugal` hooks.
Invoked via Claude Code hooks PreToolUse and PostToolUse for Bash.
Fail-open: never breaks agent execution.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from .output_trimmer import OutputTrimmer
from .pre_check import PreCheck
from .test_trimmer import TestTrimmer

try:
    import fcntl
except ImportError:
    fcntl = None  # type: ignore

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
    base = (
        os.environ.get("SPECOPS_USAGE_DIR")
        or os.environ.get("CLAUDE_USAGE_DIR")
        or str(Path.home() / ".specops" / "usage-monitor")
    )
    p = Path(base)
    p.mkdir(parents=True, exist_ok=True)
    return p


def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    cfg_file = get_runtime_dir() / "frugal.json"
    if cfg_file.exists():
        with contextlib.suppress(Exception):
            cfg.update(json.loads(cfg_file.read_text(encoding="utf-8")))
    return cfg


def _atomic_output_copy(runtime: Path, identifier: str, stdout: str) -> Path | None:
    output_dir = runtime / "outputs"
    safe_name = hashlib.sha256(identifier.encode("utf-8")).hexdigest()[:24] + ".txt"
    temporary: Path | None = None
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        destination = output_dir / safe_name
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=output_dir, delete=False
        ) as handle:
            handle.write(stdout)
            handle.flush()
            os.fsync(handle.fileno())
            temporary = Path(handle.name)
        temporary.replace(destination)
        return destination
    except OSError:
        return None
    finally:
        if temporary and temporary.exists():
            temporary.unlink(missing_ok=True)


def _audit_trim(runtime: Path, command: str, original: int, trimmed: int) -> None:
    record = {
        "timestamp": datetime.now(UTC).isoformat(),
        "command_sha256": hashlib.sha256(command.encode("utf-8")).hexdigest(),
        "original_chars": original,
        "trimmed_chars": trimmed,
    }
    try:
        runtime.mkdir(parents=True, exist_ok=True)
        with open(runtime / "trim-audit.jsonl", "a", encoding="utf-8") as handle:
            if fcntl:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                handle.write(json.dumps(record, sort_keys=True) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            finally:
                if fcntl:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass


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
    is_dict = isinstance(resp, dict)
    if is_dict:
        stdout = resp.get("stdout") or ""
        persisted = resp.get("persistedOutputPath")
    else:
        stdout = payload.get("tool_output") or (resp if isinstance(resp, str) else "") or ""
        persisted = None

    if not stdout:
        return

    is_test = TestTrimmer.is_test_command(command)
    threshold = cfg["test_umbral_chars"] if is_test else cfg["umbral_chars"]

    if len(stdout) <= threshold:
        return
    if not is_test and OutputTrimmer.should_skip(command):
        return

    if is_test:
        candidate = TestTrimmer.trim(stdout, cfg)
    else:
        candidate = OutputTrimmer.trim_listing(stdout, cfg)

    if candidate and len(candidate) < len(stdout):
        runtime = get_runtime_dir()
        generated = None
        if not persisted:
            identifier = str(payload.get("tool_use_id") or payload.get("session_id") or command)
            generated = _atomic_output_copy(runtime, identifier, stdout)
            persisted = str(generated) if generated else None
        ref = f"full output: {persisted}" if persisted else "full output unavailable"
        if is_test:
            new_output = TestTrimmer.trim(stdout, cfg, ref)
        else:
            new_output = OutputTrimmer.trim_listing(stdout, cfg, ref)
        if not new_output or len(new_output) >= len(stdout):
            return
        _audit_trim(runtime, command, len(stdout), len(new_output))
        if is_dict:
            updated_val = dict(resp)
            updated_val["stdout"] = new_output
            if persisted:
                updated_val["persistedOutputPath"] = persisted
        else:
            updated_val = new_output

        print(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "PostToolUse",
                        "updatedToolOutput": updated_val,
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
