from pathlib import Path
from rules.core.catalog import RuleCatalog
from rules.adapters import ALL_ADAPTERS


def test_all_adapters_install_and_uninstall_reversibly(tmp_path: Path) -> None:
    catalog = RuleCatalog()
    rules = catalog.rules[:3]
    storage_path = tmp_path / ".specops" / "rules"

    for name, adapter in ALL_ADAPTERS.items():
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


def test_cursor_adapter_generates_native_mdc_rules(tmp_path: Path) -> None:
    cursor_adapter = ALL_ADAPTERS["cursor"]
    catalog = RuleCatalog()
    rules = catalog.rules[:2]
    storage_path = tmp_path / ".specops" / "rules"

    cursor_adapter.install(rules, storage_path, tmp_path, is_global=False)
    mdc_dir = tmp_path / ".cursor" / "rules"
    assert mdc_dir.exists()
    
    for r in rules:
        mdc_file = mdc_dir / f"{r.id}.mdc"
        assert mdc_file.exists()
        content = mdc_file.read_text(encoding="utf-8")
        assert "globs:" in content
        assert "alwaysApply: false" in content

    cursor_adapter.uninstall(tmp_path, is_global=False)
    assert not mdc_dir.exists()
