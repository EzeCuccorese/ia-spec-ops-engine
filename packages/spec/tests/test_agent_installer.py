from __future__ import annotations

from pathlib import Path

import pytest

from spec.cli import main
from spec.governance.project import ProjectGovernance


def test_agent_install_single_claude(tmp_path: Path) -> None:
    ProjectGovernance(tmp_path).initialize()
    with pytest.raises(SystemExit) as exc:
        main(["agent", "install", "claude", "--root", str(tmp_path)])
    assert exc.value.code == 0

    claude_md = tmp_path / "CLAUDE.md"
    assert claude_md.exists()
    assert "@.spec/governance.md" in claude_md.read_text(encoding="utf-8")


def test_agent_install_single_aider(tmp_path: Path) -> None:
    ProjectGovernance(tmp_path).initialize()
    with pytest.raises(SystemExit) as exc:
        main(["agent", "install", "aider", "--root", str(tmp_path)])
    assert exc.value.code == 0

    aider_conf = tmp_path / ".aider.conf.yml"
    assert aider_conf.exists()
    assert ".spec/governance.md" in aider_conf.read_text(encoding="utf-8")


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
    assert (tmp_path / "CLAUDE.md").exists()
    assert (tmp_path / ".cursorrules").exists()
    assert (tmp_path / ".windsurfrules").exists()
    assert (tmp_path / ".aider.conf.yml").exists()
    assert (tmp_path / ".github/copilot-instructions.md").exists()
    assert (tmp_path / "GEMINI.md").exists()


def test_agent_install_single_copilot(tmp_path: Path) -> None:
    ProjectGovernance(tmp_path).initialize()
    with pytest.raises(SystemExit) as exc:
        main(["agent", "install", "copilot", "--root", str(tmp_path)])
    assert exc.value.code == 0

    copilot_file = tmp_path / ".github/copilot-instructions.md"
    assert copilot_file.exists()
    assert "@.spec/governance.md" in copilot_file.read_text(encoding="utf-8")


def test_agent_install_single_gemini(tmp_path: Path) -> None:
    ProjectGovernance(tmp_path).initialize()
    with pytest.raises(SystemExit) as exc:
        main(["agent", "install", "gemini", "--root", str(tmp_path)])
    assert exc.value.code == 0

    gemini_file = tmp_path / "GEMINI.md"
    assert gemini_file.exists()
    assert "@.spec/governance.md" in gemini_file.read_text(encoding="utf-8")


def test_agent_uninstall_single_aider(tmp_path: Path) -> None:
    ProjectGovernance(tmp_path).initialize()
    with pytest.raises(SystemExit):
        main(["agent", "install", "aider", "--root", str(tmp_path)])
    assert (tmp_path / ".aider.conf.yml").exists()

    with pytest.raises(SystemExit) as exc:
        main(["agent", "uninstall", "aider", "--apply", "--root", str(tmp_path)])
    assert exc.value.code == 0
    assert not (tmp_path / ".aider.conf.yml").exists()



def test_agent_install_unknown_raises(tmp_path: Path) -> None:
    ProjectGovernance(tmp_path).initialize()
    with pytest.raises(SystemExit) as exc:
        main(["agent", "install", "nonexistent_ai", "--root", str(tmp_path)])
    assert exc.value.code == 1
