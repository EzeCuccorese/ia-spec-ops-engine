from pathlib import Path

import pytest

from spec.agents import AgentsAdapter, ClaudeAdapter
from spec.cli import main
from spec.core.ownership import FileChangedError, OwnershipManifest
from spec.governance.project import ProjectGovernance


def test_reinstall_preserves_existing_claude(tmp_path: Path) -> None:
    """A01: Given a pre-existing CLAUDE.md with custom user text, installing the Claude adapter

    twice must preserve the user text byte-for-byte, having exactly one <!-- spec:governance --> block.
    """
    ProjectGovernance(tmp_path).initialize()

    custom_user_text = (
        "# User Claude Instructions\n\n"
        "Custom rule 1: Do not modify user text.\n"
        "Custom rule 2: Always follow TDD.\n"
    )
    claude_path = tmp_path / "CLAUDE.md"
    claude_path.write_text(custom_user_text, encoding="utf-8")

    adapter = ClaudeAdapter(tmp_path)

    # First installation
    res1 = adapter.install()
    assert res1.path == ".spec/governance.md"
    content_after_first = claude_path.read_text(encoding="utf-8")

    assert content_after_first.count("<!-- spec:governance -->") == 1
    assert content_after_first.count("<!-- /spec:governance -->") == 1
    assert custom_user_text in content_after_first
    # Spec must not claim whole-file ownership of a file that had pre-existing user content
    assert OwnershipManifest(tmp_path).get("CLAUDE.md") is None

    # Second installation (re-install)
    res2 = adapter.install()
    assert res2.path == ".spec/governance.md"
    content_after_second = claude_path.read_text(encoding="utf-8")

    # Byte-for-byte preservation across reinstalls
    assert content_after_second == content_after_first
    assert content_after_second.count("<!-- spec:governance -->") == 1
    assert content_after_second.count("<!-- /spec:governance -->") == 1
    assert custom_user_text in content_after_second
    assert OwnershipManifest(tmp_path).get("CLAUDE.md") is None


def test_uninstall_preserves_modified_owned_block(tmp_path: Path) -> None:
    """A02: If user edited inside the generated owned block before uninstall, uninstall must

    report an explicit conflict or preserve the file, and NEVER unlink() the file when
    FileChangedError occurs.
    """
    ProjectGovernance(tmp_path).initialize()

    adapter = ClaudeAdapter(tmp_path)
    adapter.install()

    claude_path = tmp_path / "CLAUDE.md"
    assert claude_path.exists()
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
    """A02b: If CLAUDE.md pre-existed (unowned) and user edited inside the spec block, uninstall

    must raise FileChangedError and preserve the file and its modifications intact.
    """
    ProjectGovernance(tmp_path).initialize()

    custom_text = "# Preexisting user instructions\n\nRule 1: Always verify.\n"
    claude_path = tmp_path / "CLAUDE.md"
    claude_path.write_text(custom_text, encoding="utf-8")

    adapter = ClaudeAdapter(tmp_path)
    adapter.install()

    # Verify not owned as whole file
    assert OwnershipManifest(tmp_path).get("CLAUDE.md") is None
    installed_content = claude_path.read_text(encoding="utf-8")
    assert custom_text in installed_content
    assert "<!-- spec:governance -->" in installed_content

    # User modifies inside the block
    modified_content = installed_content.replace(
        "@AGENTS.md", "@AGENTS.md\n# User added note inside block"
    )
    claude_path.write_text(modified_content, encoding="utf-8")

    # Uninstall via Python API must raise FileChangedError
    with pytest.raises(FileChangedError):
        adapter.uninstall(dry_run=False)

    assert claude_path.exists()
    assert claude_path.read_text(encoding="utf-8") == modified_content

    # Uninstall via CLI must exit non-zero and preserve file
    with pytest.raises(SystemExit) as exc:
        main(["agent", "uninstall", "claude", "--apply", "--root", str(tmp_path)])
    assert exc.value.code != 0
    assert claude_path.exists()
    assert claude_path.read_text(encoding="utf-8") == modified_content


