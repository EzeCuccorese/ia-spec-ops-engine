"""Corporate packs: bundled layout, opt-in user install, per-agent rendering, removal."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from ai_governance import corporate
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
    """A fake `tiendanube` pack: real packs are gitignored and absent in CI."""
    root = tmp_path / "corporate-rules"
    rules, scripts = root / "tiendanube" / "rules", root / "tiendanube" / "scripts"
    rules.mkdir(parents=True)
    scripts.mkdir()
    (rules / "glosario.md").write_text("# Glosario\n")
    (rules / "principios-culturales.md").write_text("# Principios\n")
    script = scripts / "levantar-tiendanube-local"
    script.write_text("#!/bin/sh\necho ok\n")
    script.chmod(0o755)
    monkeypatch.setattr(corporate, "corporate_root", lambda: root)
    return root


def _pack_rules(home: Path) -> list[str]:
    return sorted(p.name for p in (home / ".claude" / "rules").glob("ai-governance-tiendanube-*"))


def test_pack_exposes_rules_and_executable_scripts() -> None:
    assert "tiendanube" in corporate.available()
    pack = corporate.load("tiendanube")
    assert {rule.name for rule in pack.rules()} >= {"glosario", "principios-culturales"}
    scripts = pack.scripts()
    assert scripts and all(os.access(script, os.X_OK) for script in scripts)


def test_unknown_pack_is_rejected(tmp_path: Path) -> None:
    other = tmp_path / "other"
    (other / "acme" / "rules").mkdir(parents=True)
    assert corporate.available(other) == ["acme"]
    assert corporate.available(tmp_path / "missing") == []
    with pytest.raises(ValueError, match="Unknown corporate pack"):
        corporate.load("globex", other)


def test_user_install_without_corporate_installs_no_pack(home: Path) -> None:
    install_user(["claude"])
    assert _pack_rules(home) == []
    assert not (home / ".local" / "bin").exists()


def test_corporate_install_renders_rules_per_agent_and_links_scripts(home: Path) -> None:
    report = install_user(["claude", "antigravity", "codex"], corporate_packs=("tiendanube",))

    claude_rules = _pack_rules(home)
    assert "ai-governance-tiendanube-glosario.md" in claude_rules
    glosario = home / ".gemini" / "config" / "rules" / "ai-governance-tiendanube-glosario.md"
    assert glosario.read_text().startswith("---\ntrigger: always_on\n---\n")
    assert any("OpenAI Codex" in warning for warning in report.warnings)
    link = home / ".local" / "bin" / "levantar-tiendanube-local"
    assert link.is_symlink() and Path(os.readlink(link)).is_file()
    assert global_ledger().extra["corporate"] == {"tiendanube": ["claude", "antigravity", "codex"]}


def test_pack_survives_reinstall_and_goes_with_its_last_agent(home: Path) -> None:
    install_user(["claude", "antigravity"], corporate_packs=("tiendanube",))
    install_user(["claude"])
    assert _pack_rules(home)

    uninstall_user(["claude"])
    assert _pack_rules(home) == []
    assert (home / ".local" / "bin" / "levantar-tiendanube-local").is_symlink()

    uninstall_user(["antigravity"])
    assert not (home / ".local" / "bin" / "levantar-tiendanube-local").exists()
    assert "corporate" not in global_ledger().extra


def test_uninstall_corporate_removes_only_the_pack(home: Path) -> None:
    install_user(["claude"], corporate_packs=("tiendanube",))
    uninstall_user([], corporate_packs=("tiendanube",))
    assert _pack_rules(home) == []
    assert (home / ".claude" / "rules" / "ai-governance.md").exists()
    assert not (home / ".local" / "bin" / "levantar-tiendanube-local").exists()


def test_bin_dir_override(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_GOVERNANCE_BIN_DIR", str(home / "tools"))
    install_user(["claude"], corporate_packs=("tiendanube",))
    assert (home / "tools" / "levantar-tiendanube-local").is_symlink()


def test_cli_corporate_requires_user_scope(home: Path) -> None:
    code = install_cli(
        "install", ["--scope", "project", "--agent", "claude", "--corporate", "tiendanube"]
    )
    assert code == 2


def test_cli_uninstall_corporate_without_agent(home: Path) -> None:
    assert (
        install_cli(
            "install", ["--scope", "user", "--agent", "claude", "--corporate", "tiendanube"]
        )
        == 0
    )
    assert install_cli("uninstall", ["--scope", "user", "--corporate", "tiendanube"]) == 0
    assert _pack_rules(home) == []


def test_corporate_root_defaults_to_the_packages_folder_and_honours_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.undo()
    monkeypatch.delenv("AI_GOVERNANCE_CORPORATE_DIR", raising=False)
    assert corporate.corporate_root().parent.name == "packages"
    assert corporate.corporate_root().name == "corporate-rules"
    monkeypatch.setenv("AI_GOVERNANCE_CORPORATE_DIR", str(tmp_path))
    assert corporate.corporate_root() == tmp_path
