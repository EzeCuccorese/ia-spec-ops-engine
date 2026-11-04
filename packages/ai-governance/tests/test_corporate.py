"""Corporate packs: any folder in the packs dir installs with the user scope, no flags."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from ai_governance import corporate
from ai_governance.install import cli, doctor
from ai_governance.install.budget import fixed_cost
from ai_governance.install.cli import main as install_cli
from ai_governance.install.installer import global_ledger, install_user, uninstall_user
from ai_governance.rules.catalog import RuleCatalog


@pytest.fixture
def home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setenv("AI_GOVERNANCE_STATE_DIR", str(home / "state"))
    monkeypatch.delenv("CODEX_HOME", raising=False)
    monkeypatch.delenv("AI_GOVERNANCE_BIN_DIR", raising=False)
    return home


@pytest.fixture(autouse=True)
def pack_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """A fake company pack `acme`; real packs are gitignored and absent in CI."""
    root = tmp_path / "corporate-rules"
    rules, scripts = root / "acme" / "rules", root / "acme" / "scripts"
    rules.mkdir(parents=True)
    scripts.mkdir()
    (rules / "glossary.md").write_text("# Glossary\n")
    (rules / "principles.md").write_text("# Principles\n")
    script = scripts / "acme-up"
    script.write_text("#!/bin/sh\necho ok\n")
    script.chmod(0o755)
    monkeypatch.setenv("AI_GOVERNANCE_CORPORATE_DIR", str(root))
    return root


def _pack_rules(home: Path) -> list[str]:
    return sorted(p.name for p in (home / ".claude" / "rules").glob("ai-governance-acme-*"))


def _script(home: Path) -> Path:
    return home / ".local" / "bin" / "acme-up"


def test_pack_exposes_rules_and_executable_scripts() -> None:
    (pack,) = corporate.packs()
    assert pack.name == "acme"
    assert {rule.name for rule in pack.rules()} == {"glossary", "principles"}
    assert all(os.access(script, os.X_OK) for script in pack.scripts())


def test_missing_packs_folder_lists_no_pack(tmp_path: Path) -> None:
    assert corporate.available(tmp_path / "missing") == []
    assert corporate.packs(tmp_path / "missing") == []


def test_user_install_picks_up_every_pack_without_flags(home: Path) -> None:
    report = install_user(["claude", "antigravity", "codex"])

    assert _pack_rules(home) == [
        "ai-governance-acme-glossary.md",
        "ai-governance-acme-principles.md",
    ]
    gemini = home / ".gemini" / "config" / "rules" / "ai-governance-acme-glossary.md"
    assert gemini.is_symlink() and Path(os.readlink(gemini)).is_file()
    codex = home / ".codex" / "ai-governance" / "company" / "acme-glossary.md"
    assert codex.is_symlink() and Path(os.readlink(codex)).is_file()
    assert not any("OpenAI Codex" in warning for warning in report.warnings)
    assert _script(home).is_symlink() and Path(os.readlink(_script(home))).is_file()


def test_user_install_adds_path_scoped_language_rules(home: Path) -> None:
    report = install_user(["claude", "antigravity", "codex"])

    python = (home / ".claude" / "rules" / "ai-governance-python-async.md").read_text()
    assert python.startswith('---\npaths:\n  - "**/*.py"')
    assert "EmailStr" in python
    gemini = home / ".gemini" / "config" / "rules" / "ai-governance-go-idiomatic.md"
    assert "trigger: glob" in gemini.read_text()
    assert not any("language rules skipped" in warning for warning in report.warnings)
    codex = home / ".codex" / "ai-governance"
    index = (codex / "language-rules.md").read_text()
    assert "`**/*.py`" in index and str(codex / "ai-governance-python-async.md") in index
    assert "EmailStr" in (codex / "ai-governance-python-async.md").read_text()
    assert "language-rules.md" in (home / ".codex" / "AGENTS.md").read_text()


def test_claude_rules_are_symlinks_and_old_copies_migrate(home: Path, pack_root: Path) -> None:
    install_user(["claude"])
    link = home / ".claude" / "rules" / "ai-governance-acme-glossary.md"
    source = (pack_root / "acme" / "rules" / "glossary.md").resolve()
    assert link.is_symlink() and Path(os.readlink(link)) == source

    # Turn it back into what the copy-based installer left: a plain file with a "file" entry.
    ledger = global_ledger()
    ledger.entries = [e for e in ledger.entries if e["path"] != ledger.key(link)]
    ledger.entries.append(
        {"agent": "claude", "kind": "file", "path": ledger.key(link), "sha256": "x"}
    )
    ledger.save(cli.Report(), False)
    link.unlink()
    link.write_text("# Glossary\n")

    install_user(["claude"])

    assert link.is_symlink() and Path(os.readlink(link)) == source
    assert not [
        e
        for e in global_ledger().entries
        if e["kind"] == "file" and e["path"] == global_ledger().key(link)
    ]


def test_no_packs_installs_nothing_corporate(home: Path, pack_root: Path) -> None:
    for path in sorted(pack_root.rglob("*"), reverse=True):
        path.unlink() if path.is_file() else path.rmdir()
    install_user(["claude"])
    assert _pack_rules(home) == []
    assert not _script(home).exists()


def test_switching_company_is_swapping_the_folder(home: Path, pack_root: Path) -> None:
    install_user(["claude"])
    (pack_root / "acme").rename(pack_root / "globex")

    install_user(["claude"])

    rules_dir = home / ".claude" / "rules"
    rules = sorted(p.name for p in rules_dir.glob("ai-governance-*-*") if p.is_symlink())
    assert rules == ["ai-governance-globex-glossary.md", "ai-governance-globex-principles.md"]
    assert (home / ".local" / "bin" / "acme-up").is_symlink()  # same script name, new target
    assert "globex" in os.readlink(home / ".local" / "bin" / "acme-up")


def test_scripts_go_with_the_last_installed_agent(home: Path) -> None:
    install_user(["claude", "antigravity"])
    uninstall_user(["claude"])
    assert _pack_rules(home) == []
    assert _script(home).is_symlink()

    uninstall_user(["antigravity"])
    assert not _script(home).exists()


def test_script_owner_is_not_reported_as_an_agent(home: Path) -> None:
    install_user(["claude"])

    assert ("user:agents", doctor.OK, "claude") in doctor.check(None)
    assert set(fixed_cost(global_ledger())) == {"claude"}


def test_status_and_budget_name_the_owner_column(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_user(["claude"])
    tables: list[tuple[str, ...]] = []
    monkeypatch.setattr(cli, "emit_rows", lambda rows, *, headers, full: tables.append(headers))

    install_cli("status", ["--root", str(home)])
    install_cli("budget", ["--root", str(home)])

    assert [headers[1] for headers in tables] == ["Owner", "Owner"]


def test_bin_dir_override(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_GOVERNANCE_BIN_DIR", str(home / "tools"))
    install_user(["claude"])
    assert (home / "tools" / "acme-up").is_symlink()


def _add_pack(pack_root: Path, name: str, script: str) -> None:
    (pack_root / name / "rules").mkdir(parents=True)
    (pack_root / name / "rules" / "glossary.md").write_text("# Glossary\n")
    (pack_root / name / "scripts").mkdir()
    (pack_root / name / "scripts" / script).write_text("#!/bin/sh\n")


def test_script_name_clash_keeps_the_first_pack(home: Path, pack_root: Path) -> None:
    _add_pack(pack_root, "globex", "acme-up")

    report = install_user(["claude"])

    assert "/acme/" in os.readlink(_script(home))
    assert "Script acme-up of globex skipped: acme already provides it." in report.warnings


def test_cli_installs_packs_with_a_plain_user_install(home: Path) -> None:
    assert install_cli("install", ["--scope", "user", "--agent", "claude"]) == 0
    assert _pack_rules(home)


def test_corporate_root_defaults_to_the_packages_folder(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AI_GOVERNANCE_CORPORATE_DIR")
    root = corporate.corporate_root()
    assert (root.parent.name, root.name) == ("packages", "corporate-rules")


def test_codex_installs_no_language_index_without_rules(home: Path) -> None:
    from ai_governance.install.agents import AGENTS

    assert AGENTS["codex"].catalog_artifacts([]) == []


def test_missing_corporate_dir_keeps_installed_rules_and_scripts_and_warns(
    home: Path, pack_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_user(["claude"])
    assert _pack_rules(home) == [
        "ai-governance-acme-glossary.md",
        "ai-governance-acme-principles.md",
    ]
    assert _script(home).is_symlink()

    missing = pack_root.parent / "nonexistent-corporate-dir"
    monkeypatch.setenv("AI_GOVERNANCE_CORPORATE_DIR", str(missing))

    report = install_user(["claude"])

    assert _pack_rules(home) == [
        "ai-governance-acme-glossary.md",
        "ai-governance-acme-principles.md",
    ]
    assert _script(home).is_symlink()
    assert ("unchanged", str(home / ".claude" / "rules" / "ai-governance-acme-glossary.md")) in report.changes
    assert ("unchanged", str(_script(home))) in report.changes
    assert any("AI_GOVERNANCE_CORPORATE_DIR" in w and str(missing) in w for w in report.warnings)

    # Idempotent second run
    report2 = install_user(["claude"])
    assert _pack_rules(home) == [
        "ai-governance-acme-glossary.md",
        "ai-governance-acme-principles.md",
    ]
    assert _script(home).is_symlink()
    assert any("AI_GOVERNANCE_CORPORATE_DIR" in w and str(missing) in w for w in report2.warnings)


def test_empty_corporate_dir_still_removes(home: Path, pack_root: Path) -> None:
    install_user(["claude"])
    assert _pack_rules(home)
    assert _script(home).is_symlink()

    for path in sorted(pack_root.rglob("*"), reverse=True):
        path.unlink() if path.is_file() else path.rmdir()
    assert pack_root.is_dir()

    report = install_user(["claude"])

    assert _pack_rules(home) == []
    assert not _script(home).exists()
    assert not any("AI_GOVERNANCE_CORPORATE_DIR" in w for w in report.warnings)


def test_uninstall_keeps_shared_scripts_when_corporate_dir_missing(
    home: Path, pack_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_user(["claude", "antigravity"])
    assert _script(home).is_symlink()

    missing = pack_root.parent / "nonexistent-corporate-dir"
    monkeypatch.setenv("AI_GOVERNANCE_CORPORATE_DIR", str(missing))

    uninstall_user(["claude"])
    assert _pack_rules(home) == []
    assert _script(home).is_symlink()

    uninstall_user(["antigravity"])
    assert not _script(home).exists()


def test_missing_corporate_dir_keeps_all_agents_links(
    home: Path, pack_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_user(["claude", "antigravity", "codex"])
    gemini_rule = home / ".gemini" / "config" / "rules" / "ai-governance-acme-glossary.md"
    codex_rule = home / ".codex" / "ai-governance" / "company" / "acme-glossary.md"
    assert gemini_rule.is_symlink()
    assert codex_rule.is_symlink()

    missing = pack_root.parent / "nonexistent-packs"
    monkeypatch.setenv("AI_GOVERNANCE_CORPORATE_DIR", str(missing))

    report = install_user(["claude", "antigravity", "codex"])
    assert _pack_rules(home)
    assert gemini_rule.is_symlink()
    assert codex_rule.is_symlink()
    assert _script(home).is_symlink()
    assert any("AI_GOVERNANCE_CORPORATE_DIR" in w for w in report.warnings)


def test_non_corporate_agent_link_not_kept_when_dir_missing(
    home: Path, pack_root: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    install_user(["claude"])
    assert _pack_rules(home)
    assert _script(home).is_symlink()

    # Create a non-corporate symlink in Claude rules and record it in ledger
    external_target = tmp_path / "custom.md"
    external_target.write_text("# Custom\n")
    external_link = home / ".claude" / "rules" / "ai-governance-custom-rule.md"
    external_link.symlink_to(external_target)

    # Also a link pretending to be a catalog rule
    catalog_target = tmp_path / "catalog.md"
    catalog_target.write_text("# Catalog\n")
    catalog_link = home / ".claude" / "rules" / "ai-governance-python-async.md"
    if catalog_link.exists():
        catalog_link.unlink()
    catalog_link.symlink_to(catalog_target)

    ledger = global_ledger()
    ledger.entries.append(
        {"agent": "claude", "kind": "link", "path": ledger.key(external_link), "target": str(external_target)}
    )
    ledger.entries.append(
        {"agent": "claude", "kind": "link", "path": ledger.key(catalog_link), "target": str(catalog_target)}
    )
    ledger.save(cli.Report(), False)

    missing = pack_root.parent / "nonexistent-corporate-dir"
    monkeypatch.setenv("AI_GOVERNANCE_CORPORATE_DIR", str(missing))

    report = install_user(["claude"])

    # Genuine corporate rules and scripts are kept
    assert _pack_rules(home) == [
        "ai-governance-acme-glossary.md",
        "ai-governance-acme-principles.md",
    ]
    assert _script(home).is_symlink()

    # Non-corporate link was NOT kept and was removed
    assert not external_link.exists()
    assert not external_link.is_symlink()
    assert ("removed", str(external_link)) in report.changes

    # The catalog rule was installed as a regular file, not kept as a link
    assert catalog_link.is_file() and not catalog_link.is_symlink()


def test_is_corporate_entry_edge_cases(home: Path) -> None:
    from ai_governance.install.installer import _is_corporate_entry, _is_corporate_target

    ledger = global_ledger()
    catalog = RuleCatalog()

    assert not _is_corporate_target("")
    assert not _is_corporate_entry(ledger, {"kind": "file"})
    assert not _is_corporate_entry(
        ledger, {"kind": "link", "agent": "unknown", "path": "p", "target": "t"}
    )
    assert not _is_corporate_entry(
        ledger,
        {
            "kind": "link",
            "agent": "claude",
            "path": str(home / ".claude" / "not_rules" / "file.md"),
            "target": "t",
        },
    )
    assert not _is_corporate_entry(
        ledger,
        {
            "kind": "link",
            "agent": "claude",
            "path": str(home / ".claude" / "rules" / "no-prefix.md"),
            "target": "t",
        },
    )
    assert not _is_corporate_entry(
        ledger,
        {
            "kind": "link",
            "agent": "claude",
            "path": str(home / ".claude" / "rules" / "ai-governance-nohyphen.md"),
            "target": "t",
        },
    )
    assert not _is_corporate_entry(
        ledger,
        {
            "kind": "link",
            "agent": "claude",
            "path": str(home / ".claude" / "rules" / "ai-governance-kotlin-sub.md"),
            "target": "t",
        },
        catalog=catalog,
    )
