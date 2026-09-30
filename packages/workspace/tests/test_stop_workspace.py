"""
Unit tests for workspace_engine.cli.stop_workspace.

Filesystem effects use tmp_path; `os.kill`/`os.killpg`/`os.getpgid` and
`get_process_cmdline` are mocked so no real process is ever signaled, and
`time.sleep` is patched to a no-op to keep the tests fast and deterministic.
"""

from __future__ import annotations

import json
import os
import signal
from pathlib import Path
from unittest.mock import patch

import pytest
from workspace_engine.cli import stop_workspace as sw

# ---------------------------------------------------------------------------
# verify_process_identity
# ---------------------------------------------------------------------------


def test_verify_process_identity_no_cmdline_returns_false(tmp_path: Path) -> None:
    with patch("workspace_engine.cli.stop_workspace.get_process_cmdline", return_value=""):
        assert sw.verify_process_identity(123, "repo-a", tmp_path) is False


def test_verify_process_identity_disallowed_binary_returns_false(tmp_path: Path) -> None:
    with patch("workspace_engine.cli.stop_workspace.get_process_cmdline", return_value="grep foo"):
        assert sw.verify_process_identity(123, "repo-a", tmp_path) is False


def test_verify_process_identity_expected_cmd_match_returns_true(tmp_path: Path) -> None:
    with patch(
        "workspace_engine.cli.stop_workspace.get_process_cmdline",
        return_value="node server.js",
    ):
        assert (
            sw.verify_process_identity(
                123, "repo-a", tmp_path, expected_cmd="node server.js --port 3000"
            )
            is True
        )


def test_verify_process_identity_workspace_path_match_returns_true(tmp_path: Path) -> None:
    cmdline = f"node {tmp_path}/repositories/repo-a/server.js"
    with patch("workspace_engine.cli.stop_workspace.get_process_cmdline", return_value=cmdline):
        assert sw.verify_process_identity(123, "repo-a", tmp_path) is True


def test_verify_process_identity_no_match_returns_false(tmp_path: Path) -> None:
    with patch(
        "workspace_engine.cli.stop_workspace.get_process_cmdline",
        return_value="node /some/unrelated/path/server.js",
    ):
        assert sw.verify_process_identity(123, "repo-a", tmp_path) is False


# ---------------------------------------------------------------------------
# stop_workspace
# ---------------------------------------------------------------------------


def test_stop_workspace_no_run_pids_dir(tmp_path: Path) -> None:
    assert sw.stop_workspace(start_dir=tmp_path) == 0


def test_stop_workspace_no_pid_files(tmp_path: Path) -> None:
    (tmp_path / ".ai-toolkit" / "run-pids").mkdir(parents=True)
    assert sw.stop_workspace(start_dir=tmp_path) == 0


def test_stop_workspace_unreadable_pid_file_is_removed(tmp_path: Path) -> None:
    pids_dir = tmp_path / ".ai-toolkit" / "run-pids"
    pids_dir.mkdir(parents=True)
    pid_file = pids_dir / "repo-a.pid"
    pid_file.write_text("123")

    with patch.object(Path, "read_text", side_effect=OSError("unreadable")):
        rc = sw.stop_workspace(start_dir=tmp_path)
    assert rc == 0
    assert not pid_file.exists()


@pytest.mark.parametrize(
    "content",
    ["{not valid json", "not-a-number\nsome cmd\n", "0", "   \n"],
    ids=["malformed-json", "non-numeric-pid", "zero-pid", "empty"],
)
def test_stop_workspace_removes_unusable_pid_file(tmp_path: Path, content: str) -> None:
    pids_dir = tmp_path / ".ai-toolkit" / "run-pids"
    pids_dir.mkdir(parents=True)
    pid_file = pids_dir / "repo-a.pid"
    pid_file.write_text(content)

    rc = sw.stop_workspace(start_dir=tmp_path)
    assert rc == 0
    assert not pid_file.exists()


def test_stop_workspace_process_not_running_is_removed(tmp_path: Path) -> None:
    pids_dir = tmp_path / ".ai-toolkit" / "run-pids"
    pids_dir.mkdir(parents=True)
    pid_file = pids_dir / "repo-a.pid"
    pid_file.write_text("4242")

    with patch("os.kill", side_effect=OSError("no such process")):
        rc = sw.stop_workspace(start_dir=tmp_path)
    assert rc == 0
    assert not pid_file.exists()


def test_stop_workspace_identity_mismatch_is_removed(tmp_path: Path) -> None:
    pids_dir = tmp_path / ".ai-toolkit" / "run-pids"
    pids_dir.mkdir(parents=True)
    pid_file = pids_dir / "repo-a.pid"
    pid_file.write_text("4242")

    with (
        patch("os.kill", return_value=None),  # alive
        patch(
            "workspace_engine.cli.stop_workspace.verify_process_identity",
            return_value=False,
        ),
    ):
        rc = sw.stop_workspace(start_dir=tmp_path)
    assert rc == 0
    assert not pid_file.exists()


