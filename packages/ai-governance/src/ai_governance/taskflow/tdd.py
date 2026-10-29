"""Mandatory test-first evidence: the same command fails by assertion, then passes.

The red run must fail on an assertion, not on a syntax, import or collection error, and
the green run must happen on different code (the fix) and is valid only for the current
``code_stamp``. Skipping requires the human's ``tdd-skip`` approval.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from .models import JsonDict, Task, now_iso

NOT_AN_ASSERTION = re.compile(
    r"SyntaxError|IndentationError|ImportError|ModuleNotFoundError|ERROR collecting|"
    r"errors? during collection|command not found|No such file or directory|"
    r"Cannot find module|TS\d{4}:"
)
# A red run must show a failing test, not just a nonzero exit (``false`` fails too).
ASSERTION_FAILURE = re.compile(
    r"AssertionError|assert |\bFAILED\b|\bFAIL\b|failures?=|\d+ failed|Expected|expected .* (to|but)|"
    r"✕|✗|not ok \d|--- FAIL|panicked at|Failures:",
    re.IGNORECASE,
)
OUTPUT_TAIL = 4000
TEST_TIMEOUT = 1800
TIMEOUT_EXIT = 124  # same code as coreutils `timeout`


class TddError(ValueError):
    pass


def run_test(command: str, cwd: Path) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            command,
            shell=True,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=TEST_TIMEOUT,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return TIMEOUT_EXIT, f"Timed out after {TEST_TIMEOUT}s"
    return proc.returncode, (proc.stdout + proc.stderr)[-OUTPUT_TAIL:]


def red_record(command: str, exit_code: int, output: str, stamp_key: str) -> JsonDict:
    if exit_code == 0:
        raise TddError("The test passed: a red run must fail before the change")
    if NOT_AN_ASSERTION.search(output) or not ASSERTION_FAILURE.search(output):
        raise TddError(
            "The run did not fail on a test assertion (load/compile error, or no failing test "
            "in the output): fix the test first"
        )
    return {
        "cmd": command,
        "exit": exit_code,
        "stamp": stamp_key,
        "at": now_iso(),
        "tail": output[-800:],
    }


def green_record(task: Task, command: str, exit_code: int, output: str) -> JsonDict:
    stamp_key = task.stamp_key
    red = task.tdd.get("red")
    if not red:
        raise TddError("No red run recorded: run `taskflow tdd red --cmd ...` before changing code")
    if red.get("cmd") != command:
        raise TddError(f"The green run must use the red command: {red.get('cmd')}")
    if red.get("stamp") == stamp_key:
        raise TddError("The code has not changed since the red run")
    if exit_code != 0:
        raise TddError("The test still fails")
    return {"cmd": command, "exit": 0, "stamp": stamp_key, "at": now_iso(), "tail": output[-800:]}


def unmet(task: Task, stamp_key: str) -> list[str]:
    """TDD is mandatory: only a skip the user approved for this task replaces red/green."""
    if task.tdd.get("skip"):
        return []
    if not task.tdd.get("red"):
        return ["TDD: no red run (`taskflow tdd red --cmd '<test command>'` before the change)"]
    green = task.tdd.get("green")
    if not green:
        return ["TDD: no green run (`taskflow tdd green --cmd '<same command>'`)"]
    if green.get("stamp") != stamp_key:
        return ["TDD: the green run is stale (code changed): run `taskflow tdd green` again"]
    return []
