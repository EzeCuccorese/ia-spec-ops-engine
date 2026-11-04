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


def test_user_install_links_personal_rules_for_all_agents(
    home: Path, personal_root: Path
) -> None:
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
    assert "once per session read every file in `company/` and `personal/`" in codex_agents

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


def test_is_personal_entry_edge_cases(home: Path) -> None:
    ledger = global_ledger()

    assert not _is_personal_target("")
    assert _is_personal_target("/some/path/personal/rules/foo.md")
    assert _is_personal_target("/custom/rules/bar.md")

    assert not _is_personal_entry(ledger, {"kind": "file"})
    assert not _is_personal_entry(
        ledger, {"kind": "link", "agent": "unknown", "path": "p", "target": "t"}
    )
    assert not _is_personal_entry(
        ledger,
        {
            "kind": "link",
            "agent": "codex",
            "path": str(home / ".codex" / "ai-governance" / "company" / "foo.md"),
            "target": str(home / "personal" / "rules" / "foo.md"),
        },
    )
    assert not _is_personal_entry(
        ledger,
        {
            "kind": "link",
            "agent": "codex",
            "path": str(home / ".codex" / "ai-governance" / "personal" / "foo.txt"),
            "target": str(home / "personal" / "rules" / "foo.txt"),
        },
    )
    assert not _is_personal_entry(
        ledger,
        {
            "kind": "link",
            "agent": "claude",
            "path": str(home / ".claude" / "other" / "ai-governance-personal-voice.md"),
            "target": str(home / "personal" / "rules" / "voice.md"),
        },
    )
    assert not _is_personal_entry(
        ledger,
        {
            "kind": "link",
            "agent": "claude",
            "path": str(home / ".claude" / "rules" / "ai-governance-voice.md"),
            "target": str(home / "personal" / "rules" / "voice.md"),
        },
    )
    assert not _is_personal_entry(
        ledger,
        {
            "kind": "link",
            "agent": "claude",
            "path": str(home / ".claude" / "rules" / "ai-governance-personal-.md"),
            "target": str(home / "personal" / "rules" / "voice.md"),
        },
    )

    from ai_governance.install.installer import _is_corporate_entry

    assert not _is_corporate_entry(
        ledger,
        {
            "kind": "link",
            "agent": "claude",
            "path": str(home / ".claude" / "rules" / "ai-governance-personal-voice.md"),
            "target": str(home / "personal" / "rules" / "voice.md"),
        },
    )
