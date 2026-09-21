"""
Unit tests for workspace_engine.common.subprocess (run_command, run_command_safe).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from workspace_engine.common.subprocess import run_command, run_command_safe, run_git


def test_run_command_success_string_command() -> None:
    output = run_command("echo hello")
    assert output == "hello"


def test_run_command_success_list_command() -> None:
    output = run_command(["echo", "hello world"])
    assert output == "hello world"


def test_run_command_capture_output_false() -> None:
    output = run_command(["true"], capture_output=False)
    assert output == ""


def test_run_command_show_command_prints(capsys: pytest.CaptureFixture[str]) -> None:
    run_command(["echo", "hi"], show_command=True)
    captured = capsys.readouterr()
    assert "Running:" in captured.out


def test_run_command_failure_check_false_returns_empty_output() -> None:
    # subprocess.run(check=False) does not raise on a non-zero exit code,
    # so run_command simply returns the (empty) captured stdout.
    result = run_command(["false"], check=False)
    assert result == ""


def test_run_command_failure_check_true_raises() -> None:
    with pytest.raises(subprocess.CalledProcessError):
        run_command(["false"], check=True)


def test_run_command_error_message_on_failure_check_true(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(subprocess.CalledProcessError):
        run_command(["false"], check=True, error_message="custom failure message")
    captured = capsys.readouterr()
    assert "custom failure message" in captured.err


def test_run_command_timeout_check_false() -> None:
    result = run_command(["sleep", "2"], check=False, timeout=0.05)
    assert result is None


def test_run_command_timeout_check_true_raises() -> None:
    with pytest.raises(subprocess.TimeoutExpired):
        run_command(["sleep", "2"], check=True, timeout=0.05)


def test_run_command_isolated_git_strips_git_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GIT_DIR", "/should/not/appear")
    output = run_command(["env"], isolated_git=True)
    assert output is not None
    assert "GIT_DIR=" not in output
    assert "GIT_CONFIG_GLOBAL=/dev/null" in output


def test_run_command_env_override() -> None:
    output = run_command(["env"], env={"MY_CUSTOM_VAR": "42"})
    assert output is not None
    assert "MY_CUSTOM_VAR=42" in output


def test_run_command_cwd(tmp_path: object) -> None:
    output = run_command(["pwd"], cwd=str(tmp_path))
    assert output == str(tmp_path)


def test_run_command_unexpected_error_check_false() -> None:
    result = run_command(["/nonexistent/binary/xyz"], check=False)
    assert result is None


def test_run_command_unexpected_error_check_true_raises() -> None:
    with pytest.raises(OSError):
        run_command(["/nonexistent/binary/xyz"], check=True)


def test_run_command_safe_success() -> None:
    rc, out, err = run_command_safe(["echo", "hi"])
    assert rc == 0
    assert out.strip() == "hi"
    assert err == ""


def test_run_command_safe_failure_returncode() -> None:
    rc, out, err = run_command_safe(["false"])
    assert rc != 0


def test_run_command_safe_timeout() -> None:
    rc, out, err = run_command_safe(["sleep", "2"], timeout=0.05)
    assert rc == 124
    assert "TimeoutExpired" in err


def test_run_command_safe_unexpected_error() -> None:
    rc, out, err = run_command_safe(["/nonexistent/binary/xyz"])
    assert rc == 1
    assert err


def test_run_command_safe_isolated_git(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GIT_DIR", "/should/not/appear")
    rc, out, _err = run_command_safe(["env"], isolated_git=True)
    assert rc == 0
    assert "GIT_DIR=" not in out
    assert "GIT_CONFIG_SYSTEM=/dev/null" in out


def test_run_command_safe_string_command() -> None:
    rc, out, _err = run_command_safe("echo from-string")
    assert rc == 0
    assert out.strip() == "from-string"


def test_run_command_safe_env_override() -> None:
    rc, out, _err = run_command_safe(["env"], env={"MY_SAFE_VAR": "7"})
    assert rc == 0
    assert "MY_SAFE_VAR=7" in out


def test_run_command_capture_output_false_called_process_error_skips_stderr_print(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # capture_output=False, check=True: CalledProcessError has no captured stderr to print.
    with pytest.raises(subprocess.CalledProcessError):
        run_command(["false"], capture_output=False, check=True)
    captured = capsys.readouterr()
    assert captured.err == ""


def test_run_command_called_process_error_prints_captured_stderr(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(subprocess.CalledProcessError):
        run_command(["ls", "/nonexistent/path/xyz"], check=True)
    captured = capsys.readouterr()
    assert captured.err.strip() != ""


def test_run_command_called_process_error_check_false_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # subprocess.run(check=False) never raises CalledProcessError on its own; this
    # exercises the defensive `return None` branch by forcing that (unreachable in
    # practice) condition directly.
    def raise_called_process_error(*_args: object, **_kwargs: object) -> None:
        raise subprocess.CalledProcessError(returncode=1, cmd=["ls"])

    monkeypatch.setattr(subprocess, "run", raise_called_process_error)
    result = run_command(["ls"], check=False)
    assert result is None


def test_run_command_unexpected_error_with_error_message(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(OSError):
        run_command(["/nonexistent/binary/xyz"], check=True, error_message="binary missing")
    captured = capsys.readouterr()
    assert "binary missing" in captured.err


def test_run_git_success(tmp_path: Path) -> None:
    subprocess.run(
        ["git", "init", "-b", "main", str(tmp_path)],
        check=True,
        capture_output=True,
    )
    result = run_git(tmp_path, "status", "--porcelain")
    assert result.returncode == 0
