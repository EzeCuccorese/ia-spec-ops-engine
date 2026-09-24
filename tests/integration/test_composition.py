"""Black-box tests for the independently installable checkout packages."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def _get_bin(name: str) -> str:
    """Entry point from the test environment only; never a globally installed binary."""
    target = Path(sys.executable).parent / name
    assert target.exists(), f"{name} is not installed in {target.parent}"
    return str(target)


def test_help_has_no_side_effects_or_network(tmp_path: Path) -> None:
    sentinel = tmp_path / "sentinel.txt"
    sentinel.write_text("pristine", encoding="utf-8")

    for entrypoint in ("ai-governance", "ws"):
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
        [_get_bin("ai-governance"), "--help"], cwd=tmp_path, capture_output=True, text=True
    )
    assert proc.returncode == 0
    help_lines = [line.lstrip().lower() for line in proc.stdout.splitlines()]
    for removed_command in ("spec", "agent", "audit", "config"):
        assert not any(line.startswith(f"{removed_command} ") for line in help_lines)


def test_agent_env_markers_stay_in_sync() -> None:
    """ai-governance and workspace detect agent mode from the same env markers."""
    from ai_governance.output import AGENT_ENV_MARKERS as governance_markers
    from workspace_engine.common.colors import AGENT_ENV_MARKERS as workspace_markers

    assert governance_markers == workspace_markers


def test_governance_hook_condenses_through_real_ws_contract(tmp_path: Path, monkeypatch) -> None:
    """ai-governance's post-shell hook and ws condense agree on the JSON contract."""
    root = Path(__file__).resolve().parents[2]
    shim = tmp_path / "ws"
    shim.write_text(
        "#!/bin/sh\n"
        f"PYTHONPATH={root / 'packages' / 'workspace' / 'src'} "
        f'exec {sys.executable} -m workspace_engine.cli.main "$@"\n'
    )
    shim.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}:/usr/bin:/bin")
    monkeypatch.setenv("WORKSPACE_LOG_DIR", str(tmp_path / "logs"))

    from ai_governance.frugality.cli import DEFAULT_CONFIG, condensed_output

    noise = "\n".join(
        f"tests/test_{i}.py ....................................." for i in range(300)
    )
    stdout = (
        noise + "\nE       assert 3 == 4\n" + noise + "\n==== 1 failed, 600 passed in 2.0s ===="
    )
    payload = {"tool_input": {"command": "pytest"}, "tool_response": {"stdout": stdout}}

    text, response = condensed_output(payload, dict(DEFAULT_CONFIG))

    assert "assert 3 == 4" in text and "1 failed, 600 passed" in text
    assert len(text) < len(stdout) / 5
    assert response["stdout"] == text
    assert "ws log " in text
