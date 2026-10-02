from __future__ import annotations

from pathlib import Path

import pytest
import spec.agents as agents_module
from spec.agents import (
    AgentsAdapter,
    get_bundled_skills,
    render_governance,
)
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

    assert not (tmp_path / "CLAUDE.md").exists()

    manifest = OwnershipManifest(tmp_path)
    assert manifest.get("CLAUDE.md") is None
    assert (tmp_path / ".claude" / "skills" / "spec-new" / "SKILL.md").exists()
    assert (tmp_path / ".agents" / "skills" / "spec-new" / "SKILL.md").exists()
    assert manifest.get(".claude/skills/spec-new/SKILL.md") is not None


def test_agent_uninstall_single_claude(tmp_path: Path) -> None:
    ProjectGovernance(tmp_path).initialize()
    with pytest.raises(SystemExit):
        main(["agent", "install", "claude", "--root", str(tmp_path)])
    assert (tmp_path / "AGENTS.md").exists()
    assert (tmp_path / ".claude" / "skills" / "spec-new" / "SKILL.md").exists()

    with pytest.raises(SystemExit) as exc:
        main(["agent", "uninstall", "claude", "--apply", "--root", str(tmp_path)])
    assert exc.value.code == 0
    assert not (tmp_path / "AGENTS.md").exists()
    assert not (tmp_path / "CLAUDE.md").exists()
    assert not (tmp_path / ".claude" / "skills" / "spec-new" / "SKILL.md").exists()


@pytest.mark.parametrize("agent", ["claude", "agents"])
def test_agent_uninstall_removes_claude_md_from_an_earlier_install(
    agent: str, tmp_path: Path, legacy_claude_md
) -> None:
    ProjectGovernance(tmp_path).initialize()
    with pytest.raises(SystemExit):
        main(["agent", "install", agent, "--root", str(tmp_path)])
    claude_md = legacy_claude_md(tmp_path)

    with pytest.raises(SystemExit) as exc:
        main(["agent", "uninstall", agent, "--root", str(tmp_path)])
    assert exc.value.code == 0
    assert claude_md.exists()

    with pytest.raises(SystemExit) as exc:
        main(["agent", "uninstall", agent, "--apply", "--root", str(tmp_path)])
    assert exc.value.code == 0
    assert not claude_md.exists()
    assert OwnershipManifest(tmp_path).get("CLAUDE.md") is None


def test_agent_uninstall_claude_preserves_user_content(tmp_path: Path, legacy_claude_md) -> None:
    ProjectGovernance(tmp_path).initialize()
    with pytest.raises(SystemExit):
        main(["agent", "install", "claude", "--root", str(tmp_path)])

    claude_md = legacy_claude_md(tmp_path)
    custom_content = "# User Claude Instructions\nSome project notes."
    claude_md.write_text(f"{custom_content}\n\n{claude_md.read_text(encoding='utf-8')}")

    with pytest.raises(SystemExit) as exc:
        main(["agent", "uninstall", "claude", "--apply", "--root", str(tmp_path)])
    assert exc.value.code == 0
    assert claude_md.exists()
    remaining = claude_md.read_text(encoding="utf-8")
    assert "<!-- spec:governance -->" not in remaining
    assert custom_content in remaining


def test_agent_install_writes_the_governance_workflow(tmp_path: Path) -> None:
    ProjectGovernance(tmp_path).initialize()
    with pytest.raises(SystemExit) as exc:
        main(["agent", "install", "agents", "--root", str(tmp_path)])
    assert exc.value.code == 0

    gov_md = tmp_path / ".spec/governance.md"
    assert gov_md.exists()
    content = gov_md.read_text(encoding="utf-8")

    assert "Three Laws of TDD" in content
    assert "@s" in content
    assert "spec-new" in content
    assert "spec-finish" in content
    assert "spec test-assist --next" in content
    assert content == render_governance()


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
    assert exc.value.code == 2


def test_agent_install_agents_default(tmp_path: Path) -> None:
    ProjectGovernance(tmp_path).initialize()
    with pytest.raises(SystemExit) as exc:
        main(["agent", "install", "--root", str(tmp_path), "-y"])
    assert exc.value.code == 0
    assert (tmp_path / "AGENTS.md").exists()
    assert not (tmp_path / "CLAUDE.md").exists()


