"""Personal preference pack tests: installed at user scope as symlinks for each agent."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from ai_governance import personal
from ai_governance.install.installer import (
    _is_personal_entry,
    _is_personal_target,
    global_ledger,
    install_user,
    uninstall_user,
)


@pytest.fixture
def home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setenv("AI_GOVERNANCE_STATE_DIR", str(home / "state"))
    monkeypatch.setenv("AI_GOVERNANCE_CONFIG_DIR", str(home / ".config" / "ai-governance"))
    monkeypatch.delenv("CODEX_HOME", raising=False)
    monkeypatch.delenv("AI_GOVERNANCE_BIN_DIR", raising=False)
    return home


@pytest.fixture(autouse=True)
def personal_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    root = tmp_path / "personal"
    rules = root / "rules"
    rules.mkdir(parents=True)
    (rules / "voice.md").write_text("---\ntrigger: always_on\n---\n# Voice\nBe concise.\n")
    (rules / "style.md").write_text("# Style\nPrefer explicit arguments.\n")
    monkeypatch.setenv("AI_GOVERNANCE_PERSONAL_DIR", str(root))
    return root


def _claude_rules(home: Path) -> list[str]:
    return sorted(p.name for p in (home / ".claude" / "rules").glob("ai-governance-personal-*"))


def _gemini_rules(home: Path) -> list[str]:
    return sorted(
        p.name for p in (home / ".gemini" / "config" / "rules").glob("ai-governance-personal-*")
    )


def _codex_rules(home: Path) -> list[str]:
    return sorted(p.name for p in (home / ".codex" / "ai-governance" / "personal").glob("*.md"))


def test_personal_root_resolution(monkeypatch: pytest.MonkeyPatch, home: Path) -> None:
    monkeypatch.delenv("AI_GOVERNANCE_PERSONAL_DIR", raising=False)
    assert personal.personal_root() == home / ".config" / "ai-governance" / "personal"

    monkeypatch.setenv("AI_GOVERNANCE_PERSONAL_DIR", "/custom/personal")
    assert personal.personal_root() == Path("/custom/personal")


def test_personal_pack_exposes_rules(personal_root: Path) -> None:
    rules = personal.rules()
    assert [r.name for r in rules] == ["style", "voice"]
    assert "explicit arguments" in rules[0].content
    assert rules[0].path == (personal_root / "rules" / "style.md").resolve()


def test_missing_personal_folder_lists_no_rules(tmp_path: Path) -> None:
    missing = tmp_path / "missing"
    assert personal.rules(missing) == []


def test_personal_rules_ignores_directory_with_md_extension(tmp_path: Path) -> None:
    rules_dir = tmp_path / "rules"
    rules_dir.mkdir()
    (rules_dir / "valid.md").write_text("# Valid\n", encoding="utf-8")
    (rules_dir / "subfolder.md").mkdir()

    loaded = personal.rules(tmp_path)
    assert [r.name for r in loaded] == ["valid"]


def test_user_install_links_personal_rules_for_all_agents(home: Path, personal_root: Path) -> None:
    report = install_user(["claude", "antigravity", "codex"])

    assert _claude_rules(home) == [
        "ai-governance-personal-style.md",
        "ai-governance-personal-voice.md",
    ]
    claude_link = home / ".claude" / "rules" / "ai-governance-personal-voice.md"
    assert claude_link.is_symlink()
    assert Path(os.readlink(claude_link)) == (personal_root / "rules" / "voice.md").resolve()

    assert _gemini_rules(home) == [
        "ai-governance-personal-style.md",
        "ai-governance-personal-voice.md",
    ]
    gemini_link = home / ".gemini" / "config" / "rules" / "ai-governance-personal-voice.md"
    assert gemini_link.is_symlink()
    assert Path(os.readlink(gemini_link)) == (personal_root / "rules" / "voice.md").resolve()
    assert "trigger: always_on" in gemini_link.read_text()

    assert _codex_rules(home) == ["style.md", "voice.md"]
    codex_link = home / ".codex" / "ai-governance" / "personal" / "voice.md"
    assert codex_link.is_symlink()
    assert Path(os.readlink(codex_link)) == (personal_root / "rules" / "voice.md").resolve()

    codex_agents = (home / ".codex" / "AGENTS.md").read_text()
    assert "once per session read every file in `always/` and `personal/`" in codex_agents
    assert "read `company/index.md`" in codex_agents

    assert not any("Personal directory" in w for w in report.warnings)


def test_user_install_personal_rules_is_idempotent(home: Path) -> None:
    install_user(["claude", "antigravity", "codex"])
    second = install_user(["claude", "antigravity", "codex"])

    personal_changes = [
        (action, path)
        for action, path in second.changes
        if "personal" in path and action != "unchanged"
    ]
    assert personal_changes == []


def test_uninstall_removes_personal_rules(home: Path) -> None:
    install_user(["claude", "antigravity", "codex"])
    assert _claude_rules(home)
    assert _gemini_rules(home)
    assert _codex_rules(home)

    uninstall_user(["claude"])
    assert _claude_rules(home) == []
    assert _gemini_rules(home)
    assert _codex_rules(home)

    uninstall_user(["codex"])
    assert _codex_rules(home) == []
    assert _gemini_rules(home)

    uninstall_user(["antigravity"])
    assert _gemini_rules(home) == []


def test_missing_personal_dir_keeps_links_and_warns(
    home: Path, personal_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_user(["claude", "antigravity", "codex"])
    assert _claude_rules(home)
    assert _gemini_rules(home)
    assert _codex_rules(home)

    missing = personal_root.parent / "nonexistent-personal"
    monkeypatch.setenv("AI_GOVERNANCE_PERSONAL_DIR", str(missing))

    report = install_user(["claude", "antigravity", "codex"])

    assert _claude_rules(home) == [
        "ai-governance-personal-style.md",
        "ai-governance-personal-voice.md",
    ]
    assert _gemini_rules(home) == [
        "ai-governance-personal-style.md",
        "ai-governance-personal-voice.md",
    ]
    assert _codex_rules(home) == ["style.md", "voice.md"]
    assert any("Personal directory" in w and "does not exist" in w for w in report.warnings)


def test_missing_personal_dir_without_prior_entries_stays_silent(
    home: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    missing = tmp_path / "nonexistent-personal"
    monkeypatch.setenv("AI_GOVERNANCE_PERSONAL_DIR", str(missing))

    report = install_user(["claude", "antigravity", "codex"])

    assert not any("Personal directory" in w for w in report.warnings)
    assert _claude_rules(home) == []
    assert _gemini_rules(home) == []
    assert _codex_rules(home) == []


def test_empty_personal_rules_folder_removes_links_without_warning(
    home: Path, personal_root: Path
) -> None:
    install_user(["claude"])
    assert _claude_rules(home)

    for p in (personal_root / "rules").glob("*.md"):
        p.unlink()

    report = install_user(["claude"])
    assert _claude_rules(home) == []
    assert not any("Personal directory" in w for w in report.warnings)


def test_uninstall_removes_personal_rules_even_when_dir_missing(
    home: Path, personal_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_user(["claude", "antigravity"])
    assert _claude_rules(home)
    assert _gemini_rules(home)

    missing = personal_root.parent / "nonexistent-personal"
    monkeypatch.setenv("AI_GOVERNANCE_PERSONAL_DIR", str(missing))

    uninstall_user(["claude"])
    assert _claude_rules(home) == []
    assert _gemini_rules(home)


def test_is_personal_target() -> None:
    assert not _is_personal_target("")
    assert _is_personal_target("/some/path/personal/rules/foo.md")
    assert _is_personal_target("/custom/rules/bar.md")


@pytest.mark.parametrize(
    ("agent", "path", "target"),
    [
        ("unknown", "p", "t"),
        ("codex", ".codex/ai-governance/company/foo.md", "personal/rules/foo.md"),
        ("codex", ".codex/ai-governance/personal/foo.txt", "personal/rules/foo.txt"),
        ("claude", ".claude/other/ai-governance-personal-voice.md", "personal/rules/voice.md"),
        ("claude", ".claude/rules/ai-governance-voice.md", "personal/rules/voice.md"),
        ("claude", ".claude/rules/ai-governance-personal-.md", "personal/rules/voice.md"),
    ],
)
def test_is_personal_entry_edge_cases(home: Path, agent: str, path: str, target: str) -> None:
    ledger = global_ledger()
    assert not _is_personal_entry(ledger, {"kind": "file"})
    entry = {
        "kind": "link",
        "agent": agent,
        "path": str(home / path),
        "target": str(home / target),
    }
    assert not _is_personal_entry(ledger, entry)


def test_corporate_entry_rejects_personal_link(home: Path) -> None:
    from ai_governance.install.installer import _is_corporate_entry

    ledger = global_ledger()
    entry = {
        "kind": "link",
        "agent": "claude",
        "path": str(home / ".claude" / "rules" / "ai-governance-personal-voice.md"),
        "target": str(home / "personal" / "rules" / "voice.md"),
    }
    assert not _is_corporate_entry(ledger, entry)


def test_ensure_personal_dir_creates_readme(tmp_path: Path) -> None:
    target = tmp_path / "custom_personal"
    rules_dir = personal.ensure_personal_dir(target)
    assert rules_dir.is_dir()
    readme = rules_dir / "README.md"
    assert readme.is_file()
    assert "Personal Rules" in readme.read_text(encoding="utf-8")
    assert "trigger: always_on" in readme.read_text(encoding="utf-8")


def test_create_rule_injects_frontmatter_default(tmp_path: Path) -> None:
    target = tmp_path / "personal_test"
    path = personal.create_rule("custom", "# Custom Rule\nContent\n", root=target)
    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\ntrigger: always_on\n---\n")
    assert "# Custom Rule" in text


def test_personal_rules_ignores_readme_and_warns_on_missing_frontmatter(
    personal_root: Path,
) -> None:
    rules_dir = personal_root / "rules"
    (rules_dir / "README.md").write_text("# Readme", encoding="utf-8")
    with pytest.warns(UserWarning, match="style.md.*missing YAML front matter"):
        loaded = personal.rules(personal_root)
    names = [r.name for r in loaded]
    assert "README" not in names
    assert names == ["style", "voice"]


def test_doctor_personal_checks(home: Path, personal_root: Path) -> None:
    from ai_governance.install import doctor

    install_user(["claude"])
    rows = doctor.check(None)
    assert any(c == "user:personal" and s == doctor.OK for c, s, _ in rows)

    link = home / ".claude" / "rules" / "ai-governance-personal-voice.md"
    link.unlink()
    rows = doctor.check(None)
    assert any(
        c == "user:personal" and s == doctor.FAIL and "missing personal rule link" in d
        for c, s, d in rows
    )


def test_doctor_personal_empty_and_missing_dir(home: Path, personal_root: Path) -> None:
    import shutil

    from ai_governance.install import doctor

    install_user(["claude"])
    for md in list((personal_root / "rules").glob("*.md")):
        md.unlink()
    (personal_root / "rules" / "README.md").write_text("# Readme")
    rows = doctor.check(None)
    assert any(c == "user:personal" and s == doctor.FAIL and "empty" in d for c, s, d in rows)

    shutil.rmtree(personal_root / "rules")
    rows = doctor.check(None)
    assert any(c == "user:personal" and s == doctor.FAIL and "missing" in d for c, s, d in rows)


def test_doctor_antigravity_missing_trigger_check(home: Path, personal_root: Path) -> None:
    from ai_governance.install import doctor

    install_user(["antigravity"])
    rows = doctor.check(None)
    assert any(
        c == "user:antigravity" and s == doctor.FAIL and "ai-governance-personal-style.md" in d
        for c, s, d in rows
    )


def test_frontmatter_utilities() -> None:
    from ai_governance.frontmatter import check_frontmatter, ensure_frontmatter

    # Missing frontmatter
    res = check_frontmatter("# Just header\n")
    assert not res.valid and res.trigger is None

    # Invalid trigger
    res = check_frontmatter("---\ntrigger: invalid_value\n---\n# Header\n")
    assert not res.valid and res.trigger == "invalid_value"

    # Frontmatter without trigger
    res = check_frontmatter("---\npaths:\n  - '**/*.py'\n---\n# Header\n")
    assert not res.valid and res.trigger is None

    # Valid trigger
    res = check_frontmatter("---\ntrigger: glob\npaths:\n  - '**/*.py'\n---\n# Header\n")
    assert res.valid and res.trigger == "glob"

    # ensure_frontmatter on already valid content
    valid_content = "---\ntrigger: always_on\n---\n# Content\n"
    assert ensure_frontmatter(valid_content) == valid_content

    # ensure_frontmatter when frontmatter exists with invalid trigger
    replaced = ensure_frontmatter("---\ntrigger: custom\nfoo: bar\n---\nBody\n")
    assert check_frontmatter(replaced).valid
    assert check_frontmatter(replaced).trigger == "always_on"

    # ensure_frontmatter when frontmatter exists without trigger
    added = ensure_frontmatter("---\npaths:\n  - '**/*.py'\n---\nBody\n", default_trigger="glob")
    assert check_frontmatter(added).valid
    assert check_frontmatter(added).trigger == "glob"

    # ensure_frontmatter when no frontmatter exists
    new_fm = ensure_frontmatter("# Simple body\n")
    assert check_frontmatter(new_fm).valid
    assert check_frontmatter(new_fm).trigger == "always_on"


def test_personal_add_without_from(home: Path, personal_root: Path) -> None:
    install_user(["claude", "antigravity"])
    code = personal.main(["add", "concise"])
    assert code == 0

    rule_path = personal_root / "rules" / "concise.md"
    assert rule_path.is_file()
    content = rule_path.read_text(encoding="utf-8")
    assert content.startswith("---\ntrigger: always_on\n---\n")
    assert "# Concise" in content

    claude_link = home / ".claude" / "rules" / "ai-governance-personal-concise.md"
    assert claude_link.is_symlink()
    assert claude_link.resolve() == rule_path.resolve()

    gemini_link = home / ".gemini" / "config" / "rules" / "ai-governance-personal-concise.md"
    assert gemini_link.is_symlink()
    assert gemini_link.resolve() == rule_path.resolve()


def test_personal_add_with_from_and_title(home: Path, personal_root: Path, tmp_path: Path) -> None:
    install_user(["claude"])
    source_file = tmp_path / "style_guide.md"
    source_file.write_text(
        "Always use strict typing and descriptive variable names.\n", encoding="utf-8"
    )

    code = personal.main(
        ["add", "strict_typing", "--from", str(source_file), "--title", "Strict Typing"]
    )
    assert code == 0

    rule_path = personal_root / "rules" / "strict_typing.md"
    assert rule_path.is_file()
    content = rule_path.read_text(encoding="utf-8")
    assert content.startswith("---\ntrigger: always_on\n---\n")
    assert "# Strict Typing" in content
    assert "Always use strict typing and descriptive variable names." in content

    claude_link = home / ".claude" / "rules" / "ai-governance-personal-strict_typing.md"
    assert claude_link.is_symlink()
    assert claude_link.resolve() == rule_path.resolve()


def test_personal_add_existing_requires_force(personal_root: Path) -> None:
    assert personal.main(["add", "existing", "--title", "Initial"]) == 0
    rule_path = personal_root / "rules" / "existing.md"
    assert "Initial" in rule_path.read_text(encoding="utf-8")

    # Duplicate without --force fails and preserves original
    assert personal.main(["add", "existing", "--title", "Updated"]) == 1
    assert "Initial" in rule_path.read_text(encoding="utf-8")

    # With --force succeeds
    assert personal.main(["add", "existing", "--title", "Updated", "--force"]) == 0
    assert "Updated" in rule_path.read_text(encoding="utf-8")


def test_personal_list_command(
    home: Path, personal_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    install_user(["claude"])
    personal.main(["add", "list_test"])
    personal.main(["list"])
    captured = capsys.readouterr().out
    assert "list_test" in captured
    assert "claude" in captured


def test_personal_migrate_section(home: Path, personal_root: Path, tmp_path: Path) -> None:
    install_user(["claude"])
    agents_file = tmp_path / "AGENTS.md"
    agents_file.write_text(
        "# Project Instructions\n\n"
        "Project general instructions.\n\n"
        "## Personal Preferences\n\n"
        "Always write tests with pytest.\n"
        "Be concise in responses.\n\n"
        "## Team Standards\n\n"
        "Format code with ruff.\n",
        encoding="utf-8",
    )

    code = personal.main(
        [
            "migrate",
            "--from",
            str(agents_file),
            "--name",
            "migrated_prefs",
            "--section",
            "Personal Preferences",
        ]
    )
    assert code == 0

    rule_path = personal_root / "rules" / "migrated_prefs.md"
    assert rule_path.is_file()
    content = rule_path.read_text(encoding="utf-8")
    assert content.startswith("---\ntrigger: always_on\n---\n")
    assert "Always write tests with pytest." in content
    assert "Be concise in responses." in content

    # Source file was modified: section removed, other sections retained
    remaining = agents_file.read_text(encoding="utf-8")
    assert "Personal Preferences" not in remaining
    assert "Project Instructions" in remaining
    assert "Team Standards" in remaining

    # Linked in installed agent
    claude_link = home / ".claude" / "rules" / "ai-governance-personal-migrated_prefs.md"
    assert claude_link.is_symlink()
    assert claude_link.resolve() == rule_path.resolve()


def test_personal_migrate_full_file(home: Path, personal_root: Path, tmp_path: Path) -> None:
    install_user(["claude"])
    custom_file = tmp_path / "custom_notes.md"
    custom_file.write_text("# Custom Notes\nDo not forget to clean up.\n", encoding="utf-8")

    code = personal.main(["migrate", "--from", str(custom_file), "--name", "full_notes"])
    assert code == 0

    rule_path = personal_root / "rules" / "full_notes.md"
    assert rule_path.is_file()
    content = rule_path.read_text(encoding="utf-8")
    assert content.startswith("---\ntrigger: always_on\n---\n")
    assert "# Custom Notes" in content

    # Whole source file unlinked
    assert not custom_file.exists()

    claude_link = home / ".claude" / "rules" / "ai-governance-personal-full_notes.md"
    assert claude_link.is_symlink()
    assert claude_link.resolve() == rule_path.resolve()


def test_personal_rm(home: Path, personal_root: Path) -> None:
    install_user(["claude", "antigravity"])
    personal.main(["add", "to_delete"])

    rule_path = personal_root / "rules" / "to_delete.md"
    assert rule_path.is_file()
    claude_link = home / ".claude" / "rules" / "ai-governance-personal-to_delete.md"
    gemini_link = home / ".gemini" / "config" / "rules" / "ai-governance-personal-to_delete.md"
    assert claude_link.is_symlink()
    assert gemini_link.is_symlink()

    code = personal.main(["rm", "to_delete"])
    assert code == 0

    assert not rule_path.exists()
    assert not claude_link.exists()
    assert not gemini_link.exists()

    # Removing non-existent rule returns 1
    assert personal.main(["rm", "to_delete"]) == 1


def test_cli_with_no_action_prints_help(capsys: pytest.CaptureFixture[str]) -> None:
    from ai_governance.personal import main

    assert main([]) == 0
    assert "Manage personal preference rules" in capsys.readouterr().out


def test_list_reports_an_empty_personal_layer(
    home: Path, personal_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from ai_governance.personal import main

    for md in (personal_root / "rules").glob("*.md"):
        md.unlink()
    assert main(["list"]) == 0
    assert "No personal rules found" in capsys.readouterr().out


def test_add_refuses_a_missing_source_file(home: Path, personal_root: Path) -> None:
    from ai_governance.personal import main

    assert main(["add", "voice-notes", "--from", str(personal_root / "nope.md")]) == 1
    assert not (personal_root / "rules" / "voice-notes.md").exists()


def test_add_refuses_an_existing_rule_unless_forced(home: Path, personal_root: Path) -> None:
    from ai_governance.personal import main

    assert main(["add", "voice"]) == 1  # the fixture already ships voice.md
    assert main(["add", "voice", "--force", "--title", "Voice"]) == 0
    assert "# Voice" in (personal_root / "rules" / "voice.md").read_text()


def test_migrate_refuses_a_missing_source_file(home: Path, personal_root: Path) -> None:
    from ai_governance.personal import main

    assert main(["migrate", "--from", str(personal_root / "nope.md"), "--name", "x"]) == 1


def test_migrate_refuses_an_existing_rule_unless_forced(
    home: Path, personal_root: Path, tmp_path: Path
) -> None:
    from ai_governance.personal import main

    source = tmp_path / "AGENTS.md"
    source.write_text("# Voice\n\nFirst person.\n")
    assert main(["migrate", "--from", str(source), "--name", "voice"]) == 1
    assert source.is_file(), "a refused migration must leave the source alone"


def test_migrate_reports_a_section_that_is_not_there(
    home: Path, personal_root: Path, tmp_path: Path
) -> None:
    from ai_governance.personal import main

    source = tmp_path / "AGENTS.md"
    source.write_text("# Kept\n\nSomething else.\n")
    assert main(["migrate", "--from", str(source), "--name", "new", "--section", "Missing"]) == 1
    assert source.read_text() == "# Kept\n\nSomething else.\n"


def test_migrate_moves_one_section_and_leaves_the_rest(
    home: Path, personal_root: Path, tmp_path: Path
) -> None:
    from ai_governance.personal import main

    source = tmp_path / "AGENTS.md"
    source.write_text("# Kept\n\nStays here.\n\n# Moved\n\nGoes to the rule.\n")
    assert main(["migrate", "--from", str(source), "--name", "moved", "--section", "Moved"]) == 0
    rule = (personal_root / "rules" / "moved.md").read_text()
    assert "Goes to the rule" in rule and "trigger: always_on" in rule
    remaining = source.read_text()
    assert "Stays here" in remaining and "Goes to the rule" not in remaining


def test_rm_removes_the_rule_and_its_links(home: Path, personal_root: Path) -> None:
    from ai_governance.personal import main

    install_user(["claude"])
    link = home / ".claude" / "rules" / "ai-governance-personal-voice.md"
    assert link.is_symlink()
    assert main(["rm", "voice"]) == 0
    assert not (personal_root / "rules" / "voice.md").exists()
    assert not link.exists()


def test_rm_reports_a_rule_that_is_not_there(home: Path, personal_root: Path) -> None:
    from ai_governance.personal import main

    assert main(["rm", "nothing-here"]) == 1


def test_migrate_keeps_headings_inside_fenced_code_blocks(
    home: Path, personal_root: Path, tmp_path: Path
) -> None:
    """A ``# comment`` inside a fence is not a heading, so it must not cut the section."""
    from ai_governance.personal import main

    source = tmp_path / "AGENTS.md"
    source.write_text(
        "# Tools\n\nHow to run it:\n\n```bash\n# install first\nmake install\n```\n\nAfter the block.\n\n# Other\n\nStays.\n"
    )
    assert main(["migrate", "--from", str(source), "--name", "tools", "--section", "Tools"]) == 0
    rule = (personal_root / "rules" / "tools.md").read_text()
    assert "# install first" in rule, "the fenced comment belongs to the section"
    assert "After the block" in rule, "the section was cut at the fenced comment"
    assert "Other" not in rule
    assert "Stays" in source.read_text()


def test_migrate_keeps_the_source_when_the_rule_cannot_be_written(
    home: Path, personal_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The source is only touched once the rule exists, so a failure cannot lose content."""
    from ai_governance import personal

    source = tmp_path / "AGENTS.md"
    original = "# Voice\n\nFirst person.\n"
    source.write_text(original)

    def boom(*args: object, **kwargs: object) -> Path:
        raise PermissionError("read-only rules directory")

    monkeypatch.setattr(personal, "create_rule", boom)
    with pytest.raises(PermissionError):
        personal.migrate_rule(personal.RuleTarget("voice-new"), from_file=source)
    assert source.read_text() == original


def test_rm_reports_the_links_it_cleaned_for_a_hand_deleted_rule(
    home: Path, personal_root: Path
) -> None:
    """Removing a rule whose file was deleted by hand still counts the links cleaned up."""
    from ai_governance.personal import main

    install_user(["claude"])
    link = home / ".claude" / "rules" / "ai-governance-personal-voice.md"
    assert link.is_symlink()
    (personal_root / "rules" / "voice.md").unlink()
    assert main(["rm", "voice"]) == 0
    assert not link.exists()
