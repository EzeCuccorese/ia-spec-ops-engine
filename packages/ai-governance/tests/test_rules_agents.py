from pathlib import Path

import pytest
from ai_governance.rules.agents import ALL_ADAPTERS, AgentsRulesAdapter, filter_rules_by_tech
from ai_governance.rules.core.catalog import RuleCatalog


def test_agents_adapter_install_and_uninstall_reversibly(tmp_path: Path) -> None:
    catalog = RuleCatalog()
    rules = catalog.rules[:3]
    storage_path = tmp_path / ".specops" / "rules"
    adapter = AgentsRulesAdapter()

    # 1. Install
    target = adapter.install(rules, storage_path, tmp_path, is_global=False)
    assert target.exists()
    assert target.name == "AGENTS.md"
    content = target.read_text(encoding="utf-8")
    assert "<!-- rules:start -->" in content
    assert "<!-- rules:end -->" in content

    # 2. Add user custom notes
    custom_note = "# Custom Note by Eze"
    target.write_text(f"{custom_note}\n\n{content}", encoding="utf-8")

    # 3. Uninstall
    adapter.uninstall(tmp_path, is_global=False)
    assert target.exists()
    remaining = target.read_text(encoding="utf-8")
    assert "<!-- rules:start -->" not in remaining
    assert custom_note in remaining


def test_all_adapters_registry(tmp_path: Path) -> None:
    assert "agents" in ALL_ADAPTERS
    assert isinstance(ALL_ADAPTERS["agents"], AgentsRulesAdapter)


def test_filter_rules_by_tech_returns_all_rules_when_tech_is_none() -> None:
    catalog = RuleCatalog()
    assert filter_rules_by_tech(catalog.rules, None) == catalog.rules


def test_filter_rules_by_tech_returns_all_rules_when_tech_is_all() -> None:
    catalog = RuleCatalog()
    assert filter_rules_by_tech(catalog.rules, "all") == catalog.rules
    assert filter_rules_by_tech(catalog.rules, "ALL") == catalog.rules


def test_get_target_file_global_scope(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    adapter = AgentsRulesAdapter()
    target = adapter.get_target_file(tmp_path, is_global=True)
    assert target == tmp_path / ".config" / "agents" / "AGENTS.md"


def test_uninstall_when_target_file_missing_returns_none(tmp_path: Path) -> None:
    adapter = AgentsRulesAdapter()
    assert adapter.uninstall(tmp_path, is_global=False) is None
