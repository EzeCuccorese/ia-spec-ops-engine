"""Corporate packs: any folder in the packs dir installs with the user scope, no flags."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from ai_governance import corporate
from ai_governance.install import doctor
from ai_governance.install.budget import fixed_cost
from ai_governance.install.cli import main as install_cli
from ai_governance.install.installer import global_ledger, install_user, uninstall_user


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


def test_unknown_or_missing_packs(tmp_path: Path) -> None:
    assert corporate.available(tmp_path / "missing") == []
    with pytest.raises(ValueError, match="Unknown corporate pack"):
        corporate.load("globex")


def test_user_install_picks_up_every_pack_without_flags(home: Path) -> None:
    report = install_user(["claude", "antigravity", "codex"])

    assert _pack_rules(home) == [
        "ai-governance-acme-glossary.md",
        "ai-governance-acme-principles.md",
    ]
    gemini = home / ".gemini" / "config" / "rules" / "ai-governance-acme-glossary.md"
    assert gemini.read_text().startswith("---\ntrigger: always_on\n---\n")
    assert any("OpenAI Codex" in warning for warning in report.warnings)
    assert _script(home).is_symlink() and Path(os.readlink(_script(home))).is_file()


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

    rules = sorted(p.name for p in (home / ".claude" / "rules").glob("ai-governance-*-*"))
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


def test_bin_dir_override(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_GOVERNANCE_BIN_DIR", str(home / "tools"))
    install_user(["claude"])
    assert (home / "tools" / "acme-up").is_symlink()


def _add_pack(pack_root: Path, name: str, script: str) -> None:
    (pack_root / name / "rules").mkdir(parents=True)
    (pack_root / name / "rules" / "glossary.md").write_text("# Glossary\n")
    (pack_root / name / "scripts").mkdir()
    (pack_root / name / "scripts" / script).write_text("#!/bin/sh\n")


def test_agent_without_global_rules_warns_once_for_all_packs(home: Path, pack_root: Path) -> None:
    _add_pack(pack_root, "globex", "globex-up")

    report = install_user(["codex"])

    codex = [warning for warning in report.warnings if "OpenAI Codex" in warning]
    assert codex == ["OpenAI Codex has no per-file global rules: acme, globex rules skipped."]


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
