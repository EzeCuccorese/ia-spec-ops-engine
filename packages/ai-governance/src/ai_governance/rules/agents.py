from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from .core.catalog import RuleDefinition, ToolDefinition
from .core.injector import BlockInjector


def filter_rules_by_tech(rules: list[RuleDefinition], tech: str | None) -> list[RuleDefinition]:
    """Filter rules by technology stack (e.g. python, java, all)."""
    if not tech or tech.lower() == "all":
        return rules
    techs = [t.strip().lower() for t in tech.split(",") if t.strip()]
    matched: list[RuleDefinition] = []
    for r in rules:
        if any(t in r.id.lower() or t in r.relative_path.lower() for t in techs):
            matched.append(r)
    return matched


class AgentsRulesAdapter:
    """Inject and manage engineering standards in the universal AGENTS.md standard."""

    agent_id: str = "agents"
    display_name: str = "Universal AGENTS.md Standard (AGENTS.md)"

    def get_target_file(self, root: Path, is_global: bool) -> Path:
        if is_global:
            return Path.home() / ".config" / "agents" / "AGENTS.md"
        return root / "AGENTS.md"

    def render_block(
        self,
        rules: list[RuleDefinition],
        storage_path: Path,
        tools: Sequence[ToolDefinition] = (),
    ) -> str:
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
            lines.append(f"| **{r.id}** | [{r.relative_path}]({rule_file}) | `{globs_str}` |")

        if tools:
            lines.extend(
                [
                    "",
                    "## Harness Tools (deterministic — prefer over manual work)",
                    "",
                    "> Announce usage with one line: `⚙ <tool-id> <args>`. "
                    "See rule `00-deterministic-first`.",
                    "",
                    "| Tool | Use it for | Command | Trigger |",
                    "|---|---|---|---|",
                ]
            )
            ordered = sorted(tools, key=lambda t: t.trigger != "on-demand")
            for t in ordered:
                lines.append(f"| **{t.id}** | {t.purpose} | `{t.command}` | {t.trigger} |")

        return "\n".join(lines)

    def install(
        self,
        rules: list[RuleDefinition],
        storage_path: Path,
        root: Path,
        is_global: bool,
        tech: str | None = None,
        tools: Sequence[ToolDefinition] = (),
    ) -> Path:
        if tech:
            rules = filter_rules_by_tech(rules, tech)
        target_file = self.get_target_file(root, is_global)
        target_file.parent.mkdir(parents=True, exist_ok=True)
        content = target_file.read_text(encoding="utf-8") if target_file.exists() else ""
        block = self.render_block(rules, storage_path, tools)
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


AGENTS_ADAPTER = AgentsRulesAdapter()
ALL_ADAPTERS = {"agents": AGENTS_ADAPTER}
