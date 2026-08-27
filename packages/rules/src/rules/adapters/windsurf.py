from __future__ import annotations

from pathlib import Path
from .base import BaseAgentAdapter


class WindsurfAdapter(BaseAgentAdapter):
    @property
    def agent_id(self) -> str:
        return "windsurf"

    @property
    def display_name(self) -> str:
        return "Codeium Windsurf (.windsurfrules)"

    def get_target_file(self, root: Path, is_global: bool) -> Path:
        if is_global:
            return Path.home() / ".codeium" / "windsurf" / "memories" / "global_rules.md"
        return root / ".windsurfrules"