def test_agent_install_single_codex(tmp_path: Path) -> None:
    ProjectGovernance(tmp_path).initialize()
    with pytest.raises(SystemExit) as exc:
        main(["agent", "install", "codex", "--root", str(tmp_path)])
    assert exc.value.code == 0

    assert (tmp_path / ".codex" / "skills" / "spec-new" / "SKILL.md").exists()
    assert (tmp_path / ".agents" / "skills" / "spec-new" / "SKILL.md").exists()


def test_get_bundled_skills_via_importlib_resources_partial_names(monkeypatch) -> None:
    """Exercise the for-loop continue path when a resource name has no SKILL.md."""

    class FakeFile:
        def __init__(self, exists: bool, text: str = "") -> None:
            self._exists = exists
            self._text = text

        def is_file(self) -> bool:
            return self._exists

        def read_text(self, encoding: str = "utf-8") -> str:
            return self._text

    class FakeSkillsDir:
        def joinpath(self, name: str, filename: str) -> FakeFile:
            exists = name == "spec-new"
            return FakeFile(exists, "content" if exists else "")

    class FakeBase:
        def joinpath(self, sub: str) -> FakeSkillsDir:
            assert sub == "skills"
            return FakeSkillsDir()

    def fake_files(package: str) -> FakeBase:
        assert package == "spec"
        return FakeBase()

    monkeypatch.setattr("importlib.resources.files", fake_files)
    result = get_bundled_skills()
    assert result == {"spec-new": "content"}


def test_get_bundled_skills_falls_back_to_filesystem_on_resource_error(monkeypatch) -> None:
    """Exercise the except branch and the filesystem fallback lookup."""

    def raising_files(package: str) -> None:
        raise ModuleNotFoundError("no resources")

    monkeypatch.setattr("importlib.resources.files", raising_files)
    result = get_bundled_skills()
    assert "spec-new" in result
    assert "spec-plan" in result
    assert "spec-verify" in result
    assert "spec-finish" in result


def test_agent_uninstall_skill_dir_not_empty_is_preserved(tmp_path: Path) -> None:
    ProjectGovernance(tmp_path).initialize()
    with pytest.raises(SystemExit):
        main(["agent", "install", "agents", "--root", str(tmp_path)])

    skill_dir = tmp_path / ".agents" / "skills" / "spec-new"
    assert skill_dir.exists()
    (skill_dir / "extra.txt").write_text("leftover", encoding="utf-8")

    with pytest.raises(SystemExit) as exc:
        main(["agent", "uninstall", "agents", "--apply", "--root", str(tmp_path)])
    assert exc.value.code == 0

    assert skill_dir.exists()
    assert (skill_dir / "extra.txt").exists()
    assert not (skill_dir / "SKILL.md").exists()


def test_agent_uninstall_claude_without_prior_install(tmp_path: Path) -> None:
    """Neither the governance file nor CLAUDE.md was ever installed."""
    ProjectGovernance(tmp_path).initialize()
    with pytest.raises(SystemExit) as exc:
        main(["agent", "uninstall", "claude", "--apply", "--root", str(tmp_path)])
    assert exc.value.code == 0
    assert not (tmp_path / "CLAUDE.md").exists()


def test_agent_uninstall_claude_with_stale_manifest_record(
    tmp_path: Path, legacy_claude_md
) -> None:
    """CLAUDE.md was removed manually but the manifest still owns it."""
    ProjectGovernance(tmp_path).initialize()
    with pytest.raises(SystemExit):
        main(["agent", "install", "claude", "--root", str(tmp_path)])

    claude_md = legacy_claude_md(tmp_path)
    assert OwnershipManifest(tmp_path).get("CLAUDE.md") is not None
    claude_md.unlink()

    with pytest.raises(SystemExit) as exc:
        main(["agent", "uninstall", "claude", "--apply", "--root", str(tmp_path)])
    assert exc.value.code == 0
    assert OwnershipManifest(tmp_path).get("CLAUDE.md") is None


