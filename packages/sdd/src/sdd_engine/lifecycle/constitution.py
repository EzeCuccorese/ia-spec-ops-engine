"""
sdd_engine.constitution — Gestor de Constitución y Reglas Técnicas para SDD.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Dict, Optional, Union

try:
    import tomllib
except ImportError:
    try:
        import tomli as tomllib  # type: ignore
    except ImportError:
        tomllib = None  # type: ignore

from sdd_engine.core.utils import find_project_root



def get_constitution_dir(target_dir: Union[str, Path] = ".") -> Path:
    root = find_project_root(Path(target_dir))
    return root / ".specify" / "constitution"


def get_constitution_file(target_dir: Union[str, Path] = ".") -> Path:
    return get_constitution_dir(target_dir) / "constitution.md"


def read_constitution(target_dir: Union[str, Path] = ".") -> Optional[str]:
    cf = get_constitution_file(target_dir)
    if cf.exists():
        try:
            return cf.read_text(encoding="utf-8")
        except OSError:
            return None
    return None


def infer_project_constitution(target_dir: Union[str, Path] = ".") -> Dict[str, str]:
    """
    Scans codebase files (pyproject.toml, package.json, pom.xml, Cargo.toml, go.mod, README.md)
    to automatically infer project name, description, technology stack, and architecture rules.
    """
    td = Path(target_dir).resolve()
    project_name = td.name
    description = ""
    stack_elements = []

    # 1. Inspect pyproject.toml
    pyproject_file = td / "pyproject.toml"
    if pyproject_file.exists() and tomllib is not None:
        try:
            with open(pyproject_file, "rb") as f:
                pdata = tomllib.load(f)
            proj = pdata.get("project", {})
            if proj.get("name"):
                project_name = str(proj["name"])
            if proj.get("description"):
                description = str(proj["description"])

            stack_elements.append("Python 3")
            deps = str(proj.get("dependencies", [])) + str(pdata.get("tool", {}))
            if "pytest" in deps:
                stack_elements.append("Pytest")
            if "ruff" in deps or "flake8" in deps or "oxlint" in deps:
                stack_elements.append("Linter (Ruff/Oxlint)")
            if "rich" in deps:
                stack_elements.append("Rich CLI")
            if "fastapi" in deps:
                stack_elements.append("FastAPI")
            if "django" in deps:
                stack_elements.append("Django")
        except Exception:
            pass

    # 2. Inspect package.json
    pkg_file = td / "package.json"
    if pkg_file.exists():
        try:
            with open(pkg_file, encoding="utf-8") as f:
                pkg_data = json.load(f)
            if not project_name or project_name == td.name:
                project_name = pkg_data.get("name", project_name)
            if not description:
                description = pkg_data.get("description", "")

            dev_deps = str(pkg_data.get("devDependencies", {}))
            all_deps = str(pkg_data.get("dependencies", {})) + dev_deps

            if "typescript" in all_deps:
                stack_elements.append("TypeScript")
            else:
                stack_elements.append("JavaScript (Node.js)")

            if "react" in all_deps:
                stack_elements.append("React")
            if "next" in all_deps:
                stack_elements.append("Next.js")
            if "vitest" in all_deps or "jest" in all_deps:
                stack_elements.append("Test Harness (Vitest/Jest)")
            if "eslint" in all_deps or "oxlint" in all_deps:
                stack_elements.append("Linter (ESLint/Oxlint)")
        except Exception:
            pass

    # 3. Inspect pom.xml or build.gradle
    if (td / "pom.xml").exists() or (td / "build.gradle").exists():
        stack_elements.append("Java")
        gradle_or_pom = ""
        if (td / "pom.xml").exists():
            try:
                gradle_or_pom = (td / "pom.xml").read_text(encoding="utf-8", errors="ignore")
            except Exception:
                pass
        if "spring-boot" in gradle_or_pom or (td / "build.gradle").exists():
            stack_elements.append("Spring Boot")
        if "junit" in gradle_or_pom:
            stack_elements.append("JUnit")

    # 4. Inspect Go / Rust
    if (td / "go.mod").exists():
        stack_elements.append("Go")
    if (td / "Cargo.toml").exists():
        stack_elements.append("Rust")

    # 5. Inspect README.md for description fallback
    readme_file = td / "README.md"
    if not description and readme_file.exists():
        try:
            readme_text = readme_file.read_text(encoding="utf-8", errors="ignore")
            lines = [l.strip() for l in readme_text.splitlines() if l.strip() and not l.startswith("#")]
            if lines:
                description = lines[0][:200]
        except Exception:
            pass

    if not description:
        description = f"Proyecto {project_name} gestionado mediante Especificación Guiada por Desarrollo (SDD)."

    if not stack_elements:
        stack_elements = ["Python 3 / Multi-stack", "Pytest / Standard Test Suite", "Conventional Commits"]

    tech_stack_str = ", ".join(stack_elements)

    architecture_rules = """- Contratos primero: Definir interfaces TypeScript, esquemas Zod, DTOs Java o modelos Pydantic antes de implementar lógica.
