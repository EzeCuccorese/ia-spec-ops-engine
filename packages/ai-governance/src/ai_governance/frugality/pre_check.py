"""
pre_check.py — Proactive PreToolUse heuristic checker.
Warns agents when executing blatantly wasteful terminal commands without blocking execution.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

LOCKFILES = (
    "package-lock.json",
    "yarn.lock",
    "Cargo.lock",
    "Gemfile.lock",
    "poetry.lock",
    "composer.lock",
    "uv.lock",
)

PATTERNS = (
    (
        "lockfile",
        lambda c: any(
            re.search(rf"\b(cat|less|more|bat)\b.*\b{re.escape(lf)}\b", c)
            for lf in LOCKFILES
        ),
        "This lockfile may contain thousands of lines. Frugal alternative: "
        "use `rg '\"package\":' <file>` or package-specific dependency inspection tools.",
    ),
    (
        "curl_sin_jq",
        lambda c: bool(re.search(r"\bcurl\b", c) and "jq" not in c and re.search(r"https?://", c)),
        "This API call may return a large payload. Append `| jq -r '...'` "
        "with the minimal projection needed.",
    ),
    (
        "git_log_sin_limite",
        lambda c: bool(
            re.search(r"\bgit\s+log\b", c)
            and not re.search(r"(-n\s*\d+|--oneline|-\d+\b)", c)
        ),
        "`git log` without limits may print the entire history. Use `git log --oneline -n 10`.",
    ),
    (
        "find_root",
        lambda c: bool(re.search(r"\bfind\s+/(?:\s|$)", c) and "-maxdepth" not in c),
        "`find /` without `-maxdepth` may traverse the entire filesystem. Add `-maxdepth N`.",
    ),
    (
        "logs_sin_tail",
        lambda c: bool(
            re.search(r"\b(docker|kubectl)\s+logs\b", c) and "--tail" not in c and "-n" not in c
        ),
        "Log streams can be huge. Append `--tail 100`.",
    ),
    (
        "build_sin_filtro",
        lambda c: bool(
            re.search(r"\b(npm|yarn|pnpm)\s+(run\s+)?build\b", c)
            and "tail" not in c
            and "--silent" not in c
        ),
        "Consider constraining build output: append `2>&1 | tail -40` or the runner's silent flag.",
    ),
)


class PreCheck:
    @staticmethod
    def check_command(command: str, session_id: str | None = None, runtime_dir: Path | None = None) -> str | None:
        if not command or "#nofrugal" in command or os.environ.get("FRUGAL") == "0":
            return None

        warned: set[str] = set()
        warnings_file = None
        if runtime_dir and session_id:
            warnings_file = runtime_dir / "sessions" / f"{session_id}.json"
            if warnings_file.exists():
                try:
                    warned = set(json.loads(warnings_file.read_text(encoding="utf-8")))
                except Exception:
                    warned = set()

        for pid, matcher, advice in PATTERNS:
            if pid in warned:
                continue
            if matcher(command):
                if warnings_file:
                    try:
                        warnings_file.parent.mkdir(parents=True, exist_ok=True)
                        warned.add(pid)
                        warnings_file.write_text(json.dumps(sorted(warned)), encoding="utf-8")
                    except Exception:
                        pass
                return advice
        return None
