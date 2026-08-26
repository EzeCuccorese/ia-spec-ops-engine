"""
workspace_engine.services.git_hooks — Gestor de Git Hooks e instalación de Quality Gates Multi-Stack.

Provee instalación, desinstalación y verificación de estado para hooks locales (.githooks/)
y globales (~/.githooks/) con soporte multi-lenguaje (Python, Node/React, Java/Kotlin, Go, Rust, Flutter, etc.).
"""

from __future__ import annotations

import os
import shutil
import stat
from pathlib import Path
from typing import Any, Dict, Optional, Union

from workspace_engine.common import run_command_safe


def generate_canonical_pre_push_script() -> str:
    """Genera el script bash canónico de 4 etapas para el hook pre-push."""
    return """#!/usr/bin/env bash
set -e

# Colored logging
RED='\\033[0;31m'
GREEN='\\033[0;32m'
YELLOW='\\033[1;33m'
BLUE='\\033[0;34m'
CYAN='\\033[0;36m'
NC='\\033[0m' # No Color

echo -e "${BLUE}[Quality Gate Pre-Push Hook] Verificando calidad y seguridad antes de enviar cambios...${NC}"

REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
cd "$REPO_ROOT"

# 1. Delegar en hook local de repositorio si existe (evitando loop infinito con este script)
LOCAL_HOOK="$REPO_ROOT/.githooks/pre-push"
if [ -x "$LOCAL_HOOK" ] && [ "$(realpath "$LOCAL_HOOK" 2>/dev/null)" != "$(realpath "$0" 2>/dev/null)" ]; then
    echo -e "${YELLOW}Delegando en el hook local del proyecto: $LOCAL_HOOK${NC}"
    exec "$LOCAL_HOOK" "$@"
fi

LOCAL_GIT_HOOK="$REPO_ROOT/.git/hooks/pre-push"
if [ -x "$LOCAL_GIT_HOOK" ] && [ "$(realpath "$LOCAL_GIT_HOOK" 2>/dev/null)" != "$(realpath "$0" 2>/dev/null)" ]; then
    echo -e "${YELLOW}Delegando en el hook git local: $LOCAL_GIT_HOOK${NC}"
    exec "$LOCAL_GIT_HOOK" "$@"
fi

# ==============================================================================
# 2. SEGURIDAD & SECRETS: Escaneo de secretos, tokens y archivos prohibidos
# ==============================================================================
echo -e "${CYAN}🔒 [1/4] Verificando seguridad y escaneo de secretos...${NC}"

# A. Archivos prohibidos trackeados (excluyendo plantillas .example y .template)
FORBIDDEN_FILES=$(git ls-files | grep -E '(\\.(env(\\..+)?|pem|key)$|id_rsa$|id_ed25519$|credentials\\.json$|\\.DS_Store$)' | grep -vE '\\.(example|template)$' || true)
if [ -n "$FORBIDDEN_FILES" ]; then
    echo -e "${RED}❌ ERROR DE SEGURIDAD: Se detectaron archivos sensibles trackeados en Git:${NC}"
    echo "$FORBIDDEN_FILES"
    echo -e "${YELLOW}Elimínalos del tracking con 'git rm --cached <archivo>' antes de pushear.${NC}"
    exit 1
fi

# B. Escaneo de tokens de API y claves privadas en commits recientes
DIFF_CONTENT=$(git diff HEAD~1..HEAD 2>/dev/null || git diff --cached 2>/dev/null || true)
if [ -n "$DIFF_CONTENT" ]; then
    LEAK_PATTERNS='(BEGIN (RSA|EC|OPENSSH|PRIVATE) KEY|AKIA[0-9A-Z]{16}|ghp_[a-zA-Z0-9]{36}|sk-[a-zA-Z0-9]{20,}|AIza[0-9A-Za-z_-]{35})'
    DETECTED_LEAKS=$(echo "$DIFF_CONTENT" | grep -E "^\\+[^+]" | grep -E "$LEAK_PATTERNS" || true)
    if [ -n "$DETECTED_LEAKS" ]; then
        echo -e "${RED}❌ ERROR DE SEGURIDAD: Se detectaron posibles secretos/tokens hardcodeados en el diff:${NC}"
        echo "$DETECTED_LEAKS" | head -n 5
        echo -e "${YELLOW}Utiliza variables de entorno o un gestor de secretos antes de pushear.${NC}"
        exit 1
    fi
fi
echo -e "${GREEN}✔ Seguridad y Secretos: PASS${NC}"

# ==============================================================================
# 3. GIT POLICIES: Cero menciones de IA en commits
# ==============================================================================
echo -e "${CYAN}📝 [2/4] Verificando políticas de commit y reglas Git...${NC}"
RECENT_MESSAGES=$(git log -n 5 --format=%B 2>/dev/null || true)
if echo "$RECENT_MESSAGES" | grep -Eqi '(generated (by|with) ai|co-authored-by:.*(claude|gpt|gemini|copilot)|🤖|🦾)'; then
    echo -e "${RED}❌ ERROR DE POLÍTICA GIT: Se detectaron menciones de IA o emojis de robot en los mensajes de commit recientes.${NC}"
    echo -e "${YELLOW}Modifica el mensaje con 'git commit --amend' para eliminar menciones antes de pushear.${NC}"
    exit 1
fi
echo -e "${GREEN}✔ Políticas Git y Cero menciones IA: PASS${NC}"

# ==============================================================================
# 4. LINTERS & VERIFICACIÓN ESTÁTICA MULTI-LENGUAJE
# ==============================================================================
echo -e "${CYAN}🔍 [3/4] Ejecutando análisis estático y linters por stack...${NC}"

# Python Linter (Ruff / Flake8)
if [ -f "pyproject.toml" ] || [ -f "pytest.ini" ] || [ -f "requirements.txt" ] || [ -d "backend" ]; then
    if command -v ruff >/dev/null 2>&1; then
        echo -e "${BLUE}Ejecutando Ruff Linter en Python...${NC}"
        ruff check . < /dev/null || { echo -e "${RED}❌ Fallaron las comprobaciones de linter con ruff.${NC}"; exit 1; }
    elif command -v uv >/dev/null 2>&1; then
        echo -e "${BLUE}Ejecutando Ruff Linter en Python (uv)...${NC}"
        uv run --with ruff ruff check . < /dev/null || { echo -e "${RED}❌ Fallaron las comprobaciones de linter con ruff (uv).${NC}"; exit 1; }
    elif command -v flake8 >/dev/null 2>&1; then
        echo -e "${BLUE}Ejecutando Flake8 Linter en Python...${NC}"
        flake8 < /dev/null || { echo -e "${RED}❌ Fallaron las comprobaciones de linter con flake8.${NC}"; exit 1; }
    fi
fi

# Node.js / React / TypeScript / Frontend (Root, frontend, client, ui, web)
run_node_lint() {
    local dir="$1"
    if [ -f "$dir/package.json" ]; then
        if grep -q '"lint"' "$dir/package.json"; then
            echo -e "${BLUE}Ejecutando linter en $dir (npm run lint)...${NC}"
            (cd "$dir" && npm run lint < /dev/null) || { echo -e "${RED}❌ Falló el linter en $dir.${NC}"; exit 1; }
        fi
        if [ -f "$dir/tsconfig.json" ] && grep -q '"typecheck"' "$dir/package.json"; then
            echo -e "${BLUE}Ejecutando typecheck en $dir (npm run typecheck)...${NC}"
            (cd "$dir" && npm run typecheck < /dev/null) || { echo -e "${RED}❌ Falló el typecheck de TypeScript en $dir.${NC}"; exit 1; }
        fi
    fi
}
run_node_lint "."
run_node_lint "frontend"
run_node_lint "client"
run_node_lint "ui"
run_node_lint "web"

# Go (go vet)
if [ -f "go.mod" ]; then
    echo -e "${BLUE}Ejecutando go vet en Go...${NC}"
    go vet ./... < /dev/null || { echo -e "${RED}❌ Falló go vet.${NC}"; exit 1; }
fi

# Rust (cargo clippy)
if [ -f "Cargo.toml" ]; then
    if cargo clippy --version >/dev/null 2>&1; then
        echo -e "${BLUE}Ejecutando cargo clippy en Rust...${NC}"
        cargo clippy -- -D warnings < /dev/null || { echo -e "${RED}❌ Falló cargo clippy.${NC}"; exit 1; }
    fi
fi

# Flutter / Dart Analyze
if [ -f "pubspec.yaml" ]; then
    echo -e "${BLUE}Ejecutando análisis estático en Flutter/Dart...${NC}"
    if command -v flutter >/dev/null 2>&1; then
        flutter analyze < /dev/null || { echo -e "${RED}❌ Falló flutter analyze.${NC}"; exit 1; }
    elif command -v dart >/dev/null 2>&1; then
        dart analyze < /dev/null || { echo -e "${RED}❌ Falló dart analyze.${NC}"; exit 1; }
    fi
fi

# Java / Kotlin (Maven / Gradle Spotless / Checkstyle / Compilation check)
if [ -f "pom.xml" ]; then
    if grep -q "checkstyle" pom.xml 2>/dev/null; then
        echo -e "${BLUE}Ejecutando checkstyle en Maven (Java)...${NC}"
        if [ -f "./mvnw" ]; then
            ./mvnw checkstyle:check < /dev/null || true
        else
            mvn checkstyle:check < /dev/null || true
        fi
    fi
elif [ -f "build.gradle" ] || [ -f "build.gradle.kts" ]; then
    if [ -f "./gradlew" ]; then
        if ./gradlew tasks --all 2>/dev/null | grep -q "spotlessCheck"; then
            echo -e "${BLUE}Ejecutando spotlessCheck en Gradle (Java/Kotlin)...${NC}"
            ./gradlew spotlessCheck < /dev/null || { echo -e "${RED}❌ Falló spotlessCheck.${NC}"; exit 1; }
        fi
    fi
fi

echo -e "${GREEN}✔ Linters y Análisis Estático: PASS${NC}"

# ==============================================================================
# 5. SUITES DE TESTS MULTI-LENGUAJE
# ==============================================================================
echo -e "${CYAN}🧪 [4/4] Ejecutando suites de tests automáticas...${NC}"
TESTS_RUN=0

# Python Tests
if [ -f "pyproject.toml" ] || [ -f "pytest.ini" ] || [ -f "requirements.txt" ] || [ -d "backend" ]; then
    if [ -f "backend/pytest.ini" ] || [ -d "backend/tests" ]; then
        echo -e "${BLUE}Ejecutando tests de Python (backend)...${NC}"
        if [ -f "backend/.venv/bin/pytest" ]; then
            backend/.venv/bin/pytest backend/tests/ -m "not integration" < /dev/null || { echo -e "${RED}❌ Fallaron los tests de Python backend.${NC}"; exit 1; }
            TESTS_RUN=$((TESTS_RUN+1))
        elif command -v pytest >/dev/null 2>&1; then
            pytest backend/tests/ -m "not integration" < /dev/null || { echo -e "${RED}❌ Fallaron los tests de Python backend.${NC}"; exit 1; }
            TESTS_RUN=$((TESTS_RUN+1))
        fi
    elif [ -d "tests" ] || [ -f "pytest.ini" ] || [ -f "pyproject.toml" ]; then
        echo -e "${BLUE}Ejecutando tests de Python (pytest)...${NC}"
        if [ -f ".venv/bin/pytest" ]; then
            .venv/bin/pytest < /dev/null || { echo -e "${RED}❌ Fallaron los tests de Python.${NC}"; exit 1; }
            TESTS_RUN=$((TESTS_RUN+1))
        elif command -v pytest >/dev/null 2>&1; then
            pytest < /dev/null || { echo -e "${RED}❌ Fallaron los tests de Python.${NC}"; exit 1; }
            TESTS_RUN=$((TESTS_RUN+1))
        fi
    fi
fi

# Node.js / React / TypeScript Tests (Root, frontend, client, ui, web)
run_node_tests() {
    local dir="$1"
    if [ -f "$dir/package.json" ]; then
        if grep -q '"test"' "$dir/package.json"; then
            echo -e "${BLUE}Ejecutando tests en $dir (npm test)...${NC}"
            (cd "$dir" && npm test -- --run < /dev/null) || (cd "$dir" && npm test < /dev/null) || { echo -e "${RED}❌ Fallaron los tests en $dir.${NC}"; exit 1; }
            TESTS_RUN=$((TESTS_RUN+1))
        fi
    fi
}
run_node_tests "."
run_node_tests "frontend"
run_node_tests "client"
run_node_tests "ui"
run_node_tests "web"

# Go Tests
if [ -f "go.mod" ]; then
    echo -e "${BLUE}Ejecutando tests de Go (go test ./...)...${NC}"
    go test ./... < /dev/null || { echo -e "${RED}❌ Fallaron los tests de Go.${NC}"; exit 1; }
    TESTS_RUN=$((TESTS_RUN+1))
fi

# Rust Tests
if [ -f "Cargo.toml" ]; then
    echo -e "${BLUE}Ejecutando tests de Rust (cargo test)...${NC}"
    cargo test < /dev/null || { echo -e "${RED}❌ Fallaron los tests de Rust.${NC}"; exit 1; }
    TESTS_RUN=$((TESTS_RUN+1))
fi

# Flutter / Dart Tests
if [ -f "pubspec.yaml" ]; then
    echo -e "${BLUE}Ejecutando tests de Flutter/Dart...${NC}"
    if command -v flutter >/dev/null 2>&1; then
        flutter test < /dev/null || { echo -e "${RED}❌ Fallaron los tests de Flutter.${NC}"; exit 1; }
    else
        dart test < /dev/null || { echo -e "${RED}❌ Fallaron los tests de Dart.${NC}"; exit 1; }
    fi
    TESTS_RUN=$((TESTS_RUN+1))
fi

# Java / Kotlin Tests (Maven / Gradle)
if [ -f "pom.xml" ]; then
    echo -e "${BLUE}Ejecutando tests de Maven (Java)...${NC}"
    if [ -f "./mvnw" ]; then
        ./mvnw test < /dev/null || { echo -e "${RED}❌ Fallaron los tests de Maven.${NC}"; exit 1; }
    else
        mvn test < /dev/null || { echo -e "${RED}❌ Fallaron los tests de Maven.${NC}"; exit 1; }
    fi
    TESTS_RUN=$((TESTS_RUN+1))
elif [ -f "build.gradle" ] || [ -f "build.gradle.kts" ]; then
    echo -e "${BLUE}Ejecutando tests de Gradle (Java/Kotlin)...${NC}"
    if [ -f "./gradlew" ]; then
        ./gradlew test < /dev/null || { echo -e "${RED}❌ Fallaron los tests de Gradle.${NC}"; exit 1; }
    else
        gradle test < /dev/null || { echo -e "${RED}❌ Fallaron los tests de Gradle.${NC}"; exit 1; }
    fi
    TESTS_RUN=$((TESTS_RUN+1))
fi

# Ruby Tests
if [ -f "Gemfile" ]; then
    echo -e "${BLUE}Ejecutando tests de Ruby...${NC}"
    bundle exec rake test < /dev/null || bundle exec rspec < /dev/null || { echo -e "${RED}❌ Fallaron los tests de Ruby.${NC}"; exit 1; }
    TESTS_RUN=$((TESTS_RUN+1))
fi

# PHP Tests
if [ -f "composer.json" ]; then
    echo -e "${BLUE}Ejecutando tests de PHP...${NC}"
    composer test < /dev/null || ./vendor/bin/phpunit < /dev/null || { echo -e "${RED}❌ Fallaron los tests de PHP.${NC}"; exit 1; }
    TESTS_RUN=$((TESTS_RUN+1))
fi

# .NET / C# Tests
if [ -n "$(find . -maxdepth 2 -name "*.sln" -o -name "*.csproj" 2>/dev/null | head -n 1)" ]; then
    echo -e "${BLUE}Ejecutando tests de .NET...${NC}"
    dotnet test < /dev/null || { echo -e "${RED}❌ Fallaron los tests de .NET.${NC}"; exit 1; }
    TESTS_RUN=$((TESTS_RUN+1))
fi

if [ $TESTS_RUN -eq 0 ]; then
    echo -e "${YELLOW}⚠️ No se detectó ninguna suite de tests automática conocida. Procediendo con push...${NC}"
else
    echo -e "${GREEN}✅ Se ejecutaron $TESTS_RUN suite(s) de tests exitosamente.${NC}"
fi

echo -e "${GREEN}🚀 Todo en orden. Procediendo con git push...${NC}"
exit 0
"""


