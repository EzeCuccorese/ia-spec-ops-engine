#!/usr/bin/env python3
"""
workspace_engine.cli.build_project — Deterministic build for projects (Gradle, Maven, Node, Go, Python).
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from workspace_engine.cli import set_java
from workspace_engine.common import log_error, log_info, log_success, log_warning, run_command


def build_project(project_dir: Path | None = None) -> int:
    cwd = project_dir or Path.cwd()

    log_info("🔍 Detecting build tool...")
    if (cwd / "pom.xml").is_file():
        build_tool = "mvn"
        build_cmd = f"{build_tool} clean install"
        version_cmd = f"{build_tool} help:evaluate -Dexpression=project.version -q -DforceStdout"
    elif (cwd / "gradlew").is_file():
        build_tool = "gradlew"
        build_cmd = f"./{build_tool} clean build -x test"
        version_cmd = f"./{build_tool} -q properties | grep '^version:' | awk '{{print $2}}'"
    elif (cwd / "build.gradle").is_file() or (cwd / "build.gradle.kts").is_file():
        build_tool = "gradle"
        build_cmd = f"{build_tool} clean build -x test"
        version_cmd = f"{build_tool} -q properties | grep '^version:' | awk '{{print $2}}'"
    elif (cwd / "package.json").is_file():
        build_tool = "npm"
        build_cmd = "npm run build" if "build" in (cwd / "package.json").read_text() else "npm test"
        version_cmd = "node -p \"require('./package.json').version\""
    elif (cwd / "go.mod").is_file():
        build_tool = "go"
        build_cmd = "go build ./..."
        version_cmd = "git describe --tags --always"
    elif (cwd / "Cargo.toml").is_file():
        build_tool = "cargo"
        build_cmd = "cargo build"
        version_cmd = "cargo pkgid"
    elif (cwd / "pyproject.toml").is_file():
        build_tool = "python"
        build_cmd = "python3 -m pip install -e ."
        version_cmd = "python3 -c \"import tomllib, pathlib; print(tomllib.loads(pathlib.Path('pyproject.toml').read_text()).get('project', {}).get('version', 'unknown'))\""
    else:
        log_error("No compatible project detected (Maven, Gradle, Node, Go, Rust, or Python).")
        return 1

    log_info(f"🛠️ Project based on {build_tool.upper()}.")

    # Configure Java if applicable
    java_env = None
    if build_tool in ("mvn", "gradle", "gradlew"):
        log_info("🧪 Configuring Java...")
        java_env = set_java.setups_java(cwd)
        if not java_env:
            log_warning("Could not configure Java automatically. Using the current environment.")
            java_env = os.environ.copy()

    log_info(f"🚧 Running build with {build_tool}...")
    try:
        output = run_command(build_cmd, cwd=cwd, env=java_env, show_command=True)
        if output:
            print(output)
        log_success("Build completed successfully.")
    except (OSError, subprocess.SubprocessError) as e:
        log_error(f"Build failed: {e}")
        return 1

    log_info("📦 Detecting project version...")
    try:
        version = run_command(version_cmd, cwd=cwd, env=java_env, check=False)
        if version:
            log_success(f"🔖 Detected version: {version.strip()}")
    except (OSError, subprocess.SubprocessError):
        pass

    return 0


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="ws build", description="Builds a project auto-detecting its build tool."
    )
    parser.add_argument("dir", nargs="?", default=".", help="Project directory (defaults to cwd)")
    args = parser.parse_args(argv)
    sys.exit(build_project(Path(args.dir).expanduser().resolve()))


if __name__ == "__main__":
    main()
