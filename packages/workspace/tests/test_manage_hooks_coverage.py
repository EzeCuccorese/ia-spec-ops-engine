"""
Additional coverage tests for workspace_engine.cli.manage_hooks.

Covers the human-readable (non agent-mode) status rendering, sys.argv-derived
argv parsing, the install failure branch, and the defensive fallback
return at the end of main().
"""

from __future__ import annotations

import argparse
from unittest.mock import patch

from workspace_engine.cli import manage_hooks


def test_scope_row_human_mode_active_and_executable():
    status = {
        "hook_exists": True,
        "is_executable": True,
        "is_active": True,
        "configured_command": "/repo/.githooks",
        "hook_path": "/repo/.git/hooks/pre-push",
    }
    row = manage_hooks._scope_row("Local (Repo)", status, agent_mode=False)
    assert "Executable" in row[3]
    assert "ACTIVE" in row[4]


def test_scope_row_human_mode_no_exec_and_inactive():
    status = {
        "hook_exists": True,
        "is_executable": False,
        "is_active": False,
        "configured_command": None,
        "hook_path": "/repo/.git/hooks/pre-push",
    }
    row = manage_hooks._scope_row("Global (System)", status, agent_mode=False)
    assert "No exec" in row[3]
    assert "Inactive" in row[4]
    assert "Not configured" in row[2]


def test_scope_row_human_mode_not_installed():
    status = {
        "hook_exists": False,
        "is_executable": False,
        "is_active": False,
        "configured_command": None,
        "hook_path": "/repo/.git/hooks/pre-push",
    }
    row = manage_hooks._scope_row("Local (Repo)", status, agent_mode=False)
    assert "Not installed" in row[3]


def test_scope_row_agent_mode_active_and_executable():
    status = {
        "hook_exists": True,
        "is_executable": True,
        "is_active": True,
        "configured_command": "/repo/.githooks",
        "hook_path": "/repo/.git/hooks/pre-push",
    }
    row = manage_hooks._scope_row("Local (Repo)", status, agent_mode=True)
    assert row[3] == "Executable"
    assert row[4] == "ACTIVE"


def test_scope_row_agent_mode_no_exec_and_inactive():
    status = {
        "hook_exists": True,
        "is_executable": False,
        "is_active": False,
        "configured_command": None,
        "hook_path": "/repo/.git/hooks/pre-push",
    }
    row = manage_hooks._scope_row("Global (System)", status, agent_mode=True)
    assert row[3] == "No exec"
    assert row[4] == "Inactive"
    assert row[2] == "Not configured"


def test_scope_row_agent_mode_not_installed():
    status = {
        "hook_exists": False,
        "is_executable": False,
        "is_active": False,
        "configured_command": None,
        "hook_path": "/repo/.git/hooks/pre-push",
    }
    row = manage_hooks._scope_row("Local (Repo)", status, agent_mode=True)
    assert row[3] == "Not installed"


@patch("sys.argv", ["ws", "hooks", "status"])
@patch("workspace_engine.cli.manage_hooks.render_hooks_status")
def test_main_uses_sys_argv_and_strips_hooks_prefix(mock_render):
    rc = manage_hooks.main(None)
    assert rc == 0
    mock_render.assert_called_once()


@patch("sys.argv", ["ws"])
@patch("workspace_engine.cli.manage_hooks.render_hooks_status")
def test_main_uses_sys_argv_without_hooks_prefix(mock_render):
    rc = manage_hooks.main(None)
    assert rc == 0
    mock_render.assert_called_once()


def test_main_install_failure_returns_1(capsys):
    with patch(
        "workspace_engine.cli.manage_hooks.install_git_hooks",
        return_value={"success": False, "message": "disk full"},
    ):
        rc = manage_hooks.main(["install"])
        assert rc == 1
    assert "Error installing Git hook: disk full" in capsys.readouterr().err


def test_main_install_without_config_hooks_reports_the_reason(tmp_path, capsys):
    with patch("workspace_engine.services.git_hooks.supports_config_hooks", return_value=False):
        rc = manage_hooks.main(["install", "--dir", str(tmp_path)])
    assert rc == 1
    err = capsys.readouterr().err
    assert "does not support config-based hooks" in err
    assert "None" not in err


def test_main_install_success_returns_0():
    with patch(
        "workspace_engine.cli.manage_hooks.install_git_hooks",
        return_value={"success": True, "hook_path": "/repo/.git/hooks/pre-push"},
    ):
        rc = manage_hooks.main(["install"])
        assert rc == 0


def test_main_uninstall_success_returns_0(capsys):
    with patch(
        "workspace_engine.cli.manage_hooks.uninstall_git_hooks",
        return_value={"success": True, "message": "Local hook.workspace-gate removed."},
    ):
        rc = manage_hooks.main(["uninstall"])
        assert rc == 0
    assert "Local hook.workspace-gate removed." in capsys.readouterr().out


def test_main_fallback_return_for_unrecognized_action():
    """The final `return 0` guards against an action falling through all
    branches; argparse's subparser choices make this unreachable via the
    CLI, so we exercise it directly by feeding main() a crafted namespace."""
    fake_args = argparse.Namespace(action="unknown-future-action", dir=None)
    with patch(
        "workspace_engine.cli.manage_hooks.argparse.ArgumentParser.parse_args",
        return_value=fake_args,
    ):
        rc = manage_hooks.main(["whatever"])
        assert rc == 0
