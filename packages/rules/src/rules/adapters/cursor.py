from __future__ import annotations

from pathlib import Path
import shutil
from ..core.catalog import RuleDefinition
from .base import BaseAgentAdapter


class CursorAdapter(BaseAgentAdapter):
    @property
    def agent_id(self) -> str:
        return "cursor"

    @property
    def display_name(self) -> str:
        return "Cursor IDE (.cursorrules & .cursor/rules/*.mdc)"

    def get_target_file(self, root: Path, is_global: bool) -> Path:
        if is_global:
            return Path.home() / ".cursorrules"
        return root / ".cursorrules"

    def install(self, rules: list[RuleDefinition], storage_path: Path, root: Path, is_global: bool) -> Path:
        target = super().install(rules, storage_path, root, is_global)
        if not is_global:
            rules_dir = root / ".cursor" / "rules"
            rules_dir.mkdir(parents=True, exist_ok=True)
            for r in rules:
                mdc_file = rules_dir / f"{r.id}.mdc"
                globs_formatted = "\n".join([f"  - '{g}'" for g in r.globs])
                mdc_content = (
                    f"---\n"
                    f"description: {r.description}\n"
                    f"globs:\n"
                    f"{globs_formatted}\n"
                    f"alwaysApply: false\n"
                    f"---\n\n"
                    f"{r.content}\n"
                )
                mdc_file.write_text(mdc_content, encoding="utf-8")
        return target

    def uninstall(self, root: Path, is_global: bool) -> Path | None:
        target = super().uninstall(root, is_global)
        if not is_global:
            rules_dir = root / ".cursor" / "rules"
            if rules_dir.exists():
                shutil.rmtree(rules_dir)
        return target
