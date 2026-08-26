#!/usr/bin/env python3
"""
workspace_engine.cli.build_project — Compilación y build determinista de proyectos (Gradle, Maven, Node, Go, Python).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from workspace_engine.cli import set_java
from workspace_engine.utils import Color, log_error, log_info, log_success, log_warning, run_command


def build_project(project_dir: Path | None = None) -> int:
    cwd = project_dir or Path.cwd()

    log_info("🔄 Actualizando repositorio local...")
    run_command("git pull", cwd=cwd, check=False, show_command=True)
    run_command("git fetch --tags --quiet", cwd=cwd, check=False)

    log_info("🔍 Detectando herramienta de construcción...")
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
    else:
        log_error("No se detectó un proyecto compatible (Maven, Gradle, Node o Go).")
        return 1

    log_info(f"🛠️ Proyecto basado en {build_tool.upper()}.")

    # Configurar Java si aplica
    java_env = None
    if build_tool in ("mvn", "gradle", "gradlew"):
        log_info("🧪 Configurando Java...")
        java_env = set_java.setups_java(cwd)
        if not java_env:
            log_warning("No se pudo configurar Java automáticamente. Se usará el entorno actual.")
            java_env = os.environ.copy()

    log_info(f"🚧 Ejecutando build con {build_tool}...")
    try:
        output = run_command(build_cmd, cwd=cwd, env=java_env, show_command=True)
        if output:
            print(output)
        log_success("Build completado con éxito.")
    except Exception as e:
        log_error(f"Fallo en build: {e}")
        return 1

    log_info("📦 Detectando versión del proyecto...")
    try:
        version = run_command(version_cmd, cwd=cwd, env=java_env, check=False)
        if version:
            log_success(f"🔖 Versión detectada: {version.strip()}")
    except Exception:
        pass

    return 0


def main():
    sys.exit(build_project())


if __name__ == "__main__":
    main()
