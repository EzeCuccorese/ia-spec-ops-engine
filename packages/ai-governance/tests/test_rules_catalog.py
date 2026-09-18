import json
from pathlib import Path

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
