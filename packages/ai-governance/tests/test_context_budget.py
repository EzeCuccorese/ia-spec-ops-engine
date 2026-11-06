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
ENTRY_BLOCK_MAX = 500


def test_static_content_budgets() -> None:
    assert len(content.GLOBAL_INSTRUCTIONS.encode()) <= GLOBAL_MAX
    assert len(content.claude_agents_block(Path("~/.claude/rules")).encode()) <= ENTRY_BLOCK_MAX
    block = content.PROJECT_BLOCK.format(rule_locations="x" * 150)
    assert len(block.encode()) <= PROJECT_BLOCK_MAX
    assert len((content.SCOUT_DESCRIPTION + content.SCOUT_INSTRUCTIONS).encode()) <= SCOUT_MAX
    assert len((content.RUNNER_DESCRIPTION + content.RUNNER_INSTRUCTIONS).encode()) <= SCOUT_MAX
    for name, body in content.SKILLS.items():
        assert len(body.encode()) <= SKILL_MAX, name


@pytest.mark.parametrize("rule", RuleCatalog().rules, ids=lambda rule: rule.id)
def test_rule_budget(rule) -> None:
    assert len(rule.content.encode()) <= RULE_MAX, f"{rule.id} exceeds {RULE_MAX} bytes"


def test_always_on_rules_are_security_and_general_tools() -> None:
    always = {rule.id for rule in RuleCatalog().rules if rule.always_on}
    assert always == {
        "06-security-privacy",
        "13-atlassian",
        "14-taskflow",
        "15-tool-confidentiality",
        "16-git-branch-ownership",
        "17-quality-gate",
        "circleci",
    }


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

    # Global instructions, the Claude entry blocks and the 6 always-on tool rules.
    assert user["claude"] <= GLOBAL_MAX + ENTRY_BLOCK_MAX + 7 * (RULE_MAX + 300)
    # The 7 always-on rules (read by each agent once) plus the shared AGENTS.md block.
    assert project["claude"] <= 7 * (RULE_MAX + 300)
    assert project["project"] <= PROJECT_BLOCK_MAX + 7 * (RULE_MAX + 300)


def test_readme_agents_table_is_generated() -> None:
    from ai_governance.install.agents import capability_table

    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text()
    section = readme.split("<!-- agents-table:start -->\n", 1)[1].split(
        "<!-- agents-table:end -->"
    )[0]
    assert section.strip() == capability_table().strip()


def test_user_content_outside_block_measured_and_trimming_changes_number(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setenv("AI_GOVERNANCE_STATE_DIR", str(tmp_path / "state"))
    install_user(["claude"])

    agents_md = tmp_path / ".claude" / "AGENTS.md"
    initial_content = agents_md.read_text(encoding="utf-8")

    user_note = "# My custom instructions\nRemember to write clean code.\n" * 10
    agents_md.write_text(f"{user_note}\n{initial_content}", encoding="utf-8")

    cost1 = fixed_cost(installer.global_ledger())
    assert "usuario" in cost1
    assert cost1["usuario"] == len(user_note.strip().encode("utf-8"))

    # Trimming user content changes the reported number
    trimmed_note = "# My custom instructions\nBe concise.\n"
    agents_md.write_text(f"{trimmed_note}\n{initial_content}", encoding="utf-8")

    cost2 = fixed_cost(installer.global_ledger())
    assert "usuario" in cost2
    assert cost2["usuario"] == len(trimmed_note.strip().encode("utf-8"))
    assert cost2["usuario"] < cost1["usuario"]


def test_codex_fixed_cost_includes_always_personal_and_company_index(
    monkeypatch, tmp_path: Path
) -> None:
    from ai_governance import personal

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setenv("AI_GOVERNANCE_STATE_DIR", str(tmp_path / "state"))

    # Setup corporate rules
    corp_dir = tmp_path / "corporate-rules"
    rules_dir = corp_dir / "acme" / "rules"
    rules_dir.mkdir(parents=True)
    (rules_dir / "glossary.md").write_text(
        "---\ntrigger: always_on\n---\n# Glossary\nLarge text " * 50
    )
    (rules_dir / "principles.md").write_text("# Principles\nLarge text " * 50)
    monkeypatch.setenv("AI_GOVERNANCE_CORPORATE_DIR", str(corp_dir))

    # Setup personal rules
    p_dir = tmp_path / "personal"
    personal.create_rule("voice", "# Voice\nBe concise.\n", root=p_dir)
    monkeypatch.setenv("AI_GOVERNANCE_PERSONAL_DIR", str(p_dir))

    install_user(["codex"])
    cost = fixed_cost(installer.global_ledger())

    codex_home = tmp_path / ".codex" / "ai-governance"
    always_size = sum(len(p.read_bytes()) for p in (codex_home / "always").glob("*.md"))
    personal_size = sum(len(p.read_bytes()) for p in (codex_home / "personal").glob("*.md"))
    company_index_size = len((codex_home / "company" / "index.md").read_bytes())

    # The individual company rule files (~large) must NOT be counted in fixed cost
    glossary_size = len((codex_home / "company" / "acme-glossary.md").read_bytes())
    assert cost["codex"] < always_size + personal_size + company_index_size + glossary_size
    assert cost["codex"] >= always_size + personal_size + company_index_size