- Harnés de pruebas (Test-First): Escribir suite de pruebas unitarias/integración (RED) antes del código de negocio (GREEN).
- Implementación mínima: Escribir únicamente el código necesario para satisfacer el contrato y pasar los tests (YAGNI).
- Detección temprana: Correr linters estáticos y realizar lecturas de confirmación post-mutación.
- Cero secretos hardcodeados y cero datos personales (PII) guardados en logs."""

    return {
        "project_name": project_name,
        "description": description,
        "tech_stack": tech_stack_str,
        "architecture_rules": architecture_rules,
    }


def write_constitution(
    target_dir: Union[str, Path] = ".",
    project_name: str = "",
    description: str = "",
    tech_stack: str = "",
    architecture_rules: str = "",
) -> Path:
    td = Path(target_dir).resolve()
    inferred = infer_project_constitution(td)

    if not project_name:
        project_name = inferred["project_name"]

    if not description:
        description = inferred["description"]

    if not tech_stack:
        tech_stack = inferred["tech_stack"]

    if not architecture_rules:
        architecture_rules = inferred["architecture_rules"]

    cdir = get_constitution_dir(td)
    cdir.mkdir(parents=True, exist_ok=True)
    cfile = cdir / "constitution.md"

    content = f"""# Constitución del Proyecto — {project_name}

## 1. Descripción & Propósito
{description}

## 2. Stack Tecnológico Principal
{tech_stack}

## 3. Reglas Arquitectónicas & Estándares de Código
{architecture_rules}

## 4. Principios SDD (Single Source of Truth)
- Todo desarrollo de características avanzará secuencialmente: `/sdd-specify` -> `/sdd-clarify` -> `/sdd-plan` -> `/sdd-checklist` -> `/sdd-tasks` -> `/sdd-analyze` -> `/sdd-exec` -> `/sdd-converge`.
- Las decisiones registradas en `.specify/constitution/` prevalecen sobre cualquier preferencia de agente o configuración por defecto.
- Conventional Commits en inglés imperativo (`type(scope): description`) sin ninguna alusión a Inteligencia Artificial ni emojis.

## 5. 🔍 Descubrimientos Dinámicos de IA & Buenas Prácticas del Proyecto
- *(Sección reservada para que el agente de IA documente reglas detectadas dinámicamente: patrones de arquitectura, políticas de logging, seguridad, convenciones de tests y casos borde del proyecto)*
"""

    cfile.write_text(content, encoding="utf-8")
    return cfile


def prompt_create_constitution(target_dir: Union[str, Path] = ".") -> Path:
    td = Path(target_dir).resolve()
    inferred = infer_project_constitution(td)

    print("\n📜 Constitución del Proyecto (Auto-Detectada desde Código Fuente)")
    print("-------------------------------------------------------------------")
    print(f"  • Nombre auto-detectado: {inferred['project_name']}")
    print(f"  • Propósito:            {inferred['description']}")
    print(f"  • Stack Tecnológico:    {inferred['tech_stack']}")

    try:
        print("\nPresiona ENTER para aceptar los datos auto-detectados (o escribe para modificar):")

        p_name = input(f"  Nombre del proyecto [{inferred['project_name']}]: ").strip()
        if not p_name:
            p_name = inferred["project_name"]

        p_desc = input(f"  Descripción/Propósito [{inferred['description'][:60]}...]: ").strip()
        if not p_desc:
            p_desc = inferred["description"]

        p_stack = input(f"  Stack tecnológico [{inferred['tech_stack']}]: ").strip()
        if not p_stack:
            p_stack = inferred["tech_stack"]

        print("  Reglas arquitectónicas (Enter para aceptar predeterminadas SDD):")
        p_rules = input("  -> ").strip()
        if not p_rules:
            p_rules = inferred["architecture_rules"]
    except KeyboardInterrupt:
        print("\n\n🚫 Operación cancelada por el usuario.")
        sys.exit(130)
    except EOFError:
        p_name = inferred["project_name"]
        p_desc = inferred["description"]
        p_stack = inferred["tech_stack"]
        p_rules = inferred["architecture_rules"]

    return write_constitution(
        target_dir=td,
        project_name=p_name,
        description=p_desc,
        tech_stack=p_stack,
        architecture_rules=p_rules,
    )
