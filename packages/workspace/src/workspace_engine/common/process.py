"""
workspace_engine.common.process — Process inspection helpers for Workspace Engine.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


def get_process_cmdline(pid: int) -> str:
    """Gets the command line of a process given its PID by inspecting /proc or ps."""
    if pid <= 1:
        return ""
    proc_cmdline = Path(f"/proc/{pid}/cmdline")
    if proc_cmdline.exists():
        try:
            return proc_cmdline.read_text(encoding="utf-8").replace("\x00", " ").strip()
        except OSError:
            pass

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
