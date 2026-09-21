import json
from pathlib import Path
from unittest.mock import patch

import pytest
from ai_governance.rules.core.catalog import FAIL_MODES, IO_KINDS, TRIGGERS, RuleCatalog


def test_catalog_loads_all_canonical_rules() -> None:
    catalog = RuleCatalog()
    assert len(catalog.rules) >= 25

    categories = catalog.by_category()
    assert "1-core" in categories
    assert "2-stacks" in categories
    assert "3-infrastructure" in categories
    assert "4-docs" in categories


def test_every_rule_has_valid_metadata_and_invariants() -> None:
    catalog = RuleCatalog()
    for rule in catalog.rules:
        assert rule.id
        assert rule.description
        assert len(rule.globs) > 0
        assert rule.content.startswith("# ")
        assert len(rule.content) > 100
        assert rule.sha256


def test_catalog_loads_at_least_fifteen_tools() -> None:
    catalog = RuleCatalog()
    assert len(catalog.tools) >= 15


def test_every_tool_has_valid_metadata() -> None:
    catalog = RuleCatalog()
    for tool in catalog.tools:
        assert tool.trigger in TRIGGERS
        assert tool.fail_mode in FAIL_MODES
        assert tool.io_stdin in IO_KINDS
        assert tool.io_stdout in IO_KINDS


def test_tools_by_trigger_keys_are_known_triggers() -> None:
    catalog = RuleCatalog()
    grouped = catalog.tools_by_trigger()
    assert set(grouped.keys()) <= TRIGGERS


def test_automatic_and_on_demand_tools_partition_all_tools() -> None:
    catalog = RuleCatalog()
    automatic = catalog.automatic_tools()
    on_demand = catalog.on_demand_tools()
    assert set(t.id for t in automatic) & set(t.id for t in on_demand) == set()
    assert set(t.id for t in automatic) | set(t.id for t in on_demand) == set(
        t.id for t in catalog.tools
    )
    assert all(t.trigger != "on-demand" for t in automatic)
    assert all(t.trigger == "on-demand" for t in on_demand)


def test_get_tool_frugal_post_bash_has_replaces() -> None:
    catalog = RuleCatalog()
    tool = catalog.get_tool("frugal-post-bash")
    assert tool is not None
    assert len(tool.replaces) > 0


def _write_manifest(tmp_path: Path, tools: list[dict]) -> Path:
    manifest = {
        "schema_version": 1,
        "total_rules": 0,
        "rules": [],
        "tools": tools,
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return tmp_path


def test_invalid_trigger_raises_value_error_naming_tool_id(tmp_path: Path) -> None:
    root = _write_manifest(
        tmp_path,
        [
            {
                "id": "bad-tool",
                "package": "ai-governance",
                "command": "bad-tool",
                "purpose": "Broken",
                "trigger": "not-a-real-trigger",
            }
        ],
    )
    with pytest.raises(ValueError, match="bad-tool"):
        RuleCatalog(catalog_root=root)


def test_manifest_without_tools_key_yields_empty_tools_and_loads_rules(tmp_path: Path) -> None:
    manifest = {"schema_version": 1, "total_rules": 0, "rules": []}
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    catalog = RuleCatalog(catalog_root=tmp_path)
    assert catalog.tools == []
    assert catalog.rules == []


def test_invalid_fail_mode_raises_value_error_naming_tool_id(tmp_path: Path) -> None:
    root = _write_manifest(
        tmp_path,
        [
            {
                "id": "bad-fail-mode",
                "package": "ai-governance",
                "command": "bad-tool",
                "purpose": "Broken",
                "trigger": "on-demand",
                "fail_mode": "not-a-real-mode",
            }
        ],
    )
    with pytest.raises(ValueError, match="bad-fail-mode"):
        RuleCatalog(catalog_root=root)


def test_invalid_io_stdin_raises_value_error_naming_tool_id(tmp_path: Path) -> None:
    root = _write_manifest(
        tmp_path,
        [
            {
                "id": "bad-stdin",
                "package": "ai-governance",
                "command": "bad-tool",
                "purpose": "Broken",
                "trigger": "on-demand",
                "io": {"stdin": "not-a-real-kind"},
            }
        ],
    )
    with pytest.raises(ValueError, match="bad-stdin"):
        RuleCatalog(catalog_root=root)


def test_invalid_io_stdout_raises_value_error_naming_tool_id(tmp_path: Path) -> None:
    root = _write_manifest(
        tmp_path,
        [
            {
                "id": "bad-stdout",
                "package": "ai-governance",
                "command": "bad-tool",
                "purpose": "Broken",
                "trigger": "on-demand",
                "io": {"stdout": "not-a-real-kind"},
            }
        ],
    )
    with pytest.raises(ValueError, match="bad-stdout"):
        RuleCatalog(catalog_root=root)


def test_catalog_root_without_manifest_yields_empty_catalog(tmp_path: Path) -> None:
    """_load() returns early when manifest.json does not exist at catalog_root."""
    catalog = RuleCatalog(catalog_root=tmp_path)
    assert catalog.rules == []
    assert catalog.tools == []


def test_manifest_rule_entry_with_missing_file_is_skipped(tmp_path: Path) -> None:
    """A rule item whose backing file does not exist on disk is silently skipped."""
    manifest = {
        "schema_version": 1,
        "rules": [
            {
                "id": "ghost-rule",
                "category": "1-core",
                "file": "does-not-exist.md",
                "description": "Ghost",
                "triggers": {"globs": ["**/*"]},
            }
        ],
        "tools": [],
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    catalog = RuleCatalog(catalog_root=tmp_path)
    assert catalog.rules == []


def test_root_resolution_falls_back_to_parent_search_when_importlib_fails(
    tmp_path: Path,
) -> None:
    """When importlib.resources raises, RuleCatalog falls back to walking parent dirs
    looking for a bundled catalog/ directory with a manifest.json."""
    with patch(
        "importlib.resources.files",
        side_effect=ModuleNotFoundError("no such package"),
    ):
        catalog = RuleCatalog()
    # The parent-directory fallback should still locate the real bundled catalog.
    assert len(catalog.rules) >= 25


def test_root_resolution_falls_back_when_importlib_resources_dir_incomplete(
    tmp_path: Path,
) -> None:
    """When importlib.resources resolves but the package has no catalog/manifest.json,
    RuleCatalog falls back to walking parent directories."""
    with patch("importlib.resources.files", return_value=tmp_path):
        catalog = RuleCatalog()
    assert len(catalog.rules) >= 25


def test_root_resolution_uses_default_when_no_catalog_dir_found_anywhere() -> None:
    """When both importlib.resources and the parent-directory walk fail to locate a
    catalog/manifest.json, RuleCatalog falls back to the default computed path."""
    with (
        patch("importlib.resources.files", side_effect=ModuleNotFoundError("missing")),
        patch("pathlib.Path.is_dir", return_value=False),
    ):
        catalog = RuleCatalog()
    # No manifest was found anywhere, so the catalog loads empty rather than raising.
    assert catalog.rules == []
    assert catalog.tools == []
