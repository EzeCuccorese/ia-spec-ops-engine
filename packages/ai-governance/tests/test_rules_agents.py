from pathlib import Path

from ai_governance.rules.agents import ALL_ADAPTERS, AgentsRulesAdapter
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
