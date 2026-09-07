"""
workspace_engine.common.project — Detección determinista de tipo de proyecto, stacks y búsqueda de raíz.
"""

from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path
from typing import Any


class ProjectType(StrEnum):
    SPRING_BOOT = "spring_boot"
    MAVEN = "maven"
    GRADLE = "gradle"
    KOTLIN = "kotlin"
    GO = "go"
    NODE = "node"
    BUN = "bun"
    PYTHON = "python"
    RUST = "rust"
    UNKNOWN = "unknown"


def find_project_root(start_path: Path | str | None = None) -> Path:
    """
    Encuentra la raíz del proyecto o workspace buscando .specify, .git o pyproject.toml.
    """
    current = Path(start_path or Path.cwd()).resolve()
    for parent in [current] + list(current.parents):
        if (
            (parent / ".specify").is_dir()
            or (parent / ".git").exists()
            or (parent / "pyproject.toml").exists()
        ):
            return parent
    return current


def read_package_json(repo_path: Path | str) -> dict[str, Any] | None:
    """Parsea de forma segura package.json si existe."""
    pkg_file = Path(repo_path) / "package.json"
    if not pkg_file.is_file():
        return None
    try:
        with open(pkg_file, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def is_spring_boot_app(repo_path: Path | str) -> bool:
    """Determina si un repositorio es un microservicio Spring Boot Java/Kotlin."""
    p = Path(repo_path)
    res_dir = p / "src" / "main" / "resources"
    if (res_dir / "application.properties").is_file():
        return True
    if (res_dir / "application.yml").is_file():
        return True
    return bool((res_dir / "application.yaml").is_file())


def is_kotlin_service(repo_path: Path | str) -> bool:
    """Determina si un repositorio es un proyecto o servicio en Kotlin."""
    p = Path(repo_path)
    if (p / "build.gradle.kts").is_file() or (p / "settings.gradle.kts").is_file():
        return True
    return bool(list(p.glob("src/main/kotlin/**/*.kt")))


def is_go_service(repo_path: Path | str) -> bool:
    """Determina si un repositorio es un servicio en Go."""
    return (Path(repo_path) / "go.mod").is_file()


def is_rust_service(repo_path: Path | str) -> bool:
    """Determina si un repositorio es un proyecto o workspace Rust."""
    return (Path(repo_path) / "Cargo.toml").is_file()


def is_bun_project(repo_path: Path | str) -> bool:
    """Determina si un proyecto utiliza el runtime Bun."""
    p = Path(repo_path)
    return (
        (p / "bun.lockb").is_file() or (p / "bun.lock").is_file() or (p / "bunfig.toml").is_file()
    )


def detect_fe_framework(repo_path: Path | str) -> str | None:
    """Detecta el framework frontend (React, Next.js, Vue, Angular, Svelte, Astro, Vite)."""
    pkg = read_package_json(repo_path)
    p = Path(repo_path)
    if (p / "astro.config.mjs").is_file() or (p / "astro.config.ts").is_file():
        return "astro"
    if (p / "svelte.config.js").is_file():
        return "svelte"

    if not pkg:
        return None
    deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
    if "astro" in deps:
        return "astro"
    if "svelte" in deps or "@sveltejs/kit" in deps:
        return "svelte"
    if "next" in deps:
        return "next"
    if "react" in deps or "react-dom" in deps:
        return "react"
    if "vue" in deps:
        return "vue"
    if "@angular/core" in deps:
        return "angular"
    if "vite" in deps:
        return "vite"
    return "node"


def detect_project_type(repo_path: Path | str) -> ProjectType:
    """Identifica la tecnología o build system principal de un proyecto."""
    p = Path(repo_path)
    if is_spring_boot_app(p):
        return ProjectType.SPRING_BOOT
    if is_kotlin_service(p):
        return ProjectType.KOTLIN
    if (
        (p / "gradlew").is_file()
        or (p / "build.gradle").is_file()
        or (p / "build.gradle.kts").is_file()
    ):
        return ProjectType.GRADLE
    if (p / "pom.xml").is_file():
        return ProjectType.MAVEN
    if is_go_service(p):
        return ProjectType.GO
    if is_rust_service(p):
        return ProjectType.RUST
    if is_bun_project(p):
        return ProjectType.BUN
    if (p / "package.json").is_file():
        return ProjectType.NODE
    if (
        (p / "pyproject.toml").is_file()
        or (p / "requirements.txt").is_file()
        or (p / "setup.py").is_file()
    ):
        return ProjectType.PYTHON
    return ProjectType.UNKNOWN
