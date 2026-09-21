from __future__ import annotations

import argparse
import sys
from unittest.mock import patch

import pytest
from ai_governance.cli import main


def test_cli_dispatch_help() -> None:
    assert main([]) == 0


def test_cli_shows_banner_panel_when_not_in_agent_mode(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("SPECOPS_AGENT", "0")
    assert main([]) == 0
    assert "AI GOVERNANCE" in capsys.readouterr().out


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


def test_cli_dispatch_frugal() -> None:
    with patch("ai_governance.frugality.cli.main", return_value=0) as mock_frugal:
        assert main(["frugal", "--help"]) == 0
        mock_frugal.assert_called_once_with(["--help"])


def test_cli_dispatch_telemetry() -> None:
    with patch("ai_governance.telemetry.cli.main", return_value=0) as mock_telemetry:
        assert main(["telemetry", "usage"]) == 0
        mock_telemetry.assert_called_once_with(["usage"])


def test_cli_dispatch_ritmo() -> None:
    with patch("ai_governance.telemetry.cli.main", return_value=0) as mock_telemetry:
        assert main(["ritmo", "--budget", "100"]) == 0
        mock_telemetry.assert_called_once_with(["ritmo", "--budget", "100"])


def test_cli_dispatch_usage_alias() -> None:
    with patch("ai_governance.telemetry.cli.main", return_value=0) as mock_telemetry:
        assert main(["usage", "--budget", "50"]) == 0
        mock_telemetry.assert_called_once_with(["usage", "--budget", "50"])


def test_cli_dispatch_progress() -> None:
    with patch("ai_governance.session.cli.main", return_value=0) as mock_session:
        assert main(["progress", "list"]) == 0
        mock_session.assert_called_once_with(["list"])


def test_cli_dispatch_task_alias() -> None:
    with patch("ai_governance.session.cli.main", return_value=0) as mock_session:
        assert main(["task", "list"]) == 0
        mock_session.assert_called_once_with(["list"])


def test_cli_dispatch_jira() -> None:
    with patch("ai_governance.tools.jira.main") as mock_jira:
        assert main(["jira", "help"]) == 0
        mock_jira.assert_called_once_with(["help"])


def test_cli_dispatch_confluence() -> None:
    with patch("ai_governance.tools.confluence.main") as mock_confluence:
        assert main(["confluence", "help"]) == 0
        mock_confluence.assert_called_once_with(["help"])


def test_cli_dispatch_harness() -> None:
    with patch("ai_governance.harness.cli.main", return_value=0) as mock_harness:
        assert main(["harness", "list"]) == 0
        mock_harness.assert_called_once_with(["list"])


def test_cli_dispatch_doctor() -> None:
    with patch("ai_governance.harness.doctor.main", return_value=0) as mock_doctor:
        assert main(["doctor"]) == 0
        mock_doctor.assert_called_once_with([])


def test_cli_does_not_import_optional_packages() -> None:
    with patch.dict(sys.modules, {"spec": None, "workspace_engine": None}):
        assert main([]) == 0


def test_cli_help_lists_all_canonical_subcommands(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        main(["--help"])
    out = capsys.readouterr().out
    for subcommand in (
        "rules",
        "frugal",
        "telemetry",
        "progress",
        "jira",
        "confluence",
    ):
        assert subcommand in out
    # Hidden legacy aliases stay functional but are not advertised in --help.
    assert "progreso" not in out


def test_rules_subcommand_help_delegates_to_rules_parser(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit):
        main(["rules", "--help"])
    out = capsys.readouterr().out
    assert "SpecOps Rules" in out


def test_cli_unknown_subcommand_errors() -> None:
    with pytest.raises(SystemExit):
        main(["not-a-real-subcommand"])
