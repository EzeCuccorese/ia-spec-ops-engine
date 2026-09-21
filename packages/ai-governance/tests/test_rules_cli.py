from pathlib import Path
from unittest.mock import patch

import pytest
from ai_governance.rules import cli as rules_cli
from ai_governance.rules.cli import main
from ai_governance.rules.core.storage import RuleStorage


def _patch_global_storage(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Redirect RuleStorage.global_storage() into tmp_path so nothing touches the real home."""
    fake_home = tmp_path / "fake-home" / ".specops" / "rules"
    monkeypatch.setattr(RuleStorage, "global_storage", classmethod(lambda cls: cls(fake_home)))


class _AllExceptAgents(dict):
    """A mapping that hides the 'agents' key from `in` while __getitem__ still resolves it.

    Used to exercise the defensive `else` fallback branches in rules/cli.py that are
    otherwise unreachable because argparse restricts --agent to {"agents", "all"} and
    "agents" is always registered in ALL_ADAPTERS.
    """

    def __contains__(self, key: object) -> bool:
        if key == "agents":
            return False
        return super().__contains__(key)


def test_cli_list_action(capsys) -> None:
    # --full disables agent-mode truncation so the full catalog is asserted here,
    # independent of stdout being a TTY (see ai_governance.output truncation).
    main(["list", "--full"])
    captured = capsys.readouterr().out
    assert "Engineering Rules Catalog" in captured
    assert "java-spring" in captured


def test_cli_local_install_and_uninstall(tmp_path: Path) -> None:
    main(["install", "--local", "--all", "--root", str(tmp_path)])

    manifest_path = tmp_path / ".specops" / "rules" / "manifest.json"
    assert manifest_path.exists()
    assert (tmp_path / "AGENTS.md").exists()
    assert not (tmp_path / "CLAUDE.md").exists()
    assert not (tmp_path / ".cursorrules").exists()

    main(["uninstall", "--local", "--root", str(tmp_path)])
    assert not manifest_path.exists()
    assert not (tmp_path / "AGENTS.md").exists()


def test_show_banner_prints_when_not_in_agent_mode(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setenv("SPECOPS_AGENT", "0")
    rules_cli.show_banner()
    assert "SPECOPS RULES" in capsys.readouterr().out


def test_show_banner_silent_in_agent_mode(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setenv("SPECOPS_AGENT", "1")
    rules_cli.show_banner()
    assert capsys.readouterr().out == ""


def test_interactive_installer_local_all_categories(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SPECOPS_AGENT", "0")
    with (
        patch("ai_governance.rules.cli.select_one", return_value=1) as mock_one,
        patch(
            "ai_governance.rules.cli.select_multiple",
            side_effect=[["agents"], ["all"]],
        ) as mock_multi,
    ):
        main(["install", "--root", str(tmp_path)])
    mock_one.assert_called_once()
    assert mock_multi.call_count == 2
    assert (tmp_path / ".specops" / "rules" / "manifest.json").exists()
    assert (tmp_path / "AGENTS.md").exists()


def test_interactive_installer_local_specific_categories(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    with (
        patch("ai_governance.rules.cli.select_one", return_value=1),
        patch(
            "ai_governance.rules.cli.select_multiple",
            side_effect=[["agents"], ["1-core"]],
        ),
    ):
        main(["install", "--root", str(tmp_path)])
    manifest_path = tmp_path / ".specops" / "rules" / "manifest.json"
    assert manifest_path.exists()


def test_interactive_installer_empty_category_selection_falls_back_to_all_rules(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    with (
        patch("ai_governance.rules.cli.select_one", return_value=1),
        patch(
            "ai_governance.rules.cli.select_multiple",
            side_effect=[["agents"], []],
        ),
    ):
        main(["install", "--root", str(tmp_path)])
    manifest_path = tmp_path / ".specops" / "rules" / "manifest.json"
    data = manifest_path.read_text(encoding="utf-8")
    # Falling back to catalog.rules means a large, non-empty rule set was saved.
    assert manifest_path.exists()
    assert len(data) > 100


def test_interactive_installer_global_scope(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_global_storage(monkeypatch, tmp_path)
    with (
        patch("ai_governance.rules.cli.select_one", return_value=0),
        patch(
            "ai_governance.rules.cli.select_multiple",
            side_effect=[["agents"], ["all"]],
        ),
    ):
        main(["install", "--root", str(tmp_path)])
    assert (tmp_path / "fake-home" / ".specops" / "rules" / "manifest.json").exists()


def test_interactive_uninstaller_local_scope(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    main(["install", "--local", "--all", "--root", str(tmp_path)])
    with patch("ai_governance.rules.cli.select_one", return_value=1):
        main(["uninstall", "--root", str(tmp_path)])
    assert not (tmp_path / ".specops" / "rules" / "manifest.json").exists()


def test_interactive_uninstaller_global_scope(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_global_storage(monkeypatch, tmp_path)
    with patch("ai_governance.rules.cli.select_one", return_value=0):
        main(["uninstall", "--root", str(tmp_path)])


def test_default_menu_dispatches_to_installer(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    with (
        patch("ai_governance.rules.cli.select_one", side_effect=[0, 1]),
        patch(
            "ai_governance.rules.cli.select_multiple",
            side_effect=[["agents"], ["all"]],
        ),
    ):
        main(["--root", str(tmp_path)])
    assert (tmp_path / ".specops" / "rules" / "manifest.json").exists()


def test_default_menu_dispatches_to_uninstaller(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    main(["install", "--local", "--all", "--root", str(tmp_path)])
    with patch("ai_governance.rules.cli.select_one", side_effect=[1, 1]):
        main(["--root", str(tmp_path)])
    assert not (tmp_path / ".specops" / "rules" / "manifest.json").exists()


def test_default_menu_dispatches_to_list(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
) -> None:
    with patch("ai_governance.rules.cli.select_one", return_value=2):
        main(["--root", str(tmp_path)])
    assert "Engineering Rules Catalog" in capsys.readouterr().out


def test_explicit_uninstall_agent_all(tmp_path: Path) -> None:
    main(["install", "--local", "--all", "--root", str(tmp_path)])
    main(["uninstall", "--local", "--agent", "all", "--root", str(tmp_path)])
    assert not (tmp_path / "AGENTS.md").exists()


def test_explicit_uninstall_agent_specific(tmp_path: Path) -> None:
    main(["install", "--local", "--all", "--root", str(tmp_path)])
    main(["uninstall", "--local", "--agent", "agents", "--root", str(tmp_path)])
    assert not (tmp_path / "AGENTS.md").exists()


def test_uninstall_agent_fallback_when_not_registered(tmp_path: Path) -> None:
    """Defensive else branch: --agent resolves outside ALL_ADAPTERS falls back to all adapters."""
    main(["install", "--local", "--all", "--root", str(tmp_path)])
    with patch("ai_governance.rules.cli.ALL_ADAPTERS", _AllExceptAgents(rules_cli.ALL_ADAPTERS)):
        main(["uninstall", "--local", "--root", str(tmp_path)])
    assert not (tmp_path / "AGENTS.md").exists()


def test_explicit_install_agent_all(tmp_path: Path) -> None:
    main(["install", "--local", "--all", "--agent", "all", "--root", str(tmp_path)])
    assert (tmp_path / "AGENTS.md").exists()


def test_interactive_uninstaller_loops_over_multiple_adapters(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Covers the branch where a falsy uninstall result continues the adapter loop."""

    class _NoOpAdapter:
        display_name = "No-Op Adapter"

        def uninstall(self, root: Path, is_global: bool) -> None:
            return None

    two_adapters = {"noop": _NoOpAdapter(), "agents": rules_cli.ALL_ADAPTERS["agents"]}
    main(["install", "--local", "--all", "--root", str(tmp_path)])
    with (
        patch("ai_governance.rules.cli.select_one", return_value=1),
        patch("ai_governance.rules.cli.ALL_ADAPTERS", two_adapters),
    ):
        main(["uninstall", "--root", str(tmp_path)])
    assert not (tmp_path / "AGENTS.md").exists()


def test_install_agent_fallback_when_not_registered(tmp_path: Path) -> None:
    """Defensive else branch: --agent resolves outside ALL_ADAPTERS falls back to 'agents' adapter."""
    with patch("ai_governance.rules.cli.ALL_ADAPTERS", _AllExceptAgents(rules_cli.ALL_ADAPTERS)):
        main(["install", "--local", "--all", "--root", str(tmp_path)])
    assert (tmp_path / "AGENTS.md").exists()
