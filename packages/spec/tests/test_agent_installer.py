from __future__ import annotations

from pathlib import Path

import pytest
from spec.cli import main
from spec.core.ownership import OwnershipManifest
from spec.governance.project import ProjectGovernance


def test_agent_install_single_claude(tmp_path: Path) -> None:
    ProjectGovernance(tmp_path).initialize()
    with pytest.raises(SystemExit) as exc:
        main(["agent", "install", "claude", "--root", str(tmp_path)])
    assert exc.value.code == 0

    agents_md = tmp_path / "AGENTS.md"
    assert agents_md.exists()
    assert "@.spec/governance.md" in agents_md.read_text(encoding="utf-8")

    claude_md = tmp_path / "CLAUDE.md"
    assert claude_md.exists()
    claude_content = claude_md.read_text(encoding="utf-8")
    assert "<!-- spec:governance -->" in claude_content
    assert "@AGENTS.md" in claude_content
    assert "<!-- /spec:governance -->" in claude_content

    manifest = OwnershipManifest(tmp_path)
    assert manifest.get("CLAUDE.md") is not None
    assert (tmp_path / ".claude" / "skills" / "spec-new" / "SKILL.md").exists()
    assert (tmp_path / ".agents" / "skills" / "spec-new" / "SKILL.md").exists()
    assert manifest.get(".claude/skills/spec-new/SKILL.md") is not None


def test_agent_uninstall_single_claude(tmp_path: Path) -> None:
    ProjectGovernance(tmp_path).initialize()
    with pytest.raises(SystemExit):
        main(["agent", "install", "claude", "--root", str(tmp_path)])
    assert (tmp_path / "AGENTS.md").exists()
    assert (tmp_path / "CLAUDE.md").exists()
    assert (tmp_path / ".claude" / "skills" / "spec-new" / "SKILL.md").exists()

    with pytest.raises(SystemExit) as exc:
        main(["agent", "uninstall", "claude", "--apply", "--root", str(tmp_path)])
    assert exc.value.code == 0
    assert not (tmp_path / "AGENTS.md").exists()
    assert not (tmp_path / "CLAUDE.md").exists()
    assert not (tmp_path / ".claude" / "skills" / "spec-new" / "SKILL.md").exists()
    assert OwnershipManifest(tmp_path).get("CLAUDE.md") is None


def test_agent_uninstall_claude_preserves_user_content(tmp_path: Path) -> None:
    ProjectGovernance(tmp_path).initialize()
    with pytest.raises(SystemExit):
        main(["agent", "install", "claude", "--root", str(tmp_path)])

    claude_md = tmp_path / "CLAUDE.md"
    custom_content = "# User Claude Instructions\nSome project notes."
    claude_md.write_text(f"{custom_content}\n\n{claude_md.read_text(encoding='utf-8')}")

    with pytest.raises(SystemExit) as exc:
        main(["agent", "uninstall", "claude", "--apply", "--root", str(tmp_path)])
    assert exc.value.code == 0
    assert claude_md.exists()
    remaining = claude_md.read_text(encoding="utf-8")
    assert "<!-- spec:governance -->" not in remaining
    assert custom_content in remaining


def test_agent_install_mock_consumer_repo_renders_consumer(tmp_path: Path) -> None:
    ProjectGovernance(tmp_path).initialize()
    with pytest.raises(SystemExit) as exc:
        main(["agent", "install", "agents", "--root", str(tmp_path)])
    assert exc.value.code == 0

    gov_md = tmp_path / ".spec/governance.md"
    assert gov_md.exists()
    content = gov_md.read_text(encoding="utf-8")

    # Pure SDD consumer workflow
    assert "Three Laws of TDD" in content
    assert "@s" in content
    assert "spec-new" in content
    assert "spec-finish" in content
    assert "spec test-assist --next" in content

    # Must NOT contain contributor bootstrap commands
    assert "uv pip install -e" not in content
    assert "specops config init" not in content


def test_agent_install_contributor_repo_renders_contributor(tmp_path: Path) -> None:
    # Simulate contributor SpecOps repository
    (tmp_path / "packages" / "spec" / "src" / "spec").mkdir(parents=True)
    (tmp_path / "packages" / "spec" / "src" / "spec" / "__init__.py").touch()
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "ia-spec-ops-engine"\n', encoding="utf-8"
    )
    ProjectGovernance(tmp_path).initialize()

    with pytest.raises(SystemExit) as exc:
        main(["agent", "install", "agents", "--root", str(tmp_path)])
    assert exc.value.code == 0

    gov_md = tmp_path / ".spec/governance.md"
    assert gov_md.exists()
    content = gov_md.read_text(encoding="utf-8")

    # Contains 4-step bootstrap protocol
    assert "Agent Post-Clone Bootstrap Protocol" in content
    assert "./install.sh" in content
    assert "source .venv/bin/activate" in content
    assert "specops config init" in content
    assert "specops doctor && specops audit" in content