def test_agent_uninstall_agents_markers_absent_leaves_agents_md(tmp_path: Path) -> None:
    """AGENTS.md exists but was never wrapped with the governance markers."""
    agents_md = tmp_path / "AGENTS.md"
    agents_md.write_text("# Custom project notes\n", encoding="utf-8")

    with pytest.raises(SystemExit) as exc:
        main(["agent", "uninstall", "aider", "--apply", "--root", str(tmp_path)])
    assert exc.value.code == 0
    assert agents_md.read_text(encoding="utf-8") == "# Custom project notes\n"


def test_uninstall_claude_pointer_without_markers_returns_no_op(tmp_path: Path) -> None:
    """CLAUDE.md exists with unrelated content (no governance markers)."""
    claude_md = tmp_path / "CLAUDE.md"
    claude_md.write_text("# Unrelated Claude notes\n", encoding="utf-8")
    adapter = AgentsAdapter(tmp_path, agent="claude")

    result = adapter.uninstall_claude_pointer(dry_run=False)
    assert result.deleted is False
    assert result.would_delete is False
    assert claude_md.read_text(encoding="utf-8") == "# Unrelated Claude notes\n"


def test_uninstall_claude_pointer_unowned_block_only_content(tmp_path: Path) -> None:
    """CLAUDE.md manually seeded with only the governance block, not owned."""
    claude_md = tmp_path / "CLAUDE.md"
    claude_md.write_text(
        "<!-- spec:governance -->\n@AGENTS.md\n<!-- /spec:governance -->\n", encoding="utf-8"
    )
    adapter = AgentsAdapter(tmp_path, agent="claude")
    assert OwnershipManifest(tmp_path).get("CLAUDE.md") is None

    result = adapter.uninstall_claude_pointer(dry_run=False)
    assert result.deleted is False
    assert result.would_delete is False
    assert claude_md.read_text(encoding="utf-8") == ""


def test_uninstall_agents_md_present_without_markers_when_apply(tmp_path: Path) -> None:
    """uninstall() with an existing AGENTS.md lacking governance markers."""
    (tmp_path / "AGENTS.md").write_text("# Notes only\n", encoding="utf-8")
    adapter = AgentsAdapter(tmp_path, agent="aider")

    result = adapter.uninstall(dry_run=False)
    assert result.deleted is False
    assert (tmp_path / "AGENTS.md").read_text(encoding="utf-8") == "# Notes only\n"


def test_get_bundled_skills_fallback_skips_missing_names(tmp_path: Path, monkeypatch) -> None:
    """The filesystem fallback for-loop continues past names with no SKILL.md."""
    fake_pkg_dir = tmp_path / "fake_pkg"
    skills_dir = fake_pkg_dir / "skills" / "spec-new"
    skills_dir.mkdir(parents=True)
    (skills_dir / "SKILL.md").write_text("content", encoding="utf-8")

    def raising_files(package: str) -> None:
        raise ModuleNotFoundError("no resources")

    monkeypatch.setattr("importlib.resources.files", raising_files)
    monkeypatch.setattr(agents_module, "__file__", str(fake_pkg_dir / "agents.py"))
    result = get_bundled_skills()
    assert result == {"spec-new": "content"}


def test_agent_uninstall_skills_dry_run_leaves_files_untouched(tmp_path: Path) -> None:
    ProjectGovernance(tmp_path).initialize()
    with pytest.raises(SystemExit):
        main(["agent", "install", "agents", "--root", str(tmp_path)])
    skill_md = tmp_path / ".agents" / "skills" / "spec-new" / "SKILL.md"
    assert skill_md.exists()

    with pytest.raises(SystemExit) as exc:
        main(["agent", "uninstall", "agents", "--root", str(tmp_path)])
    assert exc.value.code == 0
    assert skill_md.exists()


def test_agent_install_agents_twice_is_idempotent(tmp_path: Path) -> None:
    ProjectGovernance(tmp_path).initialize()
    with pytest.raises(SystemExit):
        main(["agent", "install", "agents", "--root", str(tmp_path)])
    with pytest.raises(SystemExit) as exc:
        main(["agent", "install", "agents", "--root", str(tmp_path)])
    assert exc.value.code == 0

    content = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    assert content.count("<!-- spec:governance -->") == 1