def test_stop_workspace_json_pid_file_without_repo_key(tmp_path: Path) -> None:
    pids_dir = tmp_path / ".ai-toolkit" / "run-pids"
    pids_dir.mkdir(parents=True)
    pid_file = pids_dir / "repo-a.pid"
    pid_file.write_text(json.dumps({"pid": 4242, "cmdline": "node server.js"}))

    with patch("os.kill", side_effect=OSError("not running")):
        rc = sw.stop_workspace(start_dir=tmp_path)
    assert rc == 0
    assert not pid_file.exists()


def test_stop_workspace_json_pid_file_with_repo_override(tmp_path: Path) -> None:
    pids_dir = tmp_path / ".ai-toolkit" / "run-pids"
    pids_dir.mkdir(parents=True)
    pid_file = pids_dir / "generic.pid"
    pid_file.write_text(json.dumps({"pid": 4242, "cmdline": "node server.js", "repo": "repo-real"}))

    def fake_kill(pid: int, s: int) -> None:
        if s == 0:
            raise OSError("terminated instantly")
        return None

    with (
        patch("os.kill", side_effect=fake_kill),
        patch(
            "workspace_engine.cli.stop_workspace.verify_process_identity",
            return_value=True,
        ),
        patch("os.getpgid", side_effect=OSError("no pgid")),
    ):
        rc = sw.stop_workspace(start_dir=tmp_path, timeout=0.05)
    assert rc == 0
    assert not pid_file.exists()


def test_stop_workspace_terminates_quickly_on_sigterm(tmp_path: Path) -> None:
    pids_dir = tmp_path / ".ai-toolkit" / "run-pids"
    pids_dir.mkdir(parents=True)
    pid_file = pids_dir / "repo-a.pid"
    pid_file.write_text("4242\nnode server.js\n")

    state = {"signaled": False}

    def fake_kill(pid: int, s: int) -> None:
        if s == signal.SIGTERM:
            state["signaled"] = True
            return None
        if s == 0:
            if state["signaled"]:
                raise OSError("terminated")  # dies right after receiving SIGTERM
            return None  # alive for the pre-signal liveness check
        return None

    with (
        patch("os.kill", side_effect=fake_kill),
        patch(
            "workspace_engine.cli.stop_workspace.verify_process_identity",
            return_value=True,
        ),
        patch("os.getpgid", return_value=os.getpgrp()),  # same as our own pgid -> no pg signal
        patch("time.sleep", return_value=None),
    ):
        rc = sw.stop_workspace(start_dir=tmp_path, timeout=0.05)
    assert rc == 0
    assert not pid_file.exists()


def test_stop_workspace_escalates_to_sigkill_and_terminates(tmp_path: Path) -> None:
    pids_dir = tmp_path / ".ai-toolkit" / "run-pids"
    pids_dir.mkdir(parents=True)
    pid_file = pids_dir / "repo-a.pid"
    pid_file.write_text("4242\nnode server.js\n")

    state = {"killed": False}

    def fake_kill(pid: int, s: int) -> None:
        if s == 0:
            if state["killed"]:
                raise OSError("terminated after SIGKILL")
            return None  # still alive during the SIGTERM grace window
        if s == signal.SIGKILL:
            state["killed"] = True
        return None

    # A fake clock advancing 10ms per call keeps the SIGTERM grace window and
    # the SIGKILL wait deterministic regardless of machine load.
    clock = {"now": 0.0}

    def fake_time() -> float:
        clock["now"] += 0.01
        return clock["now"]

    # `os.getpgid` must return the pid itself (process is its own group leader)
    # and differ from our own pgid, to exercise the killpg branch.
    with (
        patch("os.kill", side_effect=fake_kill),
        patch("os.killpg", return_value=None) as mock_killpg,
        patch(
            "workspace_engine.cli.stop_workspace.verify_process_identity",
            return_value=True,
        ),
        patch("os.getpgid", return_value=4242),
        patch("time.sleep", return_value=None),
        patch("time.time", side_effect=fake_time),
    ):
        rc = sw.stop_workspace(start_dir=tmp_path, timeout=0.1)
    assert rc == 0
    assert not pid_file.exists()
    assert mock_killpg.called


def test_stop_workspace_never_terminates_logs_warning(tmp_path: Path) -> None:
    pids_dir = tmp_path / ".ai-toolkit" / "run-pids"
    pids_dir.mkdir(parents=True)
    pid_file = pids_dir / "repo-a.pid"
    pid_file.write_text("4242\nnode server.js\n")

    def fake_kill(pid: int, s: int) -> None:
        if s == 0:
            return None  # never dies
        return None

    with (
        patch("os.kill", side_effect=fake_kill),
        patch(
            "workspace_engine.cli.stop_workspace.verify_process_identity",
            return_value=True,
        ),
        patch("os.getpgid", side_effect=OSError("no pgid")),
        patch("time.sleep", return_value=None),
    ):
        rc = sw.stop_workspace(start_dir=tmp_path, timeout=0.03)
    assert rc == 0
    assert not pid_file.exists()


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def test_main_forwards_timeout_and_exit_code() -> None:
    with (
        patch("sys.argv", ["stop-workspace", "--timeout", "2.5"]),
        patch.object(sw, "stop_workspace", return_value=0) as mock_stop,
        pytest.raises(SystemExit) as exc,
    ):
        sw.main()
    assert exc.value.code == 0
    mock_stop.assert_called_once_with(timeout=2.5)
