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


def _extract_version(raw: str, build_tool: str) -> str:
    if build_tool in ("gradle", "gradlew"):
        for line in raw.splitlines():
            if line.startswith("version:"):
                parts = line.split(maxsplit=1)
                return parts[1].strip() if len(parts) > 1 else ""
        return ""
    return raw.strip()


def _detect_build_commands(cwd: Path) -> tuple[str, str, str] | None:
    if (cwd / "pom.xml").is_file():
        return (
            "mvn",
            "mvn clean install",
            "mvn help:evaluate -Dexpression=project.version -q -DforceStdout",
        )
    if (cwd / "gradlew").is_file():
        return ("gradlew", "./gradlew clean build -x test", "./gradlew -q properties")
    if (cwd / "build.gradle").is_file() or (cwd / "build.gradle.kts").is_file():
        return ("gradle", "gradle clean build -x test", "gradle -q properties")
    if (cwd / "package.json").is_file():
        has_build = "build" in (cwd / "package.json").read_text(encoding="utf-8")
        return (
            "npm",
            "npm run build" if has_build else "npm test",
            "node -p \"require('./package.json').version\"",
        )
    if (cwd / "go.mod").is_file():
        return ("go", "go build ./...", "git describe --tags --always")
    if (cwd / "Cargo.toml").is_file():
        return ("cargo", "cargo build", "cargo pkgid")
    if (cwd / "pyproject.toml").is_file():
        return (
            "python",
            "python3 -m pip install -e .",
            "python3 -c \"import tomllib, pathlib; print(tomllib.loads(pathlib.Path('pyproject.toml').read_text()).get('project', {}).get('version', 'unknown'))\"",
        )
    return None


def build_project(project_dir: Path | None = None) -> int:
    cwd = project_dir or Path.cwd()

    log_info("🔍 Detecting build tool...")
    detected = _detect_build_commands(cwd)
    if not detected:
        log_error("No compatible project detected (Maven, Gradle, Node, Go, Rust, or Python).")
        return 1
    build_tool, build_cmd, version_cmd = detected

    log_info(f"🛠️ Project based on {build_tool.upper()}.")

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
        raw_version = run_command(version_cmd, cwd=cwd, env=java_env, check=False)
        version = _extract_version(raw_version or "", build_tool)
        if version:
            log_success(f"🔖 Detected version: {version}")
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
