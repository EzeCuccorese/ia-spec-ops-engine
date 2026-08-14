#!/usr/bin/env python3
"""
workspace_engine.cli.install_deps — Instalación determinista de dependencias locales (Node, Gradle, Maven, Go, Python).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

from workspace_engine.utils import Color, detect_project_type, find_project_root, log_error, log_info, log_success, log_warning


def install_repo_deps(repo_path: Path) -> bool:
    """Instala las dependencias para un repositorio específico según su tecnología."""
    name = repo_path.name
    ptype = detect_project_type(repo_path)

    log_info(f"[{name}] Instalando dependencias ({ptype})...")

    if (repo_path / "yarn.lock").is_file():
        cmd = ["yarn", "install"]
    elif (repo_path / "package-lock.json").is_file():
        cmd = ["npm", "install"]
    elif (repo_path / "package.json").is_file():
        cmd = ["npm", "install"]
    elif (repo_path / "gradlew").is_file():
        cmd = ["./gradlew", "dependencies", "--quiet"]
    elif (repo_path / "pom.xml").is_file():
        cmd = ["mvn", "dependency:resolve", "-q"]
    elif (repo_path / "go.mod").is_file():
        cmd = ["go", "mod", "download"]
    elif (repo_path / "requirements.txt").is_file():
        cmd = ["pip", "install", "-r", "requirements.txt"]
    elif (repo_path / "pyproject.toml").is_file():
        cmd = ["pip", "install", "-e", "."]
    else:
        log_warning(f"[{name}] No se detectó manifest de dependencias reconocido.")
        return True

    res = subprocess.run(cmd, cwd=str(repo_path), capture_output=True, text=True)
    if res.returncode == 0:
        log_success(f"[{name}] Dependencias instaladas con éxito.")
        return True
    else:
        log_error(f"[{name}] Error al instalar dependencias:\n{res.stderr.strip()[:300]}")
        return False


def install_all_deps(repos_filter: Optional[List[str]] = None, start_dir: Optional[Path] = None) -> int:
    workspace_dir = find_project_root(start_dir)
    repos_dir = workspace_dir / "repositories"

    if not repos_dir.is_dir():
        # Si se ejecuta directamente dentro de un único repositorio
        if (workspace_dir / ".git").exists():
            success = install_repo_deps(workspace_dir)
            return 0 if success else 1
        log_error(f"No se encontró directorio de repositorios en {workspace_dir}")
        return 1

    targets: List[Path] = []
    if repos_filter:
        for rname in repos_filter:
            p = repos_dir / rname
            if p.is_dir():
                targets.append(p)
            else:
                log_error(f"Repositorio no encontrado: {rname}")
    else:
        targets = [p for p in sorted(repos_dir.iterdir()) if p.is_dir()]

    if not targets:
        log_warning("No hay repositorios para procesar.")
        return 0

    all_ok = True
    for rpath in targets:
        ok = install_repo_deps(rpath)
        if not ok:
            all_ok = False

    return 0 if all_ok else 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Instala dependencias de proyectos locales.")
    parser.add_argument("repos", nargs="*", help="Nombres de repositorios específicos (opcional)")
    args = parser.parse_args()
    sys.exit(install_all_deps(repos_filter=args.repos))


if __name__ == "__main__":
    main()
