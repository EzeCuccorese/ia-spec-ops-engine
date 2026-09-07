from pathlib import Path

from ai_governance.rules.adapters import ALL_ADAPTERS
from ai_governance.rules.core.catalog import RuleCatalog


def test_all_adapters_install_and_uninstall_reversibly(tmp_path: Path) -> None:
    catalog = RuleCatalog()
    rules = catalog.rules[:3]
    storage_path = tmp_path / ".specops" / "rules"

    for _name, adapter in ALL_ADAPTERS.items():
        # 1. Install
        target = adapter.install(rules, storage_path, tmp_path, is_global=False)
        assert target.exists()
        content = target.read_text(encoding="utf-8")
        assert "<!-- rules:start -->" in content
        assert "<!-- rules:end -->" in content

        # 2. Add user custom notes
        custom_note = "# Custom Note by Eze"
        target.write_text(f"{custom_note}\n\n{content}", encoding="utf-8")

        # 3. Uninstall
        adapter.uninstall(tmp_path, is_global=False)
        if target.exists():
            remaining = target.read_text(encoding="utf-8")
            assert "<!-- rules:start -->" not in remaining
            assert custom_note in remaining
