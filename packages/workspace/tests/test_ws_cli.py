"""
Tests for the unified `ws` entry point and its subcommands.
"""

from unittest.mock import patch

import pytest
from workspace_engine.cli.main import doctor_check, main


def test_doctor_check_reports_tools_and_hooks(capsys):
    doctor_check()
    out = capsys.readouterr().out
    assert "git" in out
    assert "git-hooks" in out


@patch("sys.argv", ["ws", "config", "init", "--local", "--yes"])
def test_ws_main_config():
    with (
        patch("workspace_engine.config.init_config.run_config", return_value=0) as mock_cfg,
        pytest.raises(SystemExit) as exc,
    ):
        main()
    assert exc.value.code == 0
    mock_cfg.assert_called_once()
    called_args = mock_cfg.call_args.args[0]
    assert called_args.config_command == "init"
    assert called_args.local is True
    assert called_args.non_interactive is True
