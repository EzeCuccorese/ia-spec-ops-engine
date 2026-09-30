"""Bundled engineering-rules catalog (``catalog/manifest.json`` + Markdown files)."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path

ALWAYS_ON_GLOB = "**/*"
SCHEMA_VERSION = 3


@dataclass(frozen=True)
class RuleDefinition:
    id: str
    category: str
    relative_path: str
    description: str
    globs: tuple[str, ...]
    stacks: tuple[str, ...]
    profile: str | None
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
        if data.get("schema_version") != SCHEMA_VERSION:
            raise ValueError(
                f"Unsupported catalog schema_version: {data.get('schema_version')} "
                f"(expected {SCHEMA_VERSION})."
            )
        self.profiles: dict[str, str] = dict(data.get("profiles", {}))
        for item in data.get("rules", []):
            profile = item.get("profile")
            if profile is not None and profile not in self.profiles:
                raise ValueError(f"Rule {item['id']!r} references unknown profile {profile!r}.")
            content = (self.root / item["file"]).read_text(encoding="utf-8")
            rule = RuleDefinition(
                id=item["id"],
                category=item.get("category", "1-core"),
                relative_path=item["file"],
                description=item.get("description", ""),
                globs=tuple(item.get("triggers", {}).get("globs", [ALWAYS_ON_GLOB])),
                stacks=tuple(item.get("stacks", [])),
                profile=profile,
                content=content,
                sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
            )
            self._rules[rule.id] = rule

    @property
    def rules(self) -> list[RuleDefinition]:
        return list(self._rules.values())

    def get(self, rule_id: str) -> RuleDefinition | None:
        return self._rules.get(rule_id)

    def check_profiles(self, names: tuple[str, ...]) -> None:
        unknown = sorted(set(names) - set(self.profiles))
        if unknown:
            raise ValueError(
                f"Unknown profile(s): {', '.join(unknown)}. "
                f"Available: {', '.join(sorted(self.profiles))}"
            )

    def select(
        self,
        detected_stacks: set[str],
        *,
        profiles: tuple[str, ...] = (),
        extra: tuple[str, ...] = (),
        excluded: tuple[str, ...] = (),
    ) -> list[RuleDefinition]:
        """Rules a project needs: general + detected stacks + enabled profiles + extra,
        minus excluded. A rule tied to a profile is only chosen when that profile is
        enabled (unless forced in via ``extra``)."""
        chosen = [
            rule
            for rule in self.rules
            if (
                (
                    (rule.profile is None or rule.profile in profiles)
                    and rule.applies_to(detected_stacks)
                )
                or rule.id in extra
            )
            and rule.id not in excluded
        ]
        return sorted(chosen, key=lambda rule: rule.id)