def test_all_installs_and_removes_owned_bridges(tmp_path: Path) -> None:
    """A03: Installing 'all' and 'claude' in either order must keep required bridges present

    and uninstall must only remove owned blocks/files.
    """
    # Case 1: install 'all' then 'claude'
    dir1 = tmp_path / "order1"
    dir1.mkdir()
    ProjectGovernance(dir1).initialize()

    # Install 'all'
    AgentsAdapter(dir1).install()
    assert (dir1 / "AGENTS.md").exists()
    assert not (dir1 / "CLAUDE.md").exists()

    # Install 'claude'
    ClaudeAdapter(dir1).install()
    assert (dir1 / "AGENTS.md").exists()
    assert (dir1 / "CLAUDE.md").exists()

    # User adds custom notes to AGENTS.md
    agents_file1 = dir1 / "AGENTS.md"
    user_note = "# Custom Project Agents Note\n"
    agents_file1.write_text(
        f"{user_note}\n{agents_file1.read_text(encoding='utf-8')}", encoding="utf-8"
    )

    # Uninstall claude: removes owned CLAUDE.md file, but AGENTS.md retains user content!
    ClaudeAdapter(dir1).uninstall(dry_run=False)
    assert not (dir1 / "CLAUDE.md").exists()
    assert agents_file1.exists()
    assert user_note in agents_file1.read_text(encoding="utf-8")
    assert "<!-- spec:governance -->" not in agents_file1.read_text(encoding="utf-8")

    # Case 2: install 'claude' then 'all'
    dir2 = tmp_path / "order2"
    dir2.mkdir()
    ProjectGovernance(dir2).initialize()

    # Install 'claude'
    ClaudeAdapter(dir2).install()
    assert (dir2 / "AGENTS.md").exists()
    assert (dir2 / "CLAUDE.md").exists()

    # Install 'all' - keeps required CLAUDE.md bridge present!
    AgentsAdapter(dir2).install()
    assert (dir2 / "AGENTS.md").exists()
    assert (dir2 / "CLAUDE.md").exists()

    # Uninstall only removes owned files
    ClaudeAdapter(dir2).uninstall(dry_run=False)
    assert not (dir2 / "CLAUDE.md").exists()
    assert not (dir2 / "AGENTS.md").exists()


def test_install_failure_keeps_manifest_consistent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A04: A write failure in one stage must not leave partial text appropriation

    or an inconsistent/deceptive manifest.
    """
    ProjectGovernance(tmp_path).initialize()

    custom_text = "# Important Pre-existing Claude Rules\nDo not overwrite or corrupt this!\n"
    claude_path = tmp_path / "CLAUDE.md"
    claude_path.write_text(custom_text, encoding="utf-8")

    adapter = ClaudeAdapter(tmp_path)

    orig_write_text = Path.write_text

    def failing_write_text(self: Path, *args, **kwargs):
        if self.name == "CLAUDE.md":
            raise OSError("Simulated disk error while writing CLAUDE.md")
        return orig_write_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", failing_write_text)
    with pytest.raises(OSError, match="Simulated disk error"):
        adapter.install()

    # Manifest must NOT have a deceptive entry claiming ownership of CLAUDE.md
    manifest = OwnershipManifest(tmp_path)
    assert manifest.get("CLAUDE.md") is None

    # Pre-existing file content must not be corrupted or partially appropriated
    assert claude_path.read_text(encoding="utf-8") == custom_text


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

    (e.g. mock layout) must NOT be guessed as Cucco contributor unless it's genuinely
    the cucco-specops-engine repository (e.g. check for packages/spec/src/spec/__init__.py
    AND root pyproject.toml containing "specops-engine" or similar robust check).
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

    # 2. Genuine cucco-specops-engine contributor project
    contributor_dir = tmp_path / "contributor_project"
    (contributor_dir / "packages" / "spec" / "src" / "spec").mkdir(parents=True)
    (contributor_dir / "packages" / "spec" / "src" / "spec" / "__init__.py").touch()
    (contributor_dir / "pyproject.toml").write_text(
        '[project]\nname = "specops-engine"\n', encoding="utf-8"
    )

    contributor_adapter = AgentsAdapter(contributor_dir)
    rendered_contributor = contributor_adapter.render()

    assert rendered_contributor == AgentsAdapter.render_contributor()
    assert "Agent Post-Clone Bootstrap Protocol" in rendered_contributor
    assert "uv pip install -e" in rendered_contributor
    assert "specops config init" in rendered_contributor
