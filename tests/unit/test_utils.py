import sys
import subprocess
from unittest.mock import patch, MagicMock
import pytest
from devscripts.core.utils import log_info, log_success, log_warning, log_error, run_command, Color

def test_log_info(capsys):
    log_info("test info")
    captured = capsys.readouterr()
    assert "test info" in captured.out
    assert Color.BLUE in captured.out

def test_log_success(capsys):
    log_success("test success")
    captured = capsys.readouterr()
    assert "test success" in captured.out
    assert Color.GREEN in captured.out

def test_log_warning(capsys):
    log_warning("test warning")
    captured = capsys.readouterr()
    assert "test warning" in captured.out
    assert Color.YELLOW in captured.out

def test_log_error(capsys):
    log_error("test error")
    captured = capsys.readouterr()
    assert "test error" in captured.err
    assert Color.RED in captured.err

def test_run_command_success():
    with patch('subprocess.run') as mock_run:
        mock_result = MagicMock()
        mock_result.stdout = "output-content"
        mock_result.stderr = ""
        mock_result.returncode = 0
        mock_run.return_value = mock_result
        
        res = run_command("echo hello", show_command=True)
        assert res == "output-content"
        mock_run.assert_called_once()

def test_run_command_failure_check_true():
    with patch('subprocess.run') as mock_run:
        mock_run.side_effect = subprocess.CalledProcessError(
            returncode=1,
            cmd="false",
            stderr="some error"
        )
        with pytest.raises(subprocess.CalledProcessError):
            run_command("false", check=True)

def test_run_command_failure_check_false():
    with patch('subprocess.run') as mock_run:
        mock_run.side_effect = subprocess.CalledProcessError(
            returncode=1,
            cmd="false",
            stderr="some error"
        )
        res = run_command("false", check=False)
        assert res is None

def test_run_command_unexpected_error():
    with patch('subprocess.run') as mock_run:
        mock_run.side_effect = Exception("unexpected error")
        with pytest.raises(Exception):
            run_command("dummy", check=True)
        res = run_command("dummy", check=False)
        assert res is None
