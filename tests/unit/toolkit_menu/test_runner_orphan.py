"""Regression test for run_embedded's child-process handling on exceptions.

subprocess.Popen's context manager does NOT terminate the child when the
`with` block raises — it only closes pipes and calls wait() (blocking
indefinitely on a long-running child). If on_line/on_start raises inside
run_embedded, the child must be terminated (not left running / not left
blocking the caller forever) before the exception propagates.
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

_TOOLKIT_DIR = Path(__file__).resolve().parents[3]
_MENU_DIR = _TOOLKIT_DIR / "devscripts" / "services" / "toolkit_menu"
sys.path.insert(0, str(_MENU_DIR))


from runner import run_embedded  # noqa: E402


def test_run_embedded_terminates_child_when_on_line_raises() -> None:
    captured: dict[str, subprocess.Popen] = {}

    def on_start(proc: subprocess.Popen) -> None:
        captured["proc"] = proc

    def on_line(_: str) -> None:
        raise RuntimeError("boom")

    # The child must emit a line BEFORE its long sleep, so on_line fires (and
    # raises) well before the child would exit on its own. This isolates the
    # bug: does run_embedded terminate the child promptly on exception, or
    # does it block until the child's full 30s sleep elapses?
    t0 = time.monotonic()
    try:
        run_embedded(
            ["bash", "-c", "echo first; sleep 30; echo done"],
            Path("."),
            on_line,
            on_start=on_start,
        )
    except RuntimeError:
        pass
    else:
        raise AssertionError("expected RuntimeError to propagate")
    elapsed = time.monotonic() - t0

    proc = captured["proc"]
    # Give the OS a brief moment to reap the terminated process.
    proc.wait(timeout=5)
    assert proc.poll() is not None, "child process was left running (orphaned)"
    # Must not have blocked for anywhere near the child's full 30s sleep.
    assert elapsed < 10, f"run_embedded blocked {elapsed:.1f}s instead of terminating the child"


def test_run_embedded_terminates_child_when_on_start_raises() -> None:
    captured: dict[str, subprocess.Popen] = {}

    def on_start(proc: subprocess.Popen) -> None:
        captured["proc"] = proc
        raise RuntimeError("boom in on_start")

    def on_line(_: str) -> None:
        pass

    try:
        run_embedded(
            ["bash", "-c", "sleep 30; echo done"],
            Path("."),
            on_line,
            on_start=on_start,
        )
    except RuntimeError:
        pass
    else:
        raise AssertionError("expected RuntimeError to propagate")

    proc = captured["proc"]
    proc.wait(timeout=5)
    assert proc.poll() is not None, "child process was left running (orphaned)"
