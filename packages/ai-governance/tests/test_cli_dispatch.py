from __future__ import annotations

import sys
from types import ModuleType
from unittest.mock import MagicMock, patch

from ai_governance.cli import main


def _mock_spec() -> tuple[dict[str, ModuleType], MagicMock]:
    spec_mod = ModuleType("spec")
    cli_mod = ModuleType("spec.cli")
    spec_mod.cli = cli_mod
    mock_main = MagicMock(return_value=0)
    cli_mod.main = mock_main
    return {"spec": spec_mod, "spec.cli": cli_mod}, mock_main


def _mock_workspace() -> tuple[dict[str, ModuleType], MagicMock, MagicMock]:
    we_mod = ModuleType("workspace_engine")
    cfg_pkg = ModuleType("workspace_engine.config")
    init_cfg = ModuleType("workspace_engine.config.init_config")
    cli_pkg = ModuleType("workspace_engine.cli")
    cli_main = ModuleType("workspace_engine.cli.main")

    mock_cfg = MagicMock(return_value=0)
    mock_doctor = MagicMock(return_value=0)
    init_cfg.run_config_init = mock_cfg
    cli_main.doctor_check = mock_doctor

    we_mod.config = cfg_pkg
    we_mod.cli = cli_pkg
    cfg_pkg.init_config = init_cfg
    cli_pkg.main = cli_main

    return (
        {
            "workspace_engine": we_mod,
            "workspace_engine.config": cfg_pkg,
            "workspace_engine.config.init_config": init_cfg,
            "workspace_engine.cli": cli_pkg,
            "workspace_engine.cli.main": cli_main,
        },
        mock_cfg,
        mock_doctor,
    )


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
    modules, mock_cfg, _ = _mock_workspace()
    with (
        patch.object(sys, "argv", ["governance", "config", "init", "--local", "--yes"]),
        patch.dict(sys.modules, modules),
    ):
        assert main() == 0
        mock_cfg.assert_called_once_with(["--local", "--yes"])


def test_cli_dispatch_agent() -> None:
    modules, mock_spec = _mock_spec()
    with (
        patch.object(sys, "argv", ["governance", "agent", "install", "antigravity"]),
        patch.dict(sys.modules, modules),
    ):
        assert main() == 0
        mock_spec.assert_called_once_with(["agent", "install", "antigravity"])


def test_cli_dispatch_doctor() -> None:
    s_mods, mock_spec = _mock_spec()
    w_mods, _, mock_wdoc = _mock_workspace()
    all_mods = {**s_mods, **w_mods}
    with (
        patch.object(sys, "argv", ["governance", "doctor"]),
        patch.dict(sys.modules, all_mods),
    ):
        assert main() == 0
        mock_spec.assert_called_once_with(["doctor"])
        mock_wdoc.assert_called_once()


def test_cli_dispatch_doctor_with_remaining_args() -> None:
    s_mods, mock_spec = _mock_spec()
    w_mods, _, mock_wdoc = _mock_workspace()
    all_mods = {**s_mods, **w_mods}
    with (
        patch.object(sys, "argv", ["governance", "doctor", "--json"]),
        patch.dict(sys.modules, all_mods),
    ):
        assert main() == 0
        mock_spec.assert_called_once_with(["doctor", "--json"])
        mock_wdoc.assert_not_called()


def test_cli_dispatch_audit() -> None:
    modules, mock_spec = _mock_spec()
    with (
        patch.object(sys, "argv", ["governance", "audit"]),
        patch.dict(sys.modules, modules),
    ):
        assert main() == 0
        mock_spec.assert_called_once_with(["audit"])


def test_cli_dispatch_audit_with_remaining_args() -> None:
    modules, mock_spec = _mock_spec()
    with (
        patch.object(sys, "argv", ["governance", "audit", "--json"]),
        patch.dict(sys.modules, modules),
    ):
        assert main() == 0
        mock_spec.assert_called_once_with(["audit", "--json"])


def test_cli_dispatch_config_missing_sibling(capsys) -> None:
    with (
        patch.object(sys, "argv", ["governance", "config", "init"]),
        patch.dict(sys.modules, {"workspace_engine.config.init_config": None}),
    ):
        assert main() == 1
        captured = capsys.readouterr()
        assert "Notice:" in captured.out
        assert "workspace" in captured.out


def test_cli_dispatch_agent_missing_sibling(capsys) -> None:
    with (
        patch.object(sys, "argv", ["governance", "agent", "install"]),
        patch.dict(sys.modules, {"spec.cli": None}),
    ):
        assert main() == 1
        captured = capsys.readouterr()
        assert "Notice:" in captured.out
        assert "spec" in captured.out


def test_cli_dispatch_doctor_missing_spec(capsys) -> None:
    with (
        patch.object(sys, "argv", ["governance", "doctor"]),
        patch.dict(sys.modules, {"spec.cli": None}),
    ):
        assert main() == 1
        captured = capsys.readouterr()
        assert "Notice:" in captured.out


def test_cli_dispatch_doctor_missing_workspace(capsys) -> None:
    with (
        patch.object(sys, "argv", ["governance", "doctor"]),
        patch.dict(sys.modules, {"workspace_engine.cli.main": None}),
    ):
        assert main() == 1
        captured = capsys.readouterr()
        assert "Notice:" in captured.out


def test_cli_dispatch_audit_missing_sibling(capsys) -> None:
    with (
        patch.object(sys, "argv", ["governance", "audit"]),
        patch.dict(sys.modules, {"spec.cli": None}),
    ):
        assert main() == 1
        captured = capsys.readouterr()
        assert "Notice:" in captured.out
        assert "spec" in captured.out
