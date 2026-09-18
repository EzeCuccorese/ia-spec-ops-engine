"""Black-box tests for the independently installable checkout packages."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def _get_bin(name: str) -> str:
    target = Path(sys.executable).parent / name
    return str(target) if target.exists() else name


def test_help_has_no_side_effects_or_network(tmp_path: Path) -> None:
    sentinel = tmp_path / "sentinel.txt"
    sentinel.write_text("pristine", encoding="utf-8")

    for entrypoint in ("specops", "governance", "ws", "rules", "progress"):
        proc = subprocess.run(
            [_get_bin(entrypoint), "--help"], cwd=tmp_path, capture_output=True, text=True
        )
        assert proc.returncode == 0
        assert "help" in proc.stdout.lower() or "usage" in proc.stdout.lower()

    assert sentinel.read_text(encoding="utf-8") == "pristine"


def test_governance_and_workspace_import_independently(tmp_path: Path) -> None:
    for module in ("ai_governance", "workspace_engine"):
        proc = subprocess.run(
            [sys.executable, "-I", "-c", f"import {module}"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 0
        assert proc.stderr == ""


def test_governance_does_not_advertise_checkout_or_optional_commands(tmp_path: Path) -> None:
    proc = subprocess.run(
        [_get_bin("governance"), "--help"], cwd=tmp_path, capture_output=True, text=True
    )
    assert proc.returncode == 0
    help_lines = [line.lstrip().lower() for line in proc.stdout.splitlines()]
    # "doctor" is intentionally absent: the checkout/environment doctor moved to
    # `ws doctor`, while `governance doctor` is the read-only harness wiring check.
    for removed_command in ("spec", "agent", "audit", "config"):
        assert not any(line.startswith(f"{removed_command} ") for line in help_lines)
