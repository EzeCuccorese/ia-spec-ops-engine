"""The gate's timeout must take down the whole process group, not just the main command."""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest
from workspace_engine.services.git_hooks import generate_canonical_pre_push_script

pytestmark = pytest.mark.skipif(shutil.which("perl") is None, reason="watchdog needs perl")


def _watchdog() -> str:
    script = generate_canonical_pre_push_script()
    body = script.split("# --- watchdog:start ---\n", 1)[1].split("# --- watchdog:end ---", 1)[0]
    return body.split("QG_WATCHDOG='", 1)[1].rsplit("'", 1)[0]


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


@pytest.mark.parametrize(
    ("secs", "parent", "expected_rc"),
    [
        (1, "sleep 30", 124),  # parent hangs: timeout kills parent and child
        (30, "true", 0),  # parent exits fine but leaves a child behind
    ],
)
def test_watchdog_leaves_no_orphans(
    tmp_path: Path, secs: int, parent: str, expected_rc: int
) -> None:
    pid_file = tmp_path / "child.pid"
    command = f"sleep 60 & echo $! > {pid_file}; {parent}"

    started = time.monotonic()
    rc = subprocess.run(["perl", "-e", _watchdog(), str(secs), "sh", "-c", command]).returncode

    assert rc == expected_rc
    assert time.monotonic() - started < 15
    child = int(pid_file.read_text())
    deadline = time.monotonic() + 3
    while _alive(child) and time.monotonic() < deadline:
        time.sleep(0.1)
    assert not _alive(child), "child process outlived the gate"


def test_watchdog_propagates_the_command_exit_code() -> None:
    rc = subprocess.run(["perl", "-e", _watchdog(), "30", "sh", "-c", "exit 3"]).returncode
    assert rc == 3
