"""
workspace_engine.common.process — Process inspection helpers for Workspace Engine.
"""

from __future__ import annotations

import contextlib
import json
import subprocess
from pathlib import Path


def _parse_json_pid(
    raw_text: str, default_name: str
) -> tuple[int | None, str | None, str, str | None]:
    with contextlib.suppress(json.JSONDecodeError, ValueError, TypeError):
        meta = json.loads(raw_text)
        raw_pid = meta.get("pid", 0)
        if isinstance(raw_pid, bool):
            return None, None, default_name, None
        pid = int(raw_pid)
        cmd = meta.get("cmd") or meta.get("cmdline") or meta.get("command")
        name = meta.get("repo") or meta.get("name") or default_name
        path = meta.get("path")
        return (pid if pid > 0 else None), cmd, str(name), (str(path) if path else None)
    return None, None, default_name, None


def _parse_text_pid(
    raw_text: str, default_name: str
) -> tuple[int | None, str | None, str, str | None]:
    lines = raw_text.splitlines()
    if not lines:
        return None, None, default_name, None
    with contextlib.suppress(ValueError):
        pid = int(lines[0].strip())
        cmd = lines[1].strip() if len(lines) > 1 and lines[1].strip() else None
        return (pid if pid > 0 else None), cmd, default_name, None
    return None, None, default_name, None


def parse_pid_file(
    pid_file: Path, default_name: str | None = None
) -> tuple[int | None, str | None, str, str | None]:
    """Parses a JSON or plain-text .pid file into (pid, cmd, name, path)."""
    fallback = default_name if default_name is not None else pid_file.stem
    try:
        raw_text = pid_file.read_text(encoding="utf-8").strip()
    except OSError:
        return None, None, fallback, None
    if raw_text.startswith("{"):
        return _parse_json_pid(raw_text, fallback)
    return _parse_text_pid(raw_text, fallback)


def get_process_cmdline(pid: int) -> str:
    """Gets the command line of a process given its PID by inspecting /proc or ps."""
    if pid <= 1:
        return ""
    proc_cmdline = Path(f"/proc/{pid}/cmdline")
    if proc_cmdline.exists():
        with contextlib.suppress(OSError, UnicodeDecodeError):
            return proc_cmdline.read_text(encoding="utf-8").replace("\x00", " ").strip()

    try:
        res = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="],
            capture_output=True,
            text=True,
            timeout=2,
        )
        if res.returncode == 0 and res.stdout.strip():
            return res.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass

    return ""
