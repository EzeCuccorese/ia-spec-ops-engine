from __future__ import annotations

from pathlib import Path
from .base import BaseAgentAdapter


class ClaudeAdapter(BaseAgentAdapter):
    @property
    def agent_id(self) -> str:
        return "claude"

    @property
    def display_name(self) -> str:
        return "Anthropic Claude Code (CLAUDE.md)"

    def get_target_file(self, root: Path, is_global: bool) -> Path:
        if is_global:
            return Path.home() / ".claude" / "CLAUDE.md"
        return root / "CLAUDE.md"
