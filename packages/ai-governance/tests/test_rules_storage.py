"""Direct unit tests for ai_governance.rules.core.storage covering edge branches
not exercised by the higher-level acceptance tests in test_acceptance_rules.py."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from ai_governance.rules.core.catalog import RuleCatalog
from ai_governance.rules.core.storage import RuleStorage


def test_global_storage_points_under_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    storage = RuleStorage.global_storage()
    assert storage.target_dir == tmp_path / ".specops" / "rules"


def test_save_rules_with_corrupt_existing_manifest_is_treated_as_empty(
    tmp_path: Path,
) -> None:
    storage = RuleStorage(tmp_path / ".specops" / "rules")
    storage.target_dir.mkdir(parents=True, exist_ok=True)
    (storage.target_dir / "manifest.json").write_text("{not valid json", encoding="utf-8")

    catalog = RuleCatalog()
    storage.save_rules(catalog.rules[:2])

    manifest = json.loads((storage.target_dir / "manifest.json").read_text(encoding="utf-8"))
    assert len(manifest["rules"]) == 2


def test_save_rules_preserves_unowned_existing_file(tmp_path: Path) -> None:
    catalog = RuleCatalog()
    rule = catalog.rules[0]
    storage = RuleStorage(tmp_path / ".specops" / "rules")
    storage.target_dir.mkdir(parents=True, exist_ok=True)

    # A file already sits at the rule's destination but is unowned (no manifest entry).
    dest = storage.target_dir / rule.relative_path
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("# Pre-existing unowned content", encoding="utf-8")

    storage.save_rules([rule])

    assert dest.read_text(encoding="utf-8") == "# Pre-existing unowned content"
    manifest = json.loads((storage.target_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["rules"] == []


def test_delete_owned_with_corrupt_manifest_returns_empty(tmp_path: Path) -> None:
    storage = RuleStorage(tmp_path / ".specops" / "rules")
    storage.target_dir.mkdir(parents=True, exist_ok=True)
    (storage.target_dir / "manifest.json").write_text("{not valid json", encoding="utf-8")

    assert storage.delete_owned() == []
    # Corrupt manifest is left untouched (not deleted) since we returned early.
    assert (storage.target_dir / "manifest.json").exists()


def test_delete_owned_skips_manifest_entries_without_file_key(tmp_path: Path) -> None:
    storage = RuleStorage(tmp_path / ".specops" / "rules")
    storage.target_dir.mkdir(parents=True, exist_ok=True)
    manifest = {"schema_version": 1, "rules": [{"id": "no-file-entry"}]}
    (storage.target_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    deleted = storage.delete_owned()
    assert deleted == []


def test_delete_owned_skips_missing_files_on_disk(tmp_path: Path) -> None:
    storage = RuleStorage(tmp_path / ".specops" / "rules")
    storage.target_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema_version": 1,
        "rules": [{"id": "ghost", "file": "ghost.md", "sha256": "deadbeef"}],
    }
    (storage.target_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    deleted = storage.delete_owned()
    assert deleted == []
