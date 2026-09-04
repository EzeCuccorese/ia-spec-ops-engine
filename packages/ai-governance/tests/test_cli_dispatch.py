from __future__ import annotations

import sys
from unittest.mock import patch

from ai_governance.cli import main


def test_cli_dispatch_help(capsys) -> None:
    with patch.object(sys, "argv", ["governance"]):
        assert main() == 0


def test_cli_dispatch_rules() -> None:
    with (
        patch.object(sys, "argv", ["governance", "rules", "list"]),
        patch("ai_governance.rules.cli.main", return_value=0) as mock_rules,
    ):
        assert main() == 0
        mock_rules.assert_called_once()


def test_cli_dispatch_frugal() -> None:
    with (
        patch.object(sys, "argv", ["governance", "frugal", "--help"]),
        patch("ai_governance.frugality.cli.main", return_value=0) as mock_frugal,
    ):
        assert main() == 0
        mock_frugal.assert_called_once()


def test_cli_dispatch_statusline() -> None:
    with (
        patch.object(sys, "argv", ["governance", "statusline"]),
        patch("ai_governance.telemetry.statusline.main", return_value=0) as mock_status,
    ):
        assert main() == 0
        mock_status.assert_called_once()


def test_cli_dispatch_ritmo() -> None:
    with (
        patch.object(sys, "argv", ["governance", "ritmo", "--budget", "100"]),
        patch("ai_governance.telemetry.cli.main", return_value=0) as mock_telemetry,
    ):
        assert main() == 0
        mock_telemetry.assert_called_once()


def test_cli_dispatch_progress() -> None:
    with (
        patch.object(sys, "argv", ["governance", "progress", "list"]),
        patch("ai_governance.session.cli.main", return_value=0) as mock_session,
    ):
        assert main() == 0
        mock_session.assert_called_once()
