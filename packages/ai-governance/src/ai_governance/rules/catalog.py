"""Bundled engineering-rules catalog (``catalog/manifest.json`` + Markdown files)."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path

ALWAYS_ON_GLOB = "**/*"


@dataclass(frozen=True)
class RuleDefinition:
    id: str
    category: str
    relative_path: str
    description: str
    globs: tuple[str, ...]
    stacks: tuple[str, ...]
    content: str
    sha256: str

    @property
    def always_on(self) -> bool:
        """True when the rule applies to every file (no path scoping)."""
        return ALWAYS_ON_GLOB in self.globs

    def applies_to(self, detected_stacks: set[str]) -> bool:
        """Rules without stacks are general; stack rules need a detected stack."""
        return not self.stacks or bool(detected_stacks & set(self.stacks))


def default_catalog_root() -> Path:
    return Path(str(files("ai_governance").joinpath("catalog")))


class RuleCatalog:
    """Loads and indexes engineering rules from the bundled catalog."""

    def __init__(self, catalog_root: Path | None = None) -> None:
        self.root = Path(catalog_root) if catalog_root else default_catalog_root()
        self._rules: dict[str, RuleDefinition] = {}
        manifest_path = self.root / "manifest.json"
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        for item in data.get("rules", []):
            content = (self.root / item["file"]).read_text(encoding="utf-8")
            rule = RuleDefinition(
                id=item["id"],
                category=item.get("category", "1-core"),
                relative_path=item["file"],
                description=item.get("description", ""),
                globs=tuple(item.get("triggers", {}).get("globs", [ALWAYS_ON_GLOB])),
                stacks=tuple(item.get("stacks", [])),
                content=content,
                sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
            )
            self._rules[rule.id] = rule

    @property
    def rules(self) -> list[RuleDefinition]:
        return list(self._rules.values())

    def get(self, rule_id: str) -> RuleDefinition | None:
        return self._rules.get(rule_id)

    def select(
        self,
        detected_stacks: set[str],
        *,
        extra: tuple[str, ...] = (),
        excluded: tuple[str, ...] = (),
    ) -> list[RuleDefinition]:
        """Rules a project needs: general + detected stacks + extra, minus excluded."""
        chosen = [
            rule
            for rule in self.rules
            if (rule.applies_to(detected_stacks) or rule.id in extra) and rule.id not in excluded
        ]
        return sorted(chosen, key=lambda rule: rule.id)