def install_git_hooks(
    target_dir: Optional[Union[str, Path]] = None,
    is_global: bool = False,
    force: bool = True,
) -> Dict[str, Any]:
    """
    Instala y configura el hook pre-push multi-stack canónico.

    :param target_dir: Directorio raíz del repositorio destino (ignorado si is_global=True).
    :param is_global: Si es True, instala en ~/.githooks/pre-push y configura git global core.hooksPath.
    :param force: Si es True, sobreescribe hooks existentes.
    :return: Diccionario con el resultado de la instalación.
    """
    script_content = generate_canonical_pre_push_script()

    if is_global:
        hooks_dir = Path.home() / ".githooks"
        hook_path = hooks_dir / "pre-push"
        hooks_dir.mkdir(parents=True, exist_ok=True)

        if hook_path.exists() and not force:
            return {
                "success": False,
                "message": f"El hook global ya existe en {hook_path}. Usa --force para sobreescribir.",
                "hook_path": str(hook_path),
                "is_global": True,
            }

        hook_path.write_text(script_content, encoding="utf-8")
        hook_path.chmod(hook_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

        cmd = "git config --global core.hooksPath ~/.githooks"
        code, out, err = run_command_safe(cmd, cwd=Path.home(), isolated_git=False)
        return {
            "success": code == 0,
            "message": f"Hook global instalado exitosamente en {hook_path} y configurado core.hooksPath.",
            "hook_path": str(hook_path),
            "is_global": True,
        }

    # Instalación local
    root = Path(target_dir).resolve() if target_dir else Path.cwd().resolve()
    hooks_dir = root / ".githooks"
    hook_path = hooks_dir / "pre-push"
    hooks_dir.mkdir(parents=True, exist_ok=True)

    if hook_path.exists() and not force:
        return {
            "success": False,
            "message": f"El hook local ya existe en {hook_path}. Usa --force para sobreescribir.",
            "hook_path": str(hook_path),
            "is_global": False,
        }

    hook_path.write_text(script_content, encoding="utf-8")
    hook_path.chmod(hook_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    cmd = "git config core.hooksPath .githooks"
    code, out, err = run_command_safe(cmd, cwd=root, isolated_git=True)
    return {
        "success": code == 0,
        "message": f"Hook local instalado exitosamente en {hook_path} y configurado core.hooksPath en .githooks.",
        "hook_path": str(hook_path),
        "is_global": False,
    }


def uninstall_git_hooks(
    target_dir: Optional[Union[str, Path]] = None,
    is_global: bool = False,
) -> Dict[str, Any]:
    """
    Desinstala o desconfigura el hook pre-push.
    """
    if is_global:
        hooks_dir = Path.home() / ".githooks"
        hook_path = hooks_dir / "pre-push"
        if hook_path.exists():
            hook_path.unlink()

        cmd = "git config --global --unset core.hooksPath"
        run_command_safe(cmd, cwd=Path.home(), isolated_git=False)
        return {
            "success": True,
            "message": "Hook global desinstalado y core.hooksPath desvinculado.",
            "is_global": True,
        }

    root = Path(target_dir).resolve() if target_dir else Path.cwd().resolve()
    hooks_dir = root / ".githooks"
    hook_path = hooks_dir / "pre-push"
    if hook_path.exists():
        hook_path.unlink()

    cmd = "git config --unset core.hooksPath"
    run_command_safe(cmd, cwd=root, isolated_git=True)
    return {
        "success": True,
        "message": f"Hook local desinstalado en {root} y core.hooksPath desvinculado.",
        "is_global": False,
    }


def get_hooks_status(
    target_dir: Optional[Union[str, Path]] = None,
) -> Dict[str, Any]:
    """
    Diagnóstico del estado de Git Hooks local y global.
    """
    root = Path(target_dir).resolve() if target_dir else Path.cwd().resolve()

    # Estado Local
    local_hook = root / ".githooks" / "pre-push"
    _, local_cfg_raw, _ = run_command_safe("git config --get core.hooksPath", cwd=root, isolated_git=True)
    local_cfg = local_cfg_raw.strip()
    local_active = local_hook.exists() and os.access(local_hook, os.X_OK) and (local_cfg in [".githooks", str(root / ".githooks")])

    # Estado Global
    global_hook = Path.home() / ".githooks" / "pre-push"
    _, global_cfg_raw, _ = run_command_safe("git config --global --get core.hooksPath", cwd=Path.home(), isolated_git=False)
    global_cfg = global_cfg_raw.strip()
    global_active = global_hook.exists() and os.access(global_hook, os.X_OK) and (global_cfg in ["~/.githooks", str(Path.home() / ".githooks")])

    return {
        "local": {
            "hook_exists": local_hook.exists(),
            "is_executable": os.access(local_hook, os.X_OK) if local_hook.exists() else False,
            "hook_path": str(local_hook),
            "configured_hooks_path": local_cfg,
            "is_active": local_active,
        },
        "global": {
            "hook_exists": global_hook.exists(),
            "is_executable": os.access(global_hook, os.X_OK) if global_hook.exists() else False,
            "hook_path": str(global_hook),
            "configured_hooks_path": global_cfg,
            "is_active": global_active,
        },
    }
