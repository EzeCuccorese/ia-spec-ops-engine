from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

TRIGGERS: frozenset[str] = frozenset(
    {
        "before-shell-command",
        "after-shell-command",
        "on-turn-end",
        "on-worktree-create",
        "on-demand",
    }
)
FAIL_MODES: frozenset[str] = frozenset({"open", "closed"})
IO_KINDS: frozenset[str] = frozenset({"json", "text", "none"})


@dataclass(frozen=True)
class RuleDefinition:
    id: str
    category: str
    relative_path: str
    description: str
    globs: tuple[str, ...]
    content: str
    sha256: str


@dataclass(frozen=True)
class ToolDefinition:
    id: str
    package: str
    command: str
    purpose: str
    trigger: str
    io_stdin: str
    io_stdout: str
    replaces: tuple[str, ...]
    fail_mode: str


class RuleCatalog:
    """Loads and indexes engineering rules from the bundled catalog."""

    def __init__(self, catalog_root: Path | None = None) -> None:
        if catalog_root:
            self.root = Path(catalog_root)
        else:
            found = None
            try:
                import importlib.resources as pkg_resources

                res = Path(str(pkg_resources.files("ai_governance").joinpath("catalog")))
                if res.is_dir() and (res / "manifest.json").exists():
                    found = res
            except (ImportError, ModuleNotFoundError, OSError):
                found = None

            if not found:
                for p in Path(__file__).resolve().parents:
                    cand = p / "catalog"
                    if cand.is_dir() and (cand / "manifest.json").exists():
                        found = cand
                        break
            self.root = found or (Path(__file__).resolve().parents[4] / "catalog")
        self._rules: dict[str, RuleDefinition] = {}
        self._tools: dict[str, ToolDefinition] = {}
        self._load()

    def _load(self) -> None:
        manifest_path = self.root / "manifest.json"
        if not manifest_path.exists():
            return

        with open(manifest_path, encoding="utf-8") as f:
            data = json.load(f)

        for item in data.get("rules", []):
            rule_file = self.root / item["file"]
            if rule_file.exists():
                content = rule_file.read_text(encoding="utf-8")
                digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
                rule = RuleDefinition(
                    id=item["id"],
                    category=item.get("category", "1-core"),
                    relative_path=item["file"],
                    description=item.get("description", ""),
                    globs=tuple(item.get("triggers", {}).get("globs", ["**/*"])),
                    content=content,
                    sha256=digest,
                )
                self._rules[rule.id] = rule

        for item in data.get("tools", []):
            tool_id = item["id"]
            trigger = item.get("trigger", "on-demand")
            if trigger not in TRIGGERS:
                raise ValueError(f"Tool '{tool_id}' has invalid trigger: {trigger!r}")
            fail_mode = item.get("fail_mode", "open")
            if fail_mode not in FAIL_MODES:
                raise ValueError(f"Tool '{tool_id}' has invalid fail_mode: {fail_mode!r}")
            io = item.get("io", {})
            io_stdin = io.get("stdin", "text")
            io_stdout = io.get("stdout", "text")
            if io_stdin not in IO_KINDS:
                raise ValueError(f"Tool '{tool_id}' has invalid io.stdin: {io_stdin!r}")
            if io_stdout not in IO_KINDS:
                raise ValueError(f"Tool '{tool_id}' has invalid io.stdout: {io_stdout!r}")
            tool = ToolDefinition(
                id=tool_id,
                package=item["package"],
                command=item["command"],
                purpose=item.get("purpose", ""),
                trigger=trigger,
                io_stdin=io_stdin,
                io_stdout=io_stdout,
                replaces=tuple(item.get("replaces", ())),
                fail_mode=fail_mode,
            )
            self._tools[tool.id] = tool

    @property
    def rules(self) -> list[RuleDefinition]:
        return list(self._rules.values())

    def get(self, rule_id: str) -> RuleDefinition | None:
        return self._rules.get(rule_id)

    def by_category(self) -> dict[str, list[RuleDefinition]]:
        grouped: dict[str, list[RuleDefinition]] = {}
        for rule in self.rules:
            grouped.setdefault(rule.category, []).append(rule)
        return grouped

    @property
    def tools(self) -> list[ToolDefinition]:
        return list(self._tools.values())

    def get_tool(self, tool_id: str) -> ToolDefinition | None:
        return self._tools.get(tool_id)

    def tools_by_trigger(self) -> dict[str, list[ToolDefinition]]:
        grouped: dict[str, list[ToolDefinition]] = {}
        for tool in self.tools:
            grouped.setdefault(tool.trigger, []).append(tool)
        return grouped

    def automatic_tools(self) -> list[ToolDefinition]:
        return [tool for tool in self.tools if tool.trigger != "on-demand"]

    def on_demand_tools(self) -> list[ToolDefinition]:
        return [tool for tool in self.tools if tool.trigger == "on-demand"]
