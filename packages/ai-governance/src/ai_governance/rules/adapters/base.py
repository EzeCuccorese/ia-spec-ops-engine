from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from ..core.catalog import RuleDefinition
from ..core.injector import BlockInjector


class BaseAgentAdapter(ABC):
    """Base adapter for injecting/removing rules for a specific AI agent."""

    @property
    @abstractmethod
    def agent_id(self) -> str: ...

    @property
    @abstractmethod
    def display_name(self) -> str: ...

    @abstractmethod
    def get_target_file(self, root: Path, is_global: bool) -> Path: ...

    def render_block(self, rules: list[RuleDefinition], storage_path: Path) -> str:
        lines = [
            "## Engineering Standards Index (On-Demand Loading)",
            "",
            "> **Instructions:** Read the specific rule file ONLY when your task/file matches its trigger.",
            "",
            "| Rule | File | Trigger / Globs |",
            "|---|---|---|",
        ]
        for r in rules:
            rule_file = storage_path / r.relative_path
            globs_str = ", ".join(r.globs[:3])
            lines.append(f"| **{r.id}** | `[{r.relative_path}]({rule_file})` | `{globs_str}` |")
        return "\n".join(lines)

    def install(
        self, rules: list[RuleDefinition], storage_path: Path, root: Path, is_global: bool
    ) -> Path:
        target_file = self.get_target_file(root, is_global)
        target_file.parent.mkdir(parents=True, exist_ok=True)
        content = target_file.read_text(encoding="utf-8") if target_file.exists() else ""
        block = self.render_block(rules, storage_path)
        new_content = BlockInjector.inject(content, block)
        target_file.write_text(new_content, encoding="utf-8")
        return target_file

    def uninstall(self, root: Path, is_global: bool) -> Path | None:
        target_file = self.get_target_file(root, is_global)
        if not target_file.exists():
            return None
        content = target_file.read_text(encoding="utf-8")
        new_content = BlockInjector.remove(content)
        if not new_content.strip():
            target_file.unlink()
            return target_file
        else:
            target_file.write_text(new_content, encoding="utf-8")
            return target_file
