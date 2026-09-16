#!/usr/bin/env python3
"""
workspace_engine.cli.set_java — Automatic detection and configuration of the JDK version (Maven, Gradle, SDKMAN).
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

from workspace_engine.common import log_info, log_success, log_warning, run_command


def detect_required_java_version(project_dir: Path | None = None) -> str | None:
    """Detects the required Java version from the project's build files."""
    cwd = project_dir or Path.cwd()
    pom = cwd / "pom.xml"
    gradle = cwd / "build.gradle"
    gradle_kts = cwd / "build.gradle.kts"

    if pom.is_file():
        content = pom.read_text(encoding="utf-8", errors="ignore")
        match = re.search(r"<maven\.compiler\.target>([^<]+)</maven\.compiler\.target>", content)
        if not match:
            match = re.search(r"<java\.version>([^<]+)</java\.version>", content)
        if match:
            return match.group(1).strip()

    if gradle.is_file() or gradle_kts.is_file():
        content = (gradle if gradle.is_file() else gradle_kts).read_text(
            encoding="utf-8", errors="ignore"
        )
        match = re.search(r"JavaLanguageVersion\.of\((\d+)\)", content)
        if not match:
            match = re.search(r'sourceCompatibility\s*=\s*[\'"]?([\d.]+)', content)
        if match:
            return match.group(1).strip()

    return None


def get_java_env(version_tag: str) -> dict[str, str] | None:
    """Gets environment variables for a Java version via SDKMAN."""
    sdkman_init = os.path.expanduser("~/.sdkman/bin/sdkman-init.sh")
    if not os.path.isfile(sdkman_init):
        return None

    safe_version = shlex.quote(version_tag)
    safe_sdkman = shlex.quote(sdkman_init)
    cmd = f'source {safe_sdkman} && sdk use java {safe_version} > /dev/null && echo "JAVA_HOME=$JAVA_HOME" && echo "PATH=$PATH"'
    # sdkman only exposes its shell function via `source`, so we invoke bash
    # explicitly as an argv list rather than shell=True on run_command.
    output = run_command(["bash", "-c", cmd], capture_output=True)

    env: dict[str, str] = {}
    if output:
        for line in output.splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                env[k] = v
    return env if "JAVA_HOME" in env else None


def get_current_java_version() -> str | None:
    """Gets the Java version currently active on the system."""
    try:
        process = subprocess.run(["java", "-version"], capture_output=True, text=True)
        output = process.stderr or process.stdout
        match = re.search(r'version "([^"]+)"', output)
        if match:
            return match.group(1)
    except (OSError, subprocess.SubprocessError):
        pass
    return None


def find_best_java_match(required_version: str) -> str | None:
    """Finds the best matching Java version available in SDKMAN."""
    sdkman_init = os.path.expanduser("~/.sdkman/bin/sdkman-init.sh")
    if not os.path.isfile(sdkman_init):
        return None

    safe_sdkman = shlex.quote(sdkman_init)
    cmd = f"source {safe_sdkman} && sdk list java"
    java_list = run_command(["bash", "-c", cmd], capture_output=True)
    if not java_list:
        return None

    available_versions = []
    for line in java_list.splitlines():
        if required_version in line and any(
            k in line.lower() for k in ("installed", "tem", "corretto", "open", "librc")
        ):
            parts = line.split("|")
            if len(parts) > 5:
                ver = parts[5].strip()
                if ver:
                    available_versions.append(ver)

    if not available_versions:
        matches = re.findall(r"\b\d+\.[\d\.]+\-\w+\b", java_list)
        available_versions = [m for m in matches if required_version in m]

    if not available_versions:
        return None

    installed = [
        v for v in available_versions if "installed" in java_list.lower() and v in java_list
    ]
    return installed[0] if installed else available_versions[0]


def setups_java(project_dir: Path | None = None) -> dict[str, str] | None:
    """Detects and configures the required Java environment."""
    required = detect_required_java_version(project_dir)
    if not required:
        return None

    current = get_current_java_version()
    if current and current.startswith(required):
        log_success(f"Java {current} is already in use.")
        return os.environ.copy()

    best_match = find_best_java_match(required)
    if not best_match:
        log_warning(f"Java {required} not found in SDKMAN.")
        return None

    log_info(f"Switching to Java {best_match}...")
    env = get_java_env(best_match)
    if env and "JAVA_HOME" in env:
        log_success(f"Java environment configured for {best_match}")
        return env

    return None


def main() -> None:
    env = setups_java()
    if env:
        if len(sys.argv) > 1 and sys.argv[1] == "--json":
            print(json.dumps(env))
        else:
            print(f"export JAVA_HOME='{env.get('JAVA_HOME')}'")
            print(f"export PATH='{env.get('PATH')}'")
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
