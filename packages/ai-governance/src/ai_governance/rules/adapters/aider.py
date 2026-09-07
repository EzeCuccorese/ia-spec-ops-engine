from __future__ import annotations

from pathlib import Path

from .base import BaseAgentAdapter


class AiderAdapter(BaseAgentAdapter):
    @property
    def agent_id(self) -> str:
        return "aider"

    @property
    def display_name(self) -> str:
        return "Aider AI (CONVENTIONS.md)"

    def get_target_file(self, root: Path, is_global: bool) -> Path:
        if is_global:
            return Path.home() / ".config" / "aider" / "CONVENTIONS.md"
        return root / "CONVENTIONS.md"