def test_agent_install_single_aider(tmp_path: Path) -> None:
    ProjectGovernance(tmp_path).initialize()
    with pytest.raises(SystemExit) as exc:
        main(["agent", "install", "aider", "--root", str(tmp_path)])
    assert exc.value.code == 0

    agents_md = tmp_path / "AGENTS.md"
    assert agents_md.exists()
    assert "@.spec/governance.md" in agents_md.read_text(encoding="utf-8")
    assert not (tmp_path / ".aider.conf.yml").exists()


def test_agent_install_custom_file(tmp_path: Path) -> None:
    ProjectGovernance(tmp_path).initialize()
    custom_target = "docs/CUSTOM_AI.md"
    with pytest.raises(SystemExit) as exc:
        main(["agent", "install", "custom", "--file", custom_target, "--root", str(tmp_path)])
    assert exc.value.code == 0

    custom_file = tmp_path / custom_target
    assert custom_file.exists()
    assert "@.spec/governance.md" in custom_file.read_text(encoding="utf-8")


def test_agent_install_all(tmp_path: Path) -> None:
    ProjectGovernance(tmp_path).initialize()
    with pytest.raises(SystemExit) as exc:
        main(["agent", "install", "all", "--root", str(tmp_path)])
    assert exc.value.code == 0

    assert (tmp_path / "AGENTS.md").exists()
    assert not (tmp_path / "CLAUDE.md").exists()
    assert not (tmp_path / ".cursorrules").exists()
    assert not (tmp_path / ".windsurfrules").exists()
    assert not (tmp_path / ".aider.conf.yml").exists()
    assert not (tmp_path / ".github/copilot-instructions.md").exists()
    assert not (tmp_path / "GEMINI.md").exists()


def test_agent_install_single_copilot(tmp_path: Path) -> None:
    ProjectGovernance(tmp_path).initialize()
    with pytest.raises(SystemExit) as exc:
        main(["agent", "install", "copilot", "--root", str(tmp_path)])
    assert exc.value.code == 0

    agents_md = tmp_path / "AGENTS.md"
    assert agents_md.exists()
    assert "@.spec/governance.md" in agents_md.read_text(encoding="utf-8")
    assert not (tmp_path / ".github/copilot-instructions.md").exists()


def test_agent_install_single_gemini(tmp_path: Path) -> None:
    ProjectGovernance(tmp_path).initialize()
    with pytest.raises(SystemExit) as exc:
        main(["agent", "install", "gemini", "--root", str(tmp_path)])
    assert exc.value.code == 0

    agents_md = tmp_path / "AGENTS.md"
    assert agents_md.exists()
    assert "@.spec/governance.md" in agents_md.read_text(encoding="utf-8")
    assert not (tmp_path / "GEMINI.md").exists()


def test_agent_uninstall_single_aider(tmp_path: Path) -> None:
    ProjectGovernance(tmp_path).initialize()
    with pytest.raises(SystemExit):
        main(["agent", "install", "aider", "--root", str(tmp_path)])
    assert (tmp_path / "AGENTS.md").exists()

    with pytest.raises(SystemExit) as exc:
        main(["agent", "uninstall", "aider", "--apply", "--root", str(tmp_path)])
    assert exc.value.code == 0
    assert not (tmp_path / "AGENTS.md").exists()


def test_agent_install_single_antigravity(tmp_path: Path) -> None:
    ProjectGovernance(tmp_path).initialize()
    with pytest.raises(SystemExit) as exc:
        main(["agent", "install", "antigravity", "--root", str(tmp_path)])
    assert exc.value.code == 0

    agents_md = tmp_path / "AGENTS.md"
    assert agents_md.exists()
    assert "@.spec/governance.md" in agents_md.read_text(encoding="utf-8")
    assert not (tmp_path / "CLAUDE.md").exists()


def test_agent_install_unknown_raises(tmp_path: Path) -> None:
    ProjectGovernance(tmp_path).initialize()
    with pytest.raises(SystemExit) as exc:
        main(["agent", "install", "nonexistent_ai", "--root", str(tmp_path)])
    assert exc.value.code == 1


def test_agent_install_agents_default(tmp_path: Path) -> None:
    ProjectGovernance(tmp_path).initialize()
    with pytest.raises(SystemExit) as exc:
        main(["agent", "install", "--root", str(tmp_path), "-y"])
    assert exc.value.code == 0
    assert (tmp_path / "AGENTS.md").exists()
    assert not (tmp_path / "CLAUDE.md").exists()
