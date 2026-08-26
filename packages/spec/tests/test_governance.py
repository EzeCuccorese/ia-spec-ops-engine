import json
from pathlib import Path

import pytest

from spec.adapters.codex import CodexAdapter
from spec.core.ownership import FileChangedError, OwnershipManifest
from spec.core.write import TargetExistsError
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


def test_codex_adapter_creates_real_discovered_agents_file(tmp_path: Path) -> None:
    ProjectGovernance(tmp_path).initialize()

    result = CodexAdapter(tmp_path).install()

    agents = tmp_path / "AGENTS.md"
    assert result.path == "AGENTS.md"
    assert result.created is True
    assert "spec verify" in agents.read_text()
    assert OwnershipManifest(tmp_path).get("AGENTS.md") is not None


def test_codex_adapter_refuses_to_replace_existing_agents_file(tmp_path: Path) -> None:
    agents = tmp_path / "AGENTS.md"
    agents.write_text("user rules\n")

    with pytest.raises(TargetExistsError, match="unowned"):
        CodexAdapter(tmp_path).install()

    assert agents.read_text() == "user rules\n"


def test_codex_adapter_uninstall_is_dry_run_first_and_ownership_safe(tmp_path: Path) -> None:
    adapter = CodexAdapter(tmp_path)
    adapter.install()

    preview = adapter.uninstall(dry_run=True)
    assert preview.would_delete is True
    assert (tmp_path / "AGENTS.md").exists()

    removed = adapter.uninstall(dry_run=False)
    assert removed.deleted is True
    assert not (tmp_path / "AGENTS.md").exists()


def test_codex_adapter_will_not_remove_user_modified_generated_file(tmp_path: Path) -> None:
    adapter = CodexAdapter(tmp_path)
    adapter.install()
    (tmp_path / "AGENTS.md").write_text("user changed this\n")

    with pytest.raises(FileChangedError):
        adapter.uninstall(dry_run=False)

    assert (tmp_path / "AGENTS.md").exists()
