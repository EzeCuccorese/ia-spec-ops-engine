from __future__ import annotations

from pathlib import Path

from .base import BaseAgentAdapter


class GeminiAdapter(BaseAgentAdapter):
    @property
    def agent_id(self) -> str:
        return "gemini"

    @property
    def display_name(self) -> str:
        return "Google Gemini CLI (GEMINI.md)"

    def get_target_file(self, root: Path, is_global: bool) -> Path:
        if is_global:
            return Path.home() / ".gemini" / "GEMINI.md"
        return root / "GEMINI.md"
