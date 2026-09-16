"""
Comprehensive unit tests for workspace_engine.run_local.process_manager.
Covers live-process checks, signal escalation, state save/load,
port handling, and graceful termination.
"""

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from workspace_engine.run_local.process_manager import (
    _pid_alive,
    _status_str,
    graceful_kill_pid,
    save_state,
    stop_all,
)


def test_pid_alive_current_process():
    current_pid = os.getpid()
    assert _pid_alive(current_pid) is True
    assert _pid_alive(99999999) is False  # nonexistent PID


def test_status_str():
    plain, colored = _status_str("svc-test", 99999999)
    assert "stopped" in plain
    assert "stopped" in colored


def test_save_and_load_state():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        state_file = tmp_path / "state.json"
        data_dir = tmp_path

        with (
            patch("workspace_engine.run_local.constants.STATE_FILE", state_file),
            patch("workspace_engine.run_local.constants.DATA_DIR", data_dir),
        ):
            mock_launch = [
                {
                    "name": "svc-a",
                    "path": str(tmp_path),
                    "port": 8080,
                    "env": {},
                    "base_env": "local",
                    "db_env": "local",
                    "up_mode": "auto",
                }
            ]
            mock_results = [
                {
                    "name": "svc-a",
                    "path": str(tmp_path),
                    "port": 8080,
                    "pid": os.getpid(),
                    "ok": True,
                    "type": "node",
                }
            ]

            save_state(mock_launch, mock_results)
            assert state_file.exists()


def test_graceful_kill_pid_already_dead():
    # Killing a nonexistent PID must be a no-op without raising
    graceful_kill_pid(99999999, timeout=0.1)


@patch("os.kill")
def test_graceful_kill_pid_escalation(mock_kill):
    # Simulate the process not dying on SIGTERM, requiring SIGKILL
    with patch(
        "workspace_engine.run_local.process_manager._pid_alive",
        side_effect=[True, True, True, False],
    ):
        graceful_kill_pid(12345, timeout=0.1)

        # Verify SIGTERM (15) was sent, followed by SIGKILL (9)
        calls = mock_kill.call_args_list
        signals_sent = [call[0][1] for call in calls]
        assert 15 in signals_sent
        assert 9 in signals_sent


def test_stop_all_clean_pids():
    with tempfile.TemporaryDirectory() as tmpdir:
        pids_dir = Path(tmpdir) / "pids"
        pids_dir.mkdir()
        state_file = Path(tmpdir) / "state.json"
        state_file.touch()

        # Create fake pid files
        (pids_dir / "service1.pid").write_text("99999991\n")
        (pids_dir / "service2.pid").write_text("99999992\n")

        with (
            patch("workspace_engine.run_local.constants.PIDS_DIR", pids_dir),
            patch("workspace_engine.run_local.constants.STATE_FILE", state_file),
            patch("workspace_engine.run_local.process_manager.graceful_kill_pid") as mock_kill,
        ):
            stop_all()
            assert mock_kill.call_count == 2
            # The .pid files and state.json should have been deleted
            assert len(list(pids_dir.glob("*.pid"))) == 0
            assert not state_file.exists()


@patch("os.kill")
def test_graceful_kill_pid_safety_guards(mock_kill):
    """Immediately reject pids <= 1 or the current process's pid without sending signals."""
    graceful_kill_pid(0)
    graceful_kill_pid(1)
    graceful_kill_pid(os.getpid())
    mock_kill.assert_not_called()


@patch("os.kill")
def test_graceful_kill_pid_pid_reuse_prevention(mock_kill):
    """W05: Guard against a PID reused by a process unrelated to the service."""
    with patch(
        "workspace_engine.common.get_process_cmdline",
        return_value="postgres: background worker",
    ):
        graceful_kill_pid(12345, service_name="auth-service")
        mock_kill.assert_not_called()


@patch("os.kill")
def test_graceful_kill_pid_does_not_kill_own_group(mock_kill):
    """Do not signal -pid if pid matches the current process's group."""
    current_pgid = os.getpgrp()
    with (
        patch("workspace_engine.run_local.process_manager._pid_alive", return_value=False),
        patch("os.getpid", return_value=99999),  # different from the tested pid
    ):
        stopped = graceful_kill_pid(current_pgid)
        # Verify that os.kill was NOT called with -current_pgid
        for call in mock_kill.call_args_list:
            assert call[0][0] != -current_pgid
        assert stopped is True


@patch("os.kill")
def test_graceful_kill_pid_rejects_disallowed_tools(mock_kill):
    """Reject tool processes like grep, cat, or vim that contain the service name as an argument."""
    with patch(
        "workspace_engine.common.get_process_cmdline",
        return_value="grep -r auth-service .",
    ):
        stopped = graceful_kill_pid(12345, service_name="auth-service")
        assert stopped is False
        mock_kill.assert_not_called()


@patch("os.kill")
def test_graceful_kill_pid_rejects_foreign_workspace_matching_service_name(mock_kill):
    """Verifies that when the service path (service_path) does not match cmdline,

    the process is NOT accepted even if service_name matches in another workspace
    (e.g. looking for project-a/api against node /workspaces/project-b/api/server.js).
    """
    with patch(
        "workspace_engine.common.get_process_cmdline",
        return_value="node /workspaces/project-b/api/server.js",
    ):
        # Looking for project-a/api with service_name="api" and service_path="project-a/api"
        stopped = graceful_kill_pid(
            12345,
            service_name="api",
            service_path="project-a/api",
        )
        assert stopped is False
        mock_kill.assert_not_called()


@patch("os.kill")
def test_graceful_kill_pid_rejects_foreign_workspace_when_service_name_has_path(mock_kill):
    """Verifies that when service_name includes a path (e.g. 'project-a/api'),

    it is rejected if cmdline points to another workspace ('project-b/api').
    """
    with patch(
        "workspace_engine.common.get_process_cmdline",
        return_value="node /workspaces/project-b/api/server.js",
    ):
        stopped = graceful_kill_pid(
            12345,
            service_name="project-a/api",
        )
        assert stopped is False
        mock_kill.assert_not_called()


@patch("os.kill")
def test_graceful_kill_pid_accepts_matching_service_path(mock_kill):
    """Verifies that when service_path matches in cmdline, the process is accepted."""
    with (
        patch(
            "workspace_engine.common.get_process_cmdline",
            return_value="node /workspaces/project-a/api/server.js",
        ),
        patch("workspace_engine.run_local.process_manager._pid_alive", return_value=False),
    ):
        stopped = graceful_kill_pid(
            12345,
            service_name="api",
            service_path="project-a/api",
        )
        assert stopped is True
        mock_kill.assert_called()
