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


def test_cli_dispatch_jira() -> None:
    with (
        patch.object(sys, "argv", ["governance", "jira", "help"]),
        patch("ai_governance.tools.jira.main", return_value=0) as mock_jira,
    ):
        assert main() == 0
        mock_jira.assert_called_once()


def test_cli_dispatch_confluence() -> None:
    with (
        patch.object(sys, "argv", ["governance", "confluence", "help"]),
        patch("ai_governance.tools.confluence.main", return_value=0) as mock_confluence,
    ):
        assert main() == 0
        mock_confluence.assert_called_once()


def test_cli_dispatch_config() -> None:
    with (
        patch.object(sys, "argv", ["governance", "config", "init", "--local", "--yes"]),
        patch("workspace_engine.config.init_config.run_config_init", return_value=0) as mock_cfg,
    ):
        assert main() == 0
        mock_cfg.assert_called_once_with(["--local", "--yes"])


def test_cli_dispatch_agent() -> None:
    with (
        patch.object(sys, "argv", ["governance", "agent", "install", "antigravity"]),
        patch("spec.cli.main", return_value=0) as mock_agent,
    ):
        assert main() == 0
        mock_agent.assert_called_once_with(["agent", "install", "antigravity"])


def test_cli_dispatch_doctor() -> None:
    with (
        patch.object(sys, "argv", ["governance", "doctor"]),
        patch("spec.cli.run_doctor", return_value=0) as mock_sdoc,
        patch("workspace_engine.cli.main.doctor_check") as mock_wdoc,
    ):
        assert main() == 0
        mock_sdoc.assert_called_once()
        mock_wdoc.assert_called_once()


def test_cli_dispatch_audit() -> None:
    with (
        patch.object(sys, "argv", ["governance", "audit"]),
        patch("spec.cli.run_audit", return_value=0) as mock_audit,
    ):
        assert main() == 0
        mock_audit.assert_called_once()

