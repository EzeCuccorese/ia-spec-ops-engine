"""Build-output smoke checks in fresh environments outside the checkout.

Usage: python tests/integration/verify_wheels.py <wheel-directory>
Requires uv on PATH. Downloads only declared package dependencies.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

PACKAGES = {
    "ai_governance": (
        "ai_governance",
        ["ai-governance"],
    ),
    "workspace": ("workspace_engine", ["ws"]),
}

RESOURCE_CHECK = """
import importlib.resources
import json
import pathlib
import sys

modules = sys.argv[1:]
for module in modules:
    imported = __import__(module)
    assert pathlib.Path(imported.__file__).is_relative_to(sys.prefix), imported.__file__
    assert importlib.resources.files(module).is_dir()

if "ai_governance" in modules:
    from ai_governance.cli import main as governance
    from ai_governance.rules.catalog import RuleCatalog
    from ai_governance.taskflow.cli import main as taskflow
    catalog = RuleCatalog()
    assert len(catalog.rules) >= 28
    assert governance(["install", "--scope", "project", "--agent", "claude", "--root", "."]) == 0
    assert "<!-- ai-governance:start -->" in pathlib.Path("AGENTS.md").read_text()
    assert pathlib.Path(".claude/rules/ai-governance-06-security-privacy.md").is_file()
    assert governance(["uninstall", "--scope", "project", "--agent", "claude", "--root", "."]) == 0
    assert not pathlib.Path(".ai-governance").exists()
    assert taskflow(["new", "wheel-smoke", "--title", "Wheel smoke", "--workflow", "manual"]) == 0
    assert taskflow(["summary", "wheel-smoke", "Verified installed wheel"]) == 0
    assert taskflow(["step", "wheel-smoke", "add", "Verify resources"]) == 0
    assert taskflow(["step", "wheel-smoke", "done", "Verify resources"]) == 0
    assert taskflow(["fact", "wheel-smoke", "Resources loaded"]) == 0
    assert taskflow(["link", "wheel-smoke", "Documentation", "https://example.com"]) == 0
    assert taskflow(["close", "wheel-smoke", "--reason", "Verified"]) == 0
if "workspace_engine" in modules:
    from workspace_engine.services.detect import detect_stacks
    from workspace_engine.services.git_hooks import generate_canonical_pre_push_script
    pathlib.Path("pyproject.toml").write_text("[project]\\nname = 'smoke'\\n")
    assert "python" in detect_stacks(".").stacks
    assert generate_canonical_pre_push_script().startswith("#!/usr/bin/env bash")
"""


def _find_wheels(wheel_dir: Path) -> dict[str, Path]:
    wheels = {}
    for distribution in PACKAGES:
        matches = list(wheel_dir.glob(f"{distribution}-*.whl"))
        if len(matches) != 1:
            raise SystemExit(f"Expected one wheel for {distribution}, found {len(matches)}")
        wheels[distribution] = matches[0].resolve()
    return wheels


def _isolated_env(root: Path) -> dict[str, str]:
    env = os.environ.copy()
    for var in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV"):
        env.pop(var, None)
    # All runtime writes remain in this disposable environment.
    env["HOME"] = str(root)
    env["XDG_CONFIG_HOME"] = str(root / "config")
    env["AI_GOVERNANCE_STATE_DIR"] = str(root / "state")
    env["WORKSPACE_LOG_DIR"] = str(root / "logs")
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_SYSTEM"] = os.devnull
    return env


def _run_checked(
    cmd: list[str], cwd: Path, env: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, env=env, check=True, capture_output=True, text=True)


def _verify_entrypoints(venv: Path, selected: list[str], cwd: Path, env: dict[str, str]) -> None:
    for name in selected:
        for entrypoint in PACKAGES[name][1]:
            _run_checked([str(venv / "bin" / entrypoint), "--help"], cwd, env)


def _verify_workspace_cli(ws_bin: Path, cwd: Path, env: dict[str, str]) -> None:
    _run_checked([str(ws_bin), "--help"], cwd, env)
    detected = _run_checked([str(ws_bin), "detect", "--json"], cwd, env)
    payload = json.loads(detected.stdout)
    assert "python" in payload["stacks"], payload
    ran = _run_checked([str(ws_bin), "run", "--", "echo", "ok"], cwd, env)
    assert "ok" in ran.stdout, ran.stdout
    _run_checked([str(ws_bin), "design", "--help"], cwd, env)


def _verify_selection(wheels: dict[str, Path], selected: list[str]) -> None:
    with tempfile.TemporaryDirectory(prefix="wheel-check-") as directory:
        root = Path(directory)
        venv = root / "venv"
        cwd = root / "project"
        cwd.mkdir()
        env = _isolated_env(root)
        subprocess.run(["uv", "venv", "--python", sys.executable, str(venv)], check=True)
        python = venv / "bin" / "python"
        install_cmd = ["uv", "pip", "install", "--python", str(python)]
        install_cmd.extend(str(wheels[name]) for name in selected)
        subprocess.run(install_cmd, check=True)
        _verify_entrypoints(venv, selected, cwd, env)
        resource_cmd = [str(python), "-I", "-c", RESOURCE_CHECK]
        resource_cmd.extend(PACKAGES[name][0] for name in selected)
        _run_checked(resource_cmd, cwd, env)
        if "workspace" in selected:
            _verify_workspace_cli(venv / "bin" / "ws", cwd, env)


def verify(wheel_dir: Path) -> None:
    wheels = _find_wheels(wheel_dir)
    for selected in [*[[name] for name in PACKAGES], list(PACKAGES)]:
        _verify_selection(wheels, selected)
        print(f"PASS: {', '.join(selected)}", flush=True)


if __name__ == "__main__":
    verify(Path(sys.argv[1]).resolve())
