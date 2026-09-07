from __future__ import annotations

from pathlib import Path

from .base import BaseAgentAdapter


class CopilotAdapter(BaseAgentAdapter):
    @property
    def agent_id(self) -> str:
        return "copilot"

    @property
    def display_name(self) -> str:
        return "GitHub Copilot (.github/copilot-instructions.md)"

    def get_target_file(self, root: Path, is_global: bool) -> Path:
        if is_global:
            return Path.home() / ".config" / "github-copilot" / "copilot-instructions.md"
        return root / ".github" / "copilot-instructions.md"
