from __future__ import annotations

import sys
from unittest.mock import patch

from ai_governance.cli import main


def test_cli_dispatch_help() -> None:
    assert main([]) == 0


def test_cli_dispatch_rules() -> None:
    with patch("ai_governance.rules.cli.main", return_value=0) as mock_rules:
        assert main(["rules", "list"]) == 0
        mock_rules.assert_called_once()


def test_cli_dispatch_frugal() -> None:
    with patch("ai_governance.frugality.cli.main", return_value=0) as mock_frugal:
        assert main(["frugal", "--help"]) == 0
        mock_frugal.assert_called_once()


def test_cli_dispatch_statusline() -> None:
    with patch("ai_governance.telemetry.statusline.main", return_value=0) as mock_status:
        assert main(["statusline"]) == 0
        mock_status.assert_called_once()


def test_cli_dispatch_ritmo() -> None:
    with patch("ai_governance.telemetry.cli.main", return_value=0) as mock_telemetry:
        assert main(["ritmo", "--budget", "100"]) == 0
        mock_telemetry.assert_called_once_with(["ritmo", "--budget", "100"])


def test_cli_dispatch_progress() -> None:
    with patch("ai_governance.session.cli.main", return_value=0) as mock_session:
        assert main(["progress", "list"]) == 0
        mock_session.assert_called_once()


def test_cli_dispatch_jira() -> None:
    with patch("ai_governance.tools.jira.main") as mock_jira:
        assert main(["jira", "help"]) == 0
        mock_jira.assert_called_once()


def test_cli_dispatch_confluence() -> None:
    with patch("ai_governance.tools.confluence.main") as mock_confluence:
        assert main(["confluence", "help"]) == 0
        mock_confluence.assert_called_once()


def test_cli_does_not_import_optional_packages() -> None:
    with patch.dict(sys.modules, {"spec": None, "workspace_engine": None}):
        assert main([]) == 0
