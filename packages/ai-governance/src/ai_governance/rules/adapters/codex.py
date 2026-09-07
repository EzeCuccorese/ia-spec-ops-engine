from __future__ import annotations

from pathlib import Path

from .base import BaseAgentAdapter


class CodexAdapter(BaseAgentAdapter):
    @property
    def agent_id(self) -> str:
        return "agents"

    @property
    def display_name(self) -> str:
        return "Universal AGENTS.md Standard (AGENTS.md)"

    def get_target_file(self, root: Path, is_global: bool) -> Path:
        if is_global:
            return Path.home() / ".config" / "agents" / "AGENTS.md"
        return root / "AGENTS.md"


AgentsAdapter = CodexAdapter
