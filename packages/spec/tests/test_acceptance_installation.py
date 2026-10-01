from pathlib import Path

import pytest
from spec.agents import AgentsAdapter
from spec.cli import main
from spec.core.ownership import FileChangedError, OwnershipManifest
from spec.governance.project import ProjectGovernance


def test_install_never_touches_claude_md(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A01: AGENTS.md is the only instructions file. Installing the Claude adapter twice over a
    pre-existing CLAUDE.md leaves it byte-for-byte untouched and unowned, and never writes it.
    """
    ProjectGovernance(tmp_path).initialize()

    custom_user_text = "# User Claude Instructions\n\nCustom rule 1: Do not modify user text.\n"
    claude_path = tmp_path / "CLAUDE.md"
    claude_path.write_text(custom_user_text, encoding="utf-8")

    orig_write_text = Path.write_text

    def guarded_write_text(self: Path, *args, **kwargs):
        if self.name == "CLAUDE.md":
            raise AssertionError("install must not write CLAUDE.md")
        return orig_write_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", guarded_write_text)
    adapter = AgentsAdapter(tmp_path, agent="claude")
    assert adapter.install().path == ".spec/governance.md"
    assert adapter.install().path == ".spec/governance.md"

    assert claude_path.read_text(encoding="utf-8") == custom_user_text
    assert OwnershipManifest(tmp_path).get("CLAUDE.md") is None
    assert "<!-- spec:governance -->" in (tmp_path / "AGENTS.md").read_text(encoding="utf-8")


def test_uninstall_preserves_modified_owned_block(tmp_path: Path, legacy_claude_md) -> None:
    """A02: If user edited inside the owned block of a CLAUDE.md written by an earlier install,
    uninstall must report an explicit conflict and NEVER unlink() the file.
    """
    ProjectGovernance(tmp_path).initialize()

    adapter = AgentsAdapter(tmp_path, agent="claude")
    adapter.install()
    claude_path = legacy_claude_md(tmp_path)
    assert OwnershipManifest(tmp_path).get("CLAUDE.md") is not None

    # User modifies content inside the generated owned block
    original_content = claude_path.read_text(encoding="utf-8")
    modified_content = original_content.replace(
        "@AGENTS.md", "@AGENTS.md\n# User modified this owned pointer block"
    )
    claude_path.write_text(modified_content, encoding="utf-8")

    # Uninstall via Python API: must raise FileChangedError and NEVER unlink the file
    with pytest.raises(FileChangedError):
        adapter.uninstall(dry_run=False)

    assert claude_path.exists(), "CLAUDE.md must NEVER be unlinked when FileChangedError occurs"
    assert claude_path.read_text(encoding="utf-8") == modified_content

    # Uninstall via CLI: must exit with error / conflict and NEVER unlink the file
    with pytest.raises(SystemExit) as exc:
        main(["agent", "uninstall", "claude", "--apply", "--root", str(tmp_path)])
    assert exc.value.code != 0
    assert claude_path.exists(), "CLAUDE.md must NEVER be unlinked by CLI on conflict"
    assert claude_path.read_text(encoding="utf-8") == modified_content


def test_uninstall_preserves_modified_block_in_preexisting_file(tmp_path: Path) -> None:
    """A02b: If an unowned CLAUDE.md holds a spec block the user edited, uninstall must raise
    FileChangedError and preserve the file and its modifications intact.
    """
    ProjectGovernance(tmp_path).initialize()

    claude_path = tmp_path / "CLAUDE.md"
    modified_content = (
        "# Preexisting user instructions\n\n"
        "<!-- spec:governance -->\n@AGENTS.md\n# User added note inside block\n"
        "<!-- /spec:governance -->\n"
    )
    claude_path.write_text(modified_content, encoding="utf-8")
    assert OwnershipManifest(tmp_path).get("CLAUDE.md") is None

    adapter = AgentsAdapter(tmp_path, agent="claude")
    with pytest.raises(FileChangedError):
        adapter.uninstall(dry_run=False)
    assert claude_path.read_text(encoding="utf-8") == modified_content

    # Uninstall via CLI must exit non-zero and preserve file
    with pytest.raises(SystemExit) as exc:
        main(["agent", "uninstall", "claude", "--apply", "--root", str(tmp_path)])
    assert exc.value.code != 0
    assert claude_path.read_text(encoding="utf-8") == modified_content


def test_agents_and_claude_share_agents_md_in_either_order(tmp_path: Path) -> None:
    """A03: Installing 'agents' and 'claude' in either order keeps one AGENTS.md block, never
    creates CLAUDE.md, and uninstall only removes owned blocks/files.
    """
    for order in (("agents", "claude"), ("claude", "agents")):
        root = tmp_path / "-".join(order)
        root.mkdir()
        ProjectGovernance(root).initialize()
        for agent in order:
            AgentsAdapter(root, agent=agent).install()
        agents_file = root / "AGENTS.md"
        assert agents_file.read_text(encoding="utf-8").count("<!-- spec:governance -->") == 1
        assert not (root / "CLAUDE.md").exists()

        user_note = "# Custom Project Agents Note\n"
        agents_file.write_text(
            f"{user_note}\n{agents_file.read_text(encoding='utf-8')}", encoding="utf-8"
        )

        AgentsAdapter(root, agent="claude").uninstall(dry_run=False)
        assert user_note in agents_file.read_text(encoding="utf-8")
        assert "<!-- spec:governance -->" not in agents_file.read_text(encoding="utf-8")
        assert not (root / ".claude" / "skills").exists()


def test_module_blocks_coexist(tmp_path: Path) -> None:
    """A05: When both governance rules block and spec governance block exist with user

    content/sentinels in between, uninstalling one must preserve the other and keep the sentinels.
    """
    ProjectGovernance(tmp_path).initialize()

    agents_path = tmp_path / "AGENTS.md"
    sentinel_start = "# Sentinel Start Header\nProject Overview"
    sentinel_middle = "# Sentinel Middle Notes\nTeam conventions and notes"
    sentinel_end = "# Sentinel End Footer\nContact details and references"

    rules_body = "1. Follow Clean Architecture.\n2. Apply hexagonal layering."
    rules_block = f"<!-- rules:start -->\n{rules_body}\n<!-- rules:end -->"

    spec_block = "<!-- spec:governance -->\n@.spec/governance.md\n<!-- /spec:governance -->\n"

    # Assemble file with both blocks and 3 sentinels
    content = (
        f"{sentinel_start}\n\n"
        f"{rules_block}\n\n"
        f"{sentinel_middle}\n\n"
        f"{spec_block}\n\n"
        f"{sentinel_end}\n"
    )
    agents_path.write_text(content, encoding="utf-8")

    # Step 1: Uninstall Spec governance
    adapter = AgentsAdapter(tmp_path)
    adapter.uninstall(dry_run=False)

    assert agents_path.exists()
    content_after_spec_uninstall = agents_path.read_text(encoding="utf-8")

    # Spec governance block removed
    assert "<!-- spec:governance -->" not in content_after_spec_uninstall
    # Rules block preserved
    assert "<!-- rules:start -->" in content_after_spec_uninstall
    assert "<!-- rules:end -->" in content_after_spec_uninstall
    assert "Clean Architecture" in content_after_spec_uninstall
    # All sentinels preserved
    assert sentinel_start in content_after_spec_uninstall
    assert sentinel_middle in content_after_spec_uninstall
    assert sentinel_end in content_after_spec_uninstall

    # Step 2: Uninstall rules block
    import re

    cleaned_after_rules = re.sub(
        r"<!-- rules:start -->.*?<!-- rules:end -->\n?",
        "",
        content_after_spec_uninstall,
        flags=re.DOTALL,
    )
    agents_path.write_text(cleaned_after_rules, encoding="utf-8")

    final_content = agents_path.read_text(encoding="utf-8")
    assert "<!-- rules:start -->" not in final_content
    assert "<!-- spec:governance -->" not in final_content
    assert sentinel_start in final_content
    assert sentinel_middle in final_content
    assert sentinel_end in final_content


def test_consumer_role_is_not_layout_guess(tmp_path: Path) -> None:
    """A06: A third-party consumer project that happens to have a folder packages/spec

    (e.g. mock layout) must NOT be guessed as an ia-spec-ops-engine contributor unless it's genuinely
    the ia-spec-ops-engine repository (e.g. check for packages/spec/src/spec/__init__.py
    AND root pyproject.toml containing "ia-spec-ops-engine" or similar robust check).
    """
    # 1. Consumer project with packages/spec directory (mock layout)
    consumer_dir = tmp_path / "consumer_project"
    (consumer_dir / "packages" / "spec").mkdir(parents=True)
    (consumer_dir / "packages" / "spec" / "README.md").write_text("# Mock spec", encoding="utf-8")
    (consumer_dir / "pyproject.toml").write_text(
        '[project]\nname = "consumer-app"\n', encoding="utf-8"
    )

    consumer_adapter = AgentsAdapter(consumer_dir)
    rendered_consumer = consumer_adapter.render()

    assert rendered_consumer == AgentsAdapter.render_consumer()
    assert "Three Laws of TDD" in rendered_consumer
    assert "uv pip install -e" not in rendered_consumer
    assert "Agent Post-Clone Bootstrap Protocol" not in rendered_consumer
    assert "specops config init" not in rendered_consumer

    # 2. Genuine ia-spec-ops-engine contributor project
    contributor_dir = tmp_path / "contributor_project"
    (contributor_dir / "packages" / "spec" / "src" / "spec").mkdir(parents=True)
    (contributor_dir / "packages" / "spec" / "src" / "spec" / "__init__.py").touch()
    (contributor_dir / "pyproject.toml").write_text(
        '[project]\nname = "ia-spec-ops-engine"\n', encoding="utf-8"
    )

    contributor_adapter = AgentsAdapter(contributor_dir)
    rendered_contributor = contributor_adapter.render()

    assert rendered_contributor == AgentsAdapter.render_contributor()
    assert "Agent Post-Clone Bootstrap Protocol" in rendered_contributor
    assert "./install.sh" in rendered_contributor
    assert "source .venv/bin/activate" in rendered_contributor
    assert "specops config init" in rendered_contributor
