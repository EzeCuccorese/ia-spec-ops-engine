"""Build-output smoke checks in fresh environments outside the checkout.

Usage: python tests/integration/verify_wheels.py <wheel-directory>
Requires uv on PATH. Downloads only declared package dependencies.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

PACKAGES = {
    "ai_governance": (
        "ai_governance",
        ["specops", "governance", "rules", "progress", "jira", "confluence"],
    ),
    "spec": ("spec", ["spec"]),
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
    from ai_governance.rules.core.catalog import RuleCatalog
    from ai_governance.rules.cli import main as rules
    from ai_governance.session.cli import main as progress
    catalog = RuleCatalog()
    manifest = json.loads((catalog.root / "manifest.json").read_text())
    assert len(catalog.rules) == manifest["total_rules"] >= 29
    assert len(catalog.tools) == len(manifest["tools"]) >= 15
    resource = importlib.resources.files("ai_governance").joinpath("resources", "workflows", "progress.md")
    assert resource.is_file()
    rules(["install", "--local", "--all", "--root", "."])
    assert "<!-- rules:start -->" in pathlib.Path("AGENTS.md").read_text()
    assert progress(["new", "wheel-smoke", "--title", "Wheel smoke"]) == 0
    assert progress(["summary", "wheel-smoke", "Verified installed wheel"]) == 0
    assert progress(["step", "wheel-smoke", "add", "Verify resources"]) == 0
    assert progress(["step", "wheel-smoke", "done", "Verify resources"]) == 0
    assert progress(["fact", "wheel-smoke", "Resources loaded"]) == 0
    assert progress(["link", "wheel-smoke", "Documentation", "https://example.com"]) == 0
    assert progress(["close", "wheel-smoke", "--reason", "Verified"]) == 0
if "workspace_engine" in modules:
    from workspace_engine.cli.generate_workspace import create_workspace_structure
    from workspace_engine.services.git_hooks import generate_canonical_pre_push_script
    target = create_workspace_structure("smoke", pathlib.Path.cwd(), [], {})
    content = (target / "AGENTS.md").read_text()
    assert "Dedicated Worktrees" in content
    assert "claude-yolo" not in content and "docker/scripts/run-unit-tests.sh" not in content
    assert generate_canonical_pre_push_script().startswith("#!/usr/bin/env bash")
"""


def verify(wheel_dir: Path) -> None:
    wheels = {}
    for distribution in PACKAGES:
        matches = list(wheel_dir.glob(f"{distribution}-*.whl"))
        if len(matches) != 1:
            raise SystemExit(f"Expected one wheel for {distribution}, found {len(matches)}")
        wheels[distribution] = matches[0].resolve()

    for selected in [*[[name] for name in PACKAGES], list(PACKAGES)]:
        with tempfile.TemporaryDirectory(prefix="specops-wheel-") as directory:
            root = Path(directory)
            venv = root / "venv"
            cwd = root / "project"
            cwd.mkdir()
            env = os.environ.copy()
            env.pop("PYTHONPATH", None)
            env.pop("PYTHONHOME", None)
            env.pop("VIRTUAL_ENV", None)
            # All runtime writes remain in this disposable environment.
            env["HOME"] = str(root)
            env["XDG_CONFIG_HOME"] = str(root / "config")
            env["SPECOPS_PROGRESS_DIR"] = str(root / "progress")
            env["GIT_CONFIG_GLOBAL"] = os.devnull
            env["GIT_CONFIG_SYSTEM"] = os.devnull
            subprocess.run(["uv", "venv", "--python", sys.executable, str(venv)], check=True)
            python = venv / "bin" / "python"
            subprocess.run(
                [
                    "uv",
                    "pip",
                    "install",
                    "--python",
                    str(python),
                    *[str(wheels[name]) for name in selected],
                ],
                check=True,
            )
            for name in selected:
                for entrypoint in PACKAGES[name][1]:
                    subprocess.run(
                        [str(venv / "bin" / entrypoint), "--help"],
                        cwd=cwd,
                        env=env,
                        check=True,
                        capture_output=True,
                        text=True,
                    )
            subprocess.run(
                [
                    str(python),
                    "-I",
                    "-c",
                    RESOURCE_CHECK,
                    *[PACKAGES[name][0] for name in selected],
                ],
                cwd=cwd,
                env=env,
                check=True,
                capture_output=True,
                text=True,
            )
        print(f"PASS: {', '.join(selected)}", flush=True)


if __name__ == "__main__":
    verify(Path(sys.argv[1]).resolve())
