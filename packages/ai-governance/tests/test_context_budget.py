"""Context budgets: every byte below can be loaded into a model, so sizes are capped."""

from __future__ import annotations

from pathlib import Path

import pytest
from ai_governance.install import content, installer
from ai_governance.install.budget import fixed_cost
from ai_governance.install.engine import Ledger
from ai_governance.install.installer import PROJECT_DIR, install_user, sync_project
from ai_governance.rules.catalog import RuleCatalog

GLOBAL_MAX = 1024
PROJECT_BLOCK_MAX = 1024
RULE_MAX = 1000
SCOUT_MAX = 700
SKILL_MAX = 1024


def test_static_content_budgets() -> None:
    assert len(content.GLOBAL_INSTRUCTIONS.encode()) <= GLOBAL_MAX
    block = content.PROJECT_BLOCK.format(rule_locations="x" * 150)
    assert len(block.encode()) <= PROJECT_BLOCK_MAX
    assert len((content.SCOUT_DESCRIPTION + content.SCOUT_INSTRUCTIONS).encode()) <= SCOUT_MAX
    for name, body in content.SKILLS.items():
        assert len(body.encode()) <= SKILL_MAX, name


@pytest.mark.parametrize("rule", RuleCatalog().rules, ids=lambda rule: rule.id)
def test_rule_budget(rule) -> None:
    assert len(rule.content.encode()) <= RULE_MAX, f"{rule.id} exceeds {RULE_MAX} bytes"


def test_general_rules_are_path_scoped_except_security() -> None:
    always = {rule.id for rule in RuleCatalog().rules if rule.always_on}
    assert always == {"06-security-privacy"}


def test_fixed_session_cost_for_a_typical_install(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setenv("AI_GOVERNANCE_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setattr(installer, "detect_stacks", lambda root: {"java", "docker"})
    root = tmp_path / "repo"
    root.mkdir()
    install_user(["claude"])
    sync_project(root, add_agents=["claude", "antigravity"])

    user = fixed_cost(installer.global_ledger())
    project = fixed_cost(Ledger(root / PROJECT_DIR / "lock.json", base=root))

    assert user["claude"] <= GLOBAL_MAX
    # The single always-on rule (read by each agent once) plus the shared AGENTS.md block.
    assert project["claude"] <= RULE_MAX + 300  # symlink to the canonical always-on rule
    assert project["project"] <= PROJECT_BLOCK_MAX + RULE_MAX + 300


def test_readme_agents_table_is_generated() -> None:
    from ai_governance.install.agents import capability_table

    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text()
    section = readme.split("<!-- agents-table:start -->\n", 1)[1].split(
        "<!-- agents-table:end -->"
    )[0]
    assert section.strip() == capability_table().strip()
