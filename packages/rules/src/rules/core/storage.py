from __future__ import annotations

import json
from pathlib import Path
from .catalog import RuleDefinition


class RuleStorage:
    """Manages storing rule markdown files and manifest in global (~) or local (.specops) directories."""

    def __init__(self, target_dir: Path) -> None:
        self.target_dir = target_dir

    @classmethod
    def global_storage(cls) -> RuleStorage:
        return cls(Path.home() / ".specops" / "rules")

    @classmethod
    def local_storage(cls, root: Path | None = None) -> RuleStorage:
        base = root or Path.cwd()
        return cls(base / ".specops" / "rules")

    def save_rules(self, rules: list[RuleDefinition]) -> Path:
        self.target_dir.mkdir(parents=True, exist_ok=True)
        manifest_rules = []
        for r in rules:
            dest = self.target_dir / r.relative_path
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(r.content, encoding="utf-8")
            manifest_rules.append({
                "id": r.id,
                "category": r.category,
                "file": r.relative_path,
                "description": r.description,
                "sha256": r.sha256,
                "triggers": {"globs": list(r.globs)},
            })
        manifest_path = self.target_dir / "manifest.json"
        manifest_path.write_text(json.dumps({"schema_version": 1, "rules": manifest_rules}, indent=2), encoding="utf-8")
        return self.target_dir

    def delete_all(self) -> None:
        if self.target_dir.exists():
            import shutil
            shutil.rmtree(self.target_dir)