def test_agent_uninstall_agents_md_preserves_user_content(tmp_path: Path) -> None:
    ProjectGovernance(tmp_path).initialize()
    with pytest.raises(SystemExit):
        main(["agent", "install", "agents", "--root", str(tmp_path)])

    agents_md = tmp_path / "AGENTS.md"
    custom_content = "# Project Notes\nKeep this line."
    agents_md.write_text(f"{custom_content}\n\n{agents_md.read_text(encoding='utf-8')}")

    with pytest.raises(SystemExit) as exc:
        main(["agent", "uninstall", "agents", "--apply", "--root", str(tmp_path)])
    assert exc.value.code == 0
    remaining = agents_md.read_text(encoding="utf-8")
    assert "<!-- spec:governance -->" not in remaining
    assert custom_content in remaining


def test_uninstall_claude_pointer_dry_run_unowned_block_only_content(
    tmp_path: Path,
) -> None:
    """Dry-run uninstall of an unowned block-only CLAUDE.md makes no changes."""
    claude_md = tmp_path / "CLAUDE.md"
    original = "<!-- spec:governance -->\n@AGENTS.md\n<!-- /spec:governance -->\n"
    claude_md.write_text(original, encoding="utf-8")
    adapter = AgentsAdapter(tmp_path, agent="claude")

    result = adapter.uninstall_claude_pointer(dry_run=True)
    assert result.deleted is False
    assert result.would_delete is False
    assert claude_md.read_text(encoding="utf-8") == original


def test_uninstall_claude_pointer_dry_run_preserves_user_content(
    tmp_path: Path, legacy_claude_md
) -> None:
    """Dry-run uninstall with owned CLAUDE.md plus user edits changes nothing."""
    ProjectGovernance(tmp_path).initialize()
    with pytest.raises(SystemExit):
        main(["agent", "install", "claude", "--root", str(tmp_path)])

    claude_md = legacy_claude_md(tmp_path)
    custom_content = "# Kept during dry run"
    original = f"{custom_content}\n\n{claude_md.read_text(encoding='utf-8')}"
    claude_md.write_text(original, encoding="utf-8")

    with pytest.raises(SystemExit) as exc:
        main(["agent", "uninstall", "claude", "--root", str(tmp_path)])
    assert exc.value.code == 0
    assert claude_md.read_text(encoding="utf-8") == original


def test_uninstall_claude_pointer_unowned_block_with_user_content(tmp_path: Path) -> None:
    """Unowned CLAUDE.md with block + user content: uninstall keeps user text."""
    claude_md = tmp_path / "CLAUDE.md"
    custom_content = "# Manually added notes"
    claude_md.write_text(
        f"{custom_content}\n<!-- spec:governance -->\n@AGENTS.md\n<!-- /spec:governance -->\n",
        encoding="utf-8",
    )
    adapter = AgentsAdapter(tmp_path, agent="claude")
    assert OwnershipManifest(tmp_path).get("CLAUDE.md") is None

    result = adapter.uninstall_claude_pointer(dry_run=False)
    assert result.deleted is False
    assert result.would_delete is False
    content = claude_md.read_text(encoding="utf-8")
    assert custom_content in content
    assert "<!-- spec:governance -->" not in content
    assert OwnershipManifest(tmp_path).get("CLAUDE.md") is None


def test_governance_spec_new_runs_preflight_like_the_skill() -> None:
    skill = get_bundled_skills()["spec-new"]
    line = next(row for row in render_governance().splitlines() if row.startswith("- spec-new"))
    assert 'spec preflight "<name>"' in line
    assert 'spec new "<name>" only without preflight' in line
    assert line.index("spec preflight") < line.index("spec new")
    assert 'spec preflight "<feature-name>"' in skill


def test_uninstall_custom_file_removes_unedited_legacy_claude_block(tmp_path: Path) -> None:
    """An earlier `install claude` wrote `@AGENTS.md`; uninstalling a custom target must not
    mistake that unedited block for a user edit."""
    claude_md = tmp_path / "CLAUDE.md"
    claude_md.write_text(
        "# Notes\n<!-- spec:governance -->\n@AGENTS.md\n<!-- /spec:governance -->\n",
        encoding="utf-8",
    )

    with pytest.raises(SystemExit) as exc:
        main(
            [
                "agent",
                "uninstall",
                "custom",
                "--file",
                "docs/AI.md",
                "--apply",
                "--root",
                str(tmp_path),
            ]
        )
    assert exc.value.code == 0
    assert claude_md.read_text(encoding="utf-8") == "# Notes\n"
