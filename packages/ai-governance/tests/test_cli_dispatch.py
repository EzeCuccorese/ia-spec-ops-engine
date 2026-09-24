from __future__ import annotations

import argparse
import sys
from unittest.mock import patch

import pytest
from ai_governance.cli import main


def test_cli_dispatch_help() -> None:
    assert main([]) == 0


def test_cli_unmatched_subcommand_falls_through_to_bare_parse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Covers the defensive `else` branch: a cmd string that argparse's own subparser
    choices would normally reject before reaching this line. We bypass that by making
    ArgumentParser.parse_args a no-op, isolating the dispatch fallthrough itself."""
    monkeypatch.setattr(argparse.ArgumentParser, "parse_args", lambda self, args=None: None)
    assert main(["not-a-real-subcommand"]) == 0


def test_cli_dispatch_rules() -> None:
    with patch("ai_governance.rules.cli.main", return_value=0) as mock_rules:
        assert main(["rules", "list"]) == 0
        mock_rules.assert_called_once_with(["list"])


def test_cli_dispatch_telemetry() -> None:
    with patch("ai_governance.telemetry.cli.main", return_value=0) as mock_telemetry:
        assert main(["telemetry", "report"]) == 0
        mock_telemetry.assert_called_once_with(["report"])


def test_cli_dispatch_progress() -> None:
    with patch("ai_governance.session.cli.main", return_value=0) as mock_session:
        assert main(["progress", "list"]) == 0
        mock_session.assert_called_once_with(["list"])


def test_cli_dispatch_jira() -> None:
    with patch("ai_governance.tools.jira.main") as mock_jira:
        assert main(["jira", "help"]) == 0
        mock_jira.assert_called_once_with(["help"])


def test_cli_dispatch_confluence() -> None:
    with patch("ai_governance.tools.confluence.main") as mock_confluence:
        assert main(["confluence", "help"]) == 0
        mock_confluence.assert_called_once_with(["help"])


def test_cli_does_not_import_optional_packages() -> None:
    with patch.dict(sys.modules, {"spec": None, "workspace_engine": None}):
        assert main([]) == 0


def test_cli_help_lists_all_canonical_subcommands(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--help"]) == 0
    out = capsys.readouterr().out
    for subcommand in ("install", "update", "doctor", "rules", "telemetry", "progress", "hook"):
        assert subcommand in out
    listing = out.split("{", 1)[1].split("}", 1)[0].split(",")
    for removed in ("frugal", "harness", "progreso", "ritmo", "specops"):
        assert removed not in listing


def test_rules_subcommand_help_delegates_to_rules_parser(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit):
        main(["rules", "--help"])
    out = capsys.readouterr().out
    assert "ai-governance rules" in out


def test_cli_unknown_subcommand_errors() -> None:
    with pytest.raises(SystemExit):
        main(["not-a-real-subcommand"])


def test_cli_dispatch_install_commands() -> None:
    with patch("ai_governance.install.cli.main", return_value=0) as mock_install:
        assert main(["doctor", "--root", "."]) == 0
        mock_install.assert_called_once_with("doctor", ["--root", "."])


def test_cli_dispatch_hook() -> None:
    with patch("ai_governance.hooks.main", return_value=0) as mock_hook:
        assert main(["hook", "claude", "stop"]) == 0
        mock_hook.assert_called_once_with(["claude", "stop"])
