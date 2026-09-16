"""
test_acceptance_rules.py — Acceptance tests for engineering rules contracts G01–G06.

Contracts from 02-CONTRATOS-DE-TEST.md:
- G01 (test_catalog_update_preserves_user_edits): Updating or uninstalling rules does NOT
      delete user rules or user modifications in catalog files.
- G02 (test_unowned_legacy_install_is_preserved): Legacy unowned rules files (without manifest record)
      are preserved and never deleted by heuristic.
- G03 (test_ownership_updates_are_atomic): Ownership manifest updates are atomic.
- G04 (test_technology_selection_is_respected): Non-interactive selection by technology
      (e.g. Python only, Java only) installs only the rules matching that technology.
- G05 (test_selected_host_is_only_target): Installing for a specific agent does not touch
      or mutate configurations of other agents.
- G06 (test_context_index_points_to_bundled_rules): Rules catalog resolves rules bundled in the package/wheel.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from ai_governance.rules.agents import AgentsRulesAdapter
from ai_governance.rules.cli import main as rules_cli_main
from ai_governance.rules.core.catalog import RuleCatalog
from ai_governance.rules.core.storage import RuleStorage


def test_catalog_update_preserves_user_edits(tmp_path: Path) -> None:
    """G01: Updating or uninstalling rules does NOT delete user rules or user modifications in catalog files."""
    catalog = RuleCatalog()
    storage = RuleStorage(tmp_path / ".specops" / "rules")

    # 1. Initial install
    storage.save_rules(catalog.rules)
    manifest_path = storage.target_dir / "manifest.json"
    assert manifest_path.exists()

    # Find a catalog rule file
    rule_file = storage.target_dir / "1-core" / "01-clean-code-solid.md"
    assert rule_file.exists()
    original_content = rule_file.read_text(encoding="utf-8")

    # 2. User modifies the catalog rule file
    user_modification = (
        "\n\n# User Customization: Project-specific rule additions\n- Strict logging\n"
    )
    modified_content = original_content + user_modification
    rule_file.write_text(modified_content, encoding="utf-8")

    # 3. User creates their own unowned custom rule in the rules directory
    user_rule_file = storage.target_dir / "custom" / "my-team-rules.md"
    user_rule_file.parent.mkdir(parents=True, exist_ok=True)
    user_rule_content = "# Team Specific Invariants\n- Must pass QA review\n"
    user_rule_file.write_text(user_rule_content, encoding="utf-8")

    # 4. Catalog update: save_rules called again (e.g. updating catalog)
    storage.save_rules(catalog.rules)

    # User edit in catalog file must be preserved
    assert rule_file.read_text(encoding="utf-8") == modified_content
    # User's unowned custom rule must be preserved
    assert user_rule_file.exists()
    assert user_rule_file.read_text(encoding="utf-8") == user_rule_content

    # 5. Uninstall rules
    storage.delete_owned()

    # User edit in catalog file must still be preserved (not deleted)
    assert rule_file.exists()
    assert rule_file.read_text(encoding="utf-8") == modified_content

    # User's unowned custom rule must still be preserved
    assert user_rule_file.exists()
    assert user_rule_file.read_text(encoding="utf-8") == user_rule_content

    # Unmodified catalog files that were owned by manifest must be deleted
    unmodified_file = storage.target_dir / "1-core" / "02-clean-architecture-hexagonal.md"
    assert not unmodified_file.exists()


def test_unowned_legacy_install_is_preserved(tmp_path: Path) -> None:
    """G02: Legacy unowned rules files (without manifest record) are preserved and never deleted by heuristic."""
    storage_dir = tmp_path / ".specops" / "rules"
    storage_dir.mkdir(parents=True, exist_ok=True)

    legacy_file_1 = storage_dir / "legacy-standards.md"
    legacy_file_1.write_text("# Old Standards\nDo not touch", encoding="utf-8")

    legacy_sub_dir = storage_dir / "1-core"
    legacy_sub_dir.mkdir(parents=True, exist_ok=True)
    legacy_file_2 = legacy_sub_dir / "01-clean-code-solid.md"
    legacy_file_2.write_text("# Legacy Clean Code without Manifest", encoding="utf-8")

    # Note: No manifest.json exists!
    storage = RuleStorage(storage_dir)

    # Calling delete_owned must NOT delete legacy files
    storage.delete_owned()

    assert legacy_file_1.exists()
    assert legacy_file_1.read_text(encoding="utf-8") == "# Old Standards\nDo not touch"
    assert legacy_file_2.exists()
    assert legacy_file_2.read_text(encoding="utf-8") == "# Legacy Clean Code without Manifest"


def test_ownership_updates_are_atomic(tmp_path: Path) -> None:
    """G03: Ownership manifest updates are atomic."""
    catalog = RuleCatalog()
    storage = RuleStorage(tmp_path / ".specops" / "rules")

    # First write creates manifest
    storage.save_rules(catalog.rules[:5])
    manifest_path = storage.target_dir / "manifest.json"
    assert manifest_path.exists()
    original_manifest = manifest_path.read_text(encoding="utf-8")

    # Simulate an error during atomic write (e.g. power cut / disk error before rename)
    with (
        patch("os.replace", side_effect=OSError("Disk write error during commit")),
        pytest.raises(OSError, match="Disk write error during commit"),
    ):
        storage.save_rules(catalog.rules[:10])

    # The existing manifest must remain intact and valid JSON
    assert manifest_path.exists()
    current_content = manifest_path.read_text(encoding="utf-8")
    assert current_content == original_manifest
    data = json.loads(current_content)
    assert len(data["rules"]) == 5

    # No leftover temporary files
    tmp_files = list(storage.target_dir.glob("*.tmp*"))
    assert len(tmp_files) == 0


def test_technology_selection_is_respected(tmp_path: Path) -> None:
    """G04: Non-interactive selection by technology (e.g. Python only, Java only) installs only the rules matching that technology."""
    root_py = tmp_path / "py_project"
    root_py.mkdir()

    # 1. Install with --tech python
    rules_cli_main(["install", "--local", "--tech", "python", "--root", str(root_py)])

    py_rules_dir = root_py / ".specops" / "rules"
    assert (py_rules_dir / "2-stacks" / "python-async.md").exists()
    assert not (py_rules_dir / "2-stacks" / "java-spring.md").exists()
    assert not (py_rules_dir / "2-stacks" / "go-idiomatic.md").exists()

    manifest_py = json.loads((py_rules_dir / "manifest.json").read_text(encoding="utf-8"))
    py_rule_ids = [r["id"] for r in manifest_py["rules"]]
    assert "python-async" in py_rule_ids
    assert "java-spring" not in py_rule_ids

    # AGENTS.md index must contain python-async and not java-spring
    agents_md = (root_py / "AGENTS.md").read_text(encoding="utf-8")
    assert "python-async" in agents_md
    assert "java-spring" not in agents_md

    # 2. Install with --tech java
    root_java = tmp_path / "java_project"
    root_java.mkdir()

    rules_cli_main(["install", "--local", "--tech", "java", "--root", str(root_java)])

    java_rules_dir = root_java / ".specops" / "rules"
    assert (java_rules_dir / "2-stacks" / "java-spring.md").exists()
    assert not (java_rules_dir / "2-stacks" / "python-async.md").exists()

    manifest_java = json.loads((java_rules_dir / "manifest.json").read_text(encoding="utf-8"))
    java_rule_ids = [r["id"] for r in manifest_java["rules"]]
    assert "java-spring" in java_rule_ids
    assert "python-async" not in java_rule_ids


def test_selected_host_is_only_target(tmp_path: Path) -> None:
    """G05: Installing for a specific agent does not touch or mutate configurations of other agents."""
    # 1. Target: Universal AGENTS standard
    root_agents = tmp_path / "target_agents"
    root_agents.mkdir()
    rules_cli_main(["install", "--local", "--all", "--agent", "agents", "--root", str(root_agents)])
    assert (root_agents / "AGENTS.md").exists()
    assert not (root_agents / "CLAUDE.md").exists()
    assert not (root_agents / ".cursorrules").exists()

    # Provider-specific writes belong to the agent installer, not rules.
    for provider in ("claude", "cursor"):
        target = tmp_path / provider
        with pytest.raises(SystemExit) as exc:
            rules_cli_main(
                ["install", "--local", "--all", "--agent", provider, "--root", str(target)]
            )
        assert exc.value.code == 2
        assert not target.exists()


def test_context_index_points_to_bundled_rules(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """G06: Rules catalog resolves rules bundled in the package/wheel."""
    # Run from an isolated directory far away from repo
    isolated_dir = tmp_path / "isolated_dir"
    isolated_dir.mkdir()
    monkeypatch.chdir(isolated_dir)

    catalog = RuleCatalog()
    assert len(catalog.rules) >= 25

    # Validate that every rule resolves valid bundled content
    for rule in catalog.rules:
        assert rule.id
        assert rule.relative_path
        assert rule.content.startswith("# ")
        assert len(rule.content) > 50

    # Validate that generated index links point to valid rule targets
    storage_path = isolated_dir / ".specops" / "rules"
    adapter = AgentsRulesAdapter()
    block = adapter.render_block(catalog.rules, storage_path)

    for rule in catalog.rules:
        expected_target = f"[{rule.relative_path}]({storage_path / rule.relative_path})"
        assert expected_target in block
