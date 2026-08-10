"""
Integration tests for installer dry-run execution.
"""

from devscripts.core.process import run_command_safe

def test_install_script_dry_run():
    code, stdout, _ = run_command_safe(["python3", "install.py", "--dry-run"])
    assert code == 0
    assert "[DRY-RUN]" in stdout

def test_uninstall_script_dry_run():
    code, stdout, _ = run_command_safe(["python3", "uninstall.py", "--dry-run"])
    assert code == 0
    assert "[DRY-RUN]" in stdout
