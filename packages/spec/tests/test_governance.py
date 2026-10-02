import json
from pathlib import Path

import pytest
from spec.agents import AgentsAdapter, render_governance
from spec.core.ownership import FileChangedError, OwnershipManifest
from spec.governance.project import ProjectGovernance


def test_project_init_creates_owned_local_policy_and_empty_verification(tmp_path: Path) -> None:
    result = ProjectGovernance(tmp_path).initialize()

    assert result.created == (".spec/policy.json", ".spec/verification.json")
    policy = json.loads((tmp_path / ".spec/policy.json").read_text())
    verification = json.loads((tmp_path / ".spec/verification.json").read_text())
    assert policy["scope"] == "ai-governance-and-sdd"
    assert verification == {"schema_version": 1, "checks": []}
    manifest = OwnershipManifest(tmp_path)
    assert manifest.get(".spec/policy.json") is not None
    assert manifest.get(".spec/verification.json") is not None


def test_project_init_is_idempotent_and_preserves_configured_checks(tmp_path: Path) -> None:
    governance = ProjectGovernance(tmp_path)
    governance.initialize()
    verification = tmp_path / ".spec/verification.json"
    configured = '{"schema_version": 1, "checks": [{"id": "tests"}]}\n'
    verification.write_text(configured)

    result = ProjectGovernance(tmp_path).initialize()

    assert result.created == ()
    assert set(result.existing) == {".spec/policy.json", ".spec/verification.json"}
    assert verification.read_text() == configured


def test_project_governance_audit_delegates_to_project_auditor(tmp_path: Path) -> None:
    ProjectGovernance(tmp_path).initialize()

    report = ProjectGovernance(tmp_path).audit()

    assert report is not None


def test_agents_adapter_creates_governance_and_injects_agents_file(tmp_path: Path) -> None:
    ProjectGovernance(tmp_path).initialize()

    result = AgentsAdapter(tmp_path).install()

    agents = tmp_path / "AGENTS.md"
    assert result.path == ".spec/governance.md"
    assert result.created is True
    assert (tmp_path / ".spec/governance.md").exists()
    assert "<!-- spec:governance -->" in agents.read_text()
    assert "@.spec/governance.md" in agents.read_text()
    assert OwnershipManifest(tmp_path).get(".spec/governance.md") is not None


def test_agents_adapter_preserves_existing_user_agents_file(tmp_path: Path) -> None:
    agents = tmp_path / "AGENTS.md"
    user_note = "# Custom Project Prompt\n\nUser instructions."
    agents.write_text(user_note)

    AgentsAdapter(tmp_path).install()

    content = agents.read_text()
    assert content.startswith(user_note)
    assert "<!-- spec:governance -->" in content
    assert "@.spec/governance.md" in content


def test_agents_adapter_uninstall_removes_block_preserving_user_notes(tmp_path: Path) -> None:
    adapter = AgentsAdapter(tmp_path)
    adapter.install()

    agents = tmp_path / "AGENTS.md"
    user_note = "# Custom Project Prompt\n\nUser instructions."
    agents.write_text(f"{user_note}\n\n{agents.read_text()}")

    adapter.uninstall(dry_run=False)

    assert not (tmp_path / ".spec/governance.md").exists()
    assert agents.exists()
    content = agents.read_text()
    assert "<!-- spec:governance -->" not in content
    assert user_note in content


def test_agents_adapter_refuses_to_delete_modified_governance_file(tmp_path: Path) -> None:
    adapter = AgentsAdapter(tmp_path)
    adapter.install()
    (tmp_path / ".spec/governance.md").write_text("user changed this\n")

    with pytest.raises(FileChangedError):
        adapter.uninstall(dry_run=False)

    assert (tmp_path / ".spec/governance.md").exists()


def test_claude_adapter_installs_and_uninstalls_reversibly(tmp_path: Path) -> None:
    ProjectGovernance(tmp_path).initialize()
    adapter = AgentsAdapter(tmp_path, agent="claude")

    # 1. Install creates governance.md, AGENTS.md and the skills, never CLAUDE.md
    res = adapter.install()
    assert res.created is True
    assert (tmp_path / ".spec/governance.md").exists()
    assert (tmp_path / "AGENTS.md").exists()
    assert (tmp_path / ".claude/skills/spec-new/SKILL.md").exists()
    assert not (tmp_path / "CLAUDE.md").exists()

    manifest = OwnershipManifest(tmp_path)
    assert manifest.get("CLAUDE.md") is None
    assert manifest.get(".spec/governance.md") is not None

    # 2. Uninstall cleanly removes all generated files
    del_res = adapter.uninstall(dry_run=False)
    assert del_res.deleted is True
    assert not (tmp_path / ".spec/governance.md").exists()
    assert not (tmp_path / "AGENTS.md").exists()
    assert not (tmp_path / ".claude/skills/spec-new/SKILL.md").exists()
    assert OwnershipManifest(tmp_path).get(".spec/governance.md") is None


def test_engine_checkout_gets_the_same_governance_without_bootstrap(tmp_path: Path) -> None:
    """The root AGENTS.md forbids installing or configuring anything unasked, so the engine
    checkout gets the same workflow as any project and no bootstrap commands."""
    (tmp_path / "packages" / "spec" / "src" / "spec").mkdir(parents=True)
    (tmp_path / "packages" / "spec" / "src" / "spec" / "__init__.py").touch()
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "ia-spec-ops-engine"\n')

    rendered = AgentsAdapter(tmp_path).render()

    assert rendered == render_governance()
    for command in ("./install.sh", "specops", "Bootstrap Protocol"):
        assert command not in rendered
