"""
Integration tests for process execution and command runner safety.
"""

from devscripts.core.process import run_command_safe

def test_run_command_safe_args_list():
    code, stdout, stderr = run_command_safe(["echo", "devscripts-test"])
    assert code == 0
    assert "devscripts-test" in stdout
    assert stderr == ""

def test_run_command_safe_missing_binary():
    code, _, _ = run_command_safe(["non_existent_binary_xyz_123"])
    assert code == 127
