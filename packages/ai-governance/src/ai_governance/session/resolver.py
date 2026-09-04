"""
resolver.py — Resolves the active Jira ticket or task ID from the current Git environment.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

# Match standard Jira keys like ONB-1234, PROJ-56, etc.
JIRA_RE = re.compile(r"([A-Z]{2,10}-\d+)", re.IGNORECASE)


class TaskResolver:
    @staticmethod
    def resolve_from_git(repo_dir: Path | None = None) -> str | None:
        cmd = ["git", "branch", "--show-current"]
        try:
            res = subprocess.run(
                cmd,
                cwd=str(repo_dir) if repo_dir else None,
                capture_output=True,
                text=True,
                timeout=2,
            )
            if res.returncode == 0 and res.stdout.strip():
                branch = res.stdout.strip()
                match = JIRA_RE.search(branch)
                if match:
                    return match.group(1).upper()
        except Exception:
            pass

        return None
