from pathlib import Path

from ai_governance.rules.agents import AgentsRulesAdapter
from ai_governance.rules.core.catalog import RuleCatalog


def test_render_block_without_tools_has_no_harness_section() -> None:
    """render_block with default tools=() should not include Harness Tools heading."""
    catalog = RuleCatalog()
    rules = catalog.rules[:2]
    storage_path = Path("/tmp/.specops/rules")
    adapter = AgentsRulesAdapter()

    block = adapter.render_block(rules, storage_path)
    assert "## Harness Tools" not in block
    assert "Engineering Standards Index" in block


def test_render_block_with_tools_includes_harness_section() -> None:
    """render_block with tools should include Harness Tools heading and tool rows."""
    catalog = RuleCatalog()
    rules = catalog.rules[:2]
    storage_path = Path("/tmp/.specops/rules")
    adapter = AgentsRulesAdapter()

    block = adapter.render_block(rules, storage_path, tools=catalog.tools)
    assert "## Harness Tools" in block
    assert "⚙ <tool-id> <args>" in block
    assert "Deterministic alternative:" in block or "deterministic" in block.lower()

    # Count tool rows: each tool row has "| **tool-id**"
    table_start = block.find("## Harness Tools")
    tools_section = block[table_start:]
    tool_row_count = tools_section.count("| **")
    assert tool_row_count == len(catalog.tools)


def test_render_block_tools_ordered_on_demand_first() -> None:
    """On-demand tools should appear before automatic tools in the table."""
    catalog = RuleCatalog()
    rules = catalog.rules[:2]
    storage_path = Path("/tmp/.specops/rules")
    adapter = AgentsRulesAdapter()

    block = adapter.render_block(rules, storage_path, tools=catalog.tools)

    # Find the harness section
    table_start = block.find("## Harness Tools")
    tools_section = block[table_start:]

    # Find indices of first on-demand and first automatic tool
    on_demand_tools = [t for t in catalog.tools if t.trigger == "on-demand"]
    automatic_tools = [t for t in catalog.tools if t.trigger != "on-demand"]

    if on_demand_tools and automatic_tools:
        first_on_demand_id = on_demand_tools[0].id
        first_automatic_id = automatic_tools[0].id

        idx_on_demand = tools_section.find(f"| **{first_on_demand_id}**")
        idx_automatic = tools_section.find(f"| **{first_automatic_id}**")

        assert idx_on_demand < idx_automatic


def test_install_twice_maintains_single_blocks() -> None:
    """Installing twice should result in exactly one rules block and one tools block."""
    catalog = RuleCatalog()
    rules = catalog.rules[:2]
    storage_path = Path("/tmp/.specops/rules")
    adapter = AgentsRulesAdapter()

    # First install
    target = adapter.install(
        rules, storage_path, Path("/tmp"), is_global=False, tools=catalog.tools
    )
    assert target.exists()
    content1 = target.read_text(encoding="utf-8")

    count_start1 = content1.count("<!-- rules:start -->")
    count_tools1 = content1.count("## Harness Tools")
    assert count_start1 == 1
    assert count_tools1 == 1

    # Second install
    adapter.install(rules, storage_path, Path("/tmp"), is_global=False, tools=catalog.tools)
    content2 = target.read_text(encoding="utf-8")

    count_start2 = content2.count("<!-- rules:start -->")
    count_tools2 = content2.count("## Harness Tools")
    assert count_start2 == 1
    assert count_tools2 == 1


def test_uninstall_removes_blocks() -> None:
    """Uninstall should remove both rules:start and Harness Tools blocks."""
    catalog = RuleCatalog()
    rules = catalog.rules[:2]
    storage_path = Path("/tmp/.specops/rules")
    adapter = AgentsRulesAdapter()

    # Install
    target = adapter.install(
        rules, storage_path, Path("/tmp"), is_global=False, tools=catalog.tools
    )
    assert target.exists()
    content_before = target.read_text(encoding="utf-8")
    assert "<!-- rules:start -->" in content_before
    assert "## Harness Tools" in content_before

    # Uninstall
    adapter.uninstall(Path("/tmp"), is_global=False)
    # File may be deleted if it becomes empty, or it may still exist without blocks
    if target.exists():
        content_after = target.read_text(encoding="utf-8")
        assert "<!-- rules:start -->" not in content_after
        assert "## Harness Tools" not in content_after
