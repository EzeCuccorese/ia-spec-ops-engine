import json
from pathlib import Path

import pytest

from spec.agents import AgentsAdapter
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
