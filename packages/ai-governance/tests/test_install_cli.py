"""CLI surface of install/uninstall/update/status/doctor/agents/budget/probe."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from ai_governance.cli import main
from ai_governance.install import installer


@pytest.fixture
def repo(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    monkeypatch.setenv("AI_GOVERNANCE_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("AI_GOVERNANCE_AGENT", "1")
    monkeypatch.setattr(installer, "detect_stacks", lambda root: {"python"})
    root = tmp_path / "repo"
    root.mkdir()
    return root


def test_full_cli_lifecycle(repo: Path, capsys) -> None:
    root = ["--root", str(repo)]
    assert main(["install", "--scope", "user", "--agent", "claude", "--dry-run"]) == 0
    assert "[dry-run]" in capsys.readouterr().out
    assert main(["install", "--scope", "user", "--agent", "claude"]) == 0
    assert main(["install", "--agent", "claude", *root]) == 0
    capsys.readouterr()

    assert main(["status", *root]) == 0
    status = capsys.readouterr().out
    assert "user | claude | file" in status and "project | claude" in status

    assert main(["budget", *root]) == 0
    assert "tokens" in capsys.readouterr().out

    assert main(["agents"]) == 0
    assert "Antigravity" in capsys.readouterr().out

    assert main(["doctor", *root]) == 0
    assert "project:drift | OK" in capsys.readouterr().out

    assert main(["update", "--check", *root]) == 0
    assert main(["update", "--all", "--dry-run"]) == 0
    capsys.readouterr()

    assert main(["uninstall", "--agent", "claude", *root]) == 0
    assert main(["uninstall", "--scope", "user", "--agent", "claude"]) == 0
    assert not (repo / ".ai-governance").exists()


def test_update_warns_for_uninstalled_project(repo: Path, capsys) -> None:
    assert main(["update", "--root", str(repo)]) == 0
    assert "not installed" in capsys.readouterr().out


def test_install_errors_are_reported(repo: Path, capsys) -> None:
    assert main(["install", "--root", str(repo)]) == 1
    assert "--agent" in capsys.readouterr().err


def test_interactive_agent_picker(repo: Path, monkeypatch, capsys) -> None:
    from ai_governance.install import cli as install_cli

    monkeypatch.setenv("AI_GOVERNANCE_AGENT", "0")
    monkeypatch.setattr("sys.stdin.isatty", lambda: True, raising=False)
    monkeypatch.setattr("builtins.input", lambda prompt: "1,3")
    assert install_cli._pick_agents() == ["claude", "antigravity"]
    for bad in ("9", "x", ""):
        monkeypatch.setattr("builtins.input", lambda prompt, bad=bad: bad)
        with pytest.raises(ValueError):
            install_cli._pick_agents()
    monkeypatch.setattr("builtins.input", lambda prompt: "0")
    with pytest.raises(ValueError):
        install_cli._pick_agents()


def test_probe_cli_build_and_verify(repo: Path, capsys) -> None:
    assert main(["probe", "--agent", "antigravity", "--dir", str(repo / "p")]) == 0
    assert "Probe project:" in capsys.readouterr().out
    assert (repo / "p" / ".agents" / "hooks.json").exists()
    assert main(["probe", "--agent", "antigravity", "--verify", "--seen", "CANARY-AGENTS-MD"]) == 0
    out = capsys.readouterr().out
    assert json.loads(out.split("\nWARN")[0])["shell_hooks_verified"] is False


def test_rules_cli(capsys) -> None:
    assert main(["rules", "list"]) == 0
    assert "java-spring" in capsys.readouterr().out
    assert main(["rules", "show", "java-spring"]) == 0
    assert capsys.readouterr().out.startswith("#")
    assert main(["rules", "show", "nope"]) == 1


def test_update_all_forgets_projects_that_were_removed(repo: Path, capsys) -> None:
    import shutil

    assert main(["install", "--agent", "claude", "--root", str(repo)]) == 0
    shutil.rmtree(repo / ".ai-governance")
    assert main(["update", "--all"]) == 0
    assert "removed from registry" in capsys.readouterr().out
    assert installer.registered_projects() == []
