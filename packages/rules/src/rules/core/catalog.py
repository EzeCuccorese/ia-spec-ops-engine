from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RuleDefinition:
    id: str
    category: str
    relative_path: str
    description: str
    globs: tuple[str, ...]
    content: str
    sha256: str


class RuleCatalog:
    """Loads and indexes engineering rules from the bundled catalog."""

    def __init__(self, catalog_root: Path | None = None) -> None:
        self.root = catalog_root or (Path(__file__).resolve().parent.parent.parent.parent / "catalog")
        self._rules: dict[str, RuleDefinition] = {}
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
