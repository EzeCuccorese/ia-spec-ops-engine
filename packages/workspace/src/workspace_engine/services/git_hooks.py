"""
workspace_engine.services.git_hooks — Gestor de Git Hooks e instalación de Quality Gates Multi-Stack.

Provee instalación, desinstalación y verificación de estado para hooks locales (.githooks/)
y globales (~/.githooks/) con soporte multi-lenguaje (Python, Node/React, Java/Kotlin, Go, Rust, Flutter, etc.).
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from workspace_engine.common import run_command_safe


def generate_canonical_pre_push_script() -> str:
    """Genera el script bash canónico de 5 etapas para el hook pre-push."""
    return r"""#!/usr/bin/env bash
# Global Quality Gate pre-push hook
# Instalado con: git config --global core.hooksPath ~/.githooks
#
# Variables de entorno:
#   QG_SCOPE=all|changed        Alcance de linters y tests (default: all)
#   QG_SKIP=a,b,c               Saltea checks: gitleaks,commits,lint,tests,repohooks,all
#   QG_TIMEOUT=900              Timeout en segundos por paso
#   QG_COMMIT_STYLE=conventional  Exige Conventional Commits en los mensajes
#   QG_PROTECTED="^(main)$"     Regex de ramas protegidas (override)
set -uo pipefail

QG_SCOPE="${QG_SCOPE:-all}"
QG_SKIP="${QG_SKIP:-}"
QG_TIMEOUT="${QG_TIMEOUT:-900}"
QG_COMMIT_STYLE="${QG_COMMIT_STYLE:-}"
PROTECTED_BRANCHES="${QG_PROTECTED:-^(main|master|develop|staging)\$}"

ZERO="0000000000000000000000000000000000000000"
EMPTY_TREE="4b825dc642cb6eb9a060e54bf8d69288fbee4904"

# Evita que jest/vitest/etc arranquen en modo watch y cuelguen el push para siempre.
export CI=1

echo "[Quality Gate Pre-Push Hook] Verificando calidad y seguridad antes de enviar cambios..."

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || REPO_ROOT=""
if [ -z "$REPO_ROOT" ]; then
  exit 0
fi
cd "$REPO_ROOT" || exit 1
# Git exports repository-local variables to hooks. They would otherwise leak
# into test subprocesses that create or inspect a different temporary repo.
unset $(git rev-parse --local-env-vars)

abspath() { (cd "$(dirname "$1")" 2>/dev/null && printf '%s/%s\n' "$(pwd -P)" "$(basename "$1")"); }
SELF_ABS="$(abspath "$0")"
SELF_DIR="$(dirname "$SELF_ABS")"

FAILED=0
FAILED_STEPS=""
fail() { echo "✘ $1: FAIL"; FAILED=1; FAILED_STEPS="${FAILED_STEPS}  - $1"$'\n'; }
pass() { echo "✔ $1: PASS"; }
warn() { echo "⚠  $1"; }
note() { echo "   $1"; }

skipped() {
  case ",${QG_SKIP}," in
    *,all,*) return 0 ;;
    *",$1,"*) return 0 ;;
  esac
  return 1
}

TIMEOUT_BIN=""
if command -v timeout >/dev/null 2>&1; then
  TIMEOUT_BIN="timeout"
elif command -v gtimeout >/dev/null 2>&1; then
  TIMEOUT_BIN="gtimeout"
fi

# Corre un comando con límite de tiempo, para que ninguna herramienta colgada trabe el push.
run_to() {
  local secs="$1"; shift
  local rc=0
  if [ -n "$TIMEOUT_BIN" ]; then
    "$TIMEOUT_BIN" "$secs" "$@"; rc=$?
  elif command -v perl >/dev/null 2>&1; then
    perl -e 'alarm shift; exec @ARGV' "$secs" "$@"; rc=$?
  else
    "$@"; rc=$?
  fi
  if [ "$rc" = "124" ] || [ "$rc" = "142" ]; then
    echo "   ⏱  '$1' excedió ${secs}s y fue abortado (subí QG_TIMEOUT si es esperable)."
  fi
  return $rc
}

TMPD="$(mktemp -d "${TMPDIR:-/tmp}/qg.XXXXXX")" || exit 1
trap 'rm -rf "$TMPD"' EXIT INT TERM

# --- stdin -------------------------------------------------------------------
# Git manda una línea por ref: "local_ref local_sha remote_ref remote_sha".
# Lo guardamos en un archivo para poder re-alimentarlo al hook propio del repo.
STDIN_FILE="$TMPD/stdin"
cat > "$STDIN_FILE"

LOGOPTS=()   # rango en formato "git log" para gitleaks / rev-list
BASES=()     # commit base para el diff
TIPS=()      # commit punta para el diff

while read -r local_ref local_sha remote_ref remote_sha; do
  [ -n "${local_ref}${local_sha}${remote_ref}${remote_sha}" ] || continue

  # La rama protegida es la de DESTINO (remote_ref), no la local: si no,
  # "git push origin feature:main" se colaba sin control.
  target_ref="$remote_ref"
  [ -n "$target_ref" ] || target_ref="$local_ref"
  branch_name="${target_ref#refs/heads/}"
  if [[ "$branch_name" =~ $PROTECTED_BRANCHES ]]; then
    if [ "$local_sha" = "$ZERO" ]; then
      echo "🚫 Borrar la rama protegida '$branch_name' en el remoto está bloqueado."
    else
      echo "🚫 Push directo a rama protegida '$branch_name' está bloqueado. Usá un PR/MR."
    fi
    exit 1
  fi

  # Borrado de rama no protegida: no hay contenido nuevo que revisar.
  [ "$local_sha" = "$ZERO" ] && continue

  if [ "$remote_sha" != "$ZERO" ] && git cat-file -e "${remote_sha}^{commit}" 2>/dev/null; then
    LOGOPTS+=("${remote_sha}..${local_sha}")
    BASES+=("$remote_sha")
    TIPS+=("$local_sha")
  else
    # Rama nueva: lo nuevo es lo que no está en NINGÚN remoto.
    LOGOPTS+=("$local_sha --not --remotes")
    first_new="$(git rev-list --reverse "$local_sha" --not --remotes 2>/dev/null | head -1)"
    if [ -n "$first_new" ] && git rev-parse --verify --quiet "${first_new}^" >/dev/null 2>&1; then
      BASES+=("${first_new}^")
    elif [ -n "$first_new" ]; then
      BASES+=("$EMPTY_TREE")
    else
      BASES+=("$local_sha")
    fi
    TIPS+=("$local_sha")
  fi
done < "$STDIN_FILE"

NOTHING_NEW=0
[ "${#TIPS[@]}" -eq 0 ] && NOTHING_NEW=1

DIFF_FILES_FILE="$TMPD/files"
COMMITS_FILE="$TMPD/commits"
: > "$DIFF_FILES_FILE"
: > "$COMMITS_FILE"

if [ "$NOTHING_NEW" = "0" ]; then
  i=0
  while [ "$i" -lt "${#TIPS[@]}" ]; do
    # --diff-filter=ACMR excluye borrados: no tiene sentido lintear un archivo que ya no existe.
    git diff --name-only --diff-filter=ACMR "${BASES[$i]}" "${TIPS[$i]}" 2>/dev/null >> "$DIFF_FILES_FILE"
    # shellcheck disable=SC2086
    git rev-list ${LOGOPTS[$i]} 2>/dev/null >> "$COMMITS_FILE"
    i=$((i + 1))
  done
  sort -u "$DIFF_FILES_FILE" > "$TMPD/f2" && mv "$TMPD/f2" "$DIFF_FILES_FILE"
  sort -u "$COMMITS_FILE" > "$TMPD/c2" && mv "$TMPD/c2" "$COMMITS_FILE"
  note "$(wc -l < "$COMMITS_FILE" | tr -d ' ') commit(s) y $(wc -l < "$DIFF_FILES_FILE" | tr -d ' ') archivo(s) en este push. Alcance de lint/tests: $QG_SCOPE"
fi

# Imprime los archivos del push que matchean alguno de los globs dados.
changed_files() {
  local f pat
  while IFS= read -r f; do
    [ -n "$f" ] || continue
    for pat in "$@"; do
      case "$f" in
        $pat) printf '%s\n' "$f"; break ;;
      esac
    done
  done < "$DIFF_FILES_FILE"
}

# ---------- [1/5] Seguridad y escaneo de secretos ----------
echo ""
echo "🔒 [1/5] Verificando secretos en los commits que se pushean..."
if skipped gitleaks; then
  warn "Seguridad y Secretos: salteado por QG_SKIP"
elif [ "$NOTHING_NEW" = "1" ]; then
  note "Sin commits nuevos, se omite."
elif ! command -v gitleaks >/dev/null 2>&1; then
  warn "gitleaks no está instalado, se omite el escaneo (brew install gitleaks)."
else
  GL_SUB="detect"
  gitleaks git --help >/dev/null 2>&1 && GL_SUB="git"
  GL_CFG=()
  [ -f "$REPO_ROOT/.gitleaks.toml" ] && GL_CFG=(--config "$REPO_ROOT/.gitleaks.toml")

  GL_OK=1
  i=0
  while [ "$i" -lt "${#LOGOPTS[@]}" ]; do
    log="$TMPD/gitleaks-$i.log"
    rc=0
    if [ "$GL_SUB" = "git" ]; then
      run_to "$QG_TIMEOUT" gitleaks git "$REPO_ROOT" ${GL_CFG+"${GL_CFG[@]}"} \
        --log-opts="${LOGOPTS[$i]}" --no-banner -v --exit-code 1 > "$log" 2>&1 || rc=$?
    else
      run_to "$QG_TIMEOUT" gitleaks detect --source "$REPO_ROOT" ${GL_CFG+"${GL_CFG[@]}"} \
        --log-opts="${LOGOPTS[$i]}" --no-banner -v --exit-code 1 > "$log" 2>&1 || rc=$?
    fi
    if [ "$rc" != "0" ]; then
      GL_OK=0
      cat "$log"
    fi
    i=$((i + 1))
  done

  if [ "$GL_OK" = "1" ]; then
    pass "Seguridad y Secretos"
  else
    note "Si son falsos positivos, agregá una allowlist en .gitleaks.toml del repo."
    fail "Seguridad y Secretos"
  fi
fi

# ---------- [2/5] Políticas de commit ----------
echo ""
echo "📝 [2/5] Verificando políticas de commit..."
if skipped commits; then
  warn "Políticas Git: salteado por QG_SKIP"
elif [ "$NOTHING_NEW" = "1" ]; then
  note "Sin commits nuevos, se omite."
else
  COMMITS_OK=1
  while IFS= read -r sha; do
    [ -n "$sha" ] || continue
    subject="$(git log -1 --format=%s "$sha")"
    body="$(git log -1 --format=%B "$sha")"

    if [ -z "$(printf '%s' "$body" | tr -d '[:space:]')" ]; then
      echo "   ✘ ${sha:0:8} tiene mensaje vacío."
      COMMITS_OK=0
      continue
    fi

    case "$subject" in
      fixup!*|squash!*|amend!*)
        echo "   ✘ ${sha:0:8} es un commit '$subject' sin aplicar. Corré 'git rebase -i --autosquash' antes de pushear."
        COMMITS_OK=0
        continue
        ;;
    esac

    if [ "${#subject}" -gt 100 ]; then
      warn "${sha:0:8} tiene un asunto de ${#subject} caracteres (recomendado: <= 72)."
    fi

    if [ "$QG_COMMIT_STYLE" = "conventional" ]; then
      if ! printf '%s' "$subject" | grep -Eq '^(build|chore|ci|docs|feat|fix|perf|refactor|revert|style|test)(\([^)]+\))?!?: .+'; then
        echo "   ✘ ${sha:0:8} no sigue Conventional Commits: '$subject'"
        COMMITS_OK=0
      fi
    fi
  done < "$COMMITS_FILE"

  if [ "$COMMITS_OK" = "1" ]; then
    pass "Políticas Git"
  else
    fail "Políticas Git"
  fi
fi

# ---------- [3/5] Linters y análisis estático ----------
echo ""
echo "🔍 [3/5] Ejecutando análisis estático y linters..."
if skipped lint; then
  warn "Linters y Análisis Estático: salteado por QG_SKIP"
else
  LINT_OK=1
  LINT_RAN=0

  # --- JS / TS ---
  if [ -f "$REPO_ROOT/package.json" ]; then
    HAS_LINT_SCRIPT=0
    if command -v node >/dev/null 2>&1 && \
       node -e "const p=require('$REPO_ROOT/package.json'); process.exit(p.scripts && p.scripts.lint ? 0 : 1)" 2>/dev/null; then
      HAS_LINT_SCRIPT=1
    fi

    JS_FILES=()
    if [ "$QG_SCOPE" = "changed" ] && [ "$NOTHING_NEW" = "0" ]; then
      while IFS= read -r f; do
        [ -n "$f" ] && [ -f "$f" ] && JS_FILES+=("$f")
      done < <(changed_files '*.js' '*.jsx' '*.mjs' '*.cjs' '*.ts' '*.tsx' '*.vue' '*.svelte')
    fi

    if [ "$QG_SCOPE" = "changed" ] && [ -x "$REPO_ROOT/node_modules/.bin/eslint" ]; then
      if [ "${#JS_FILES[@]}" -gt 0 ]; then
        LINT_RAN=1
        note "eslint sobre ${#JS_FILES[@]} archivo(s) del push"
        run_to "$QG_TIMEOUT" "$REPO_ROOT/node_modules/.bin/eslint" "${JS_FILES[@]}" || LINT_OK=0
      else
        note "Sin archivos JS/TS en el push, se omite eslint."
      fi
    elif [ "$HAS_LINT_SCRIPT" = "1" ] && command -v npm >/dev/null 2>&1; then
      LINT_RAN=1
      [ "$QG_SCOPE" = "changed" ] && note "No hay eslint local para acotar; corriendo 'npm run lint' completo."
      run_to "$QG_TIMEOUT" npm run lint || LINT_OK=0
    fi
  fi

  # --- Python ---
  if [ -f "$REPO_ROOT/pyproject.toml" ] || [ -f "$REPO_ROOT/requirements.txt" ] || ls "$REPO_ROOT"/*.py >/dev/null 2>&1; then
    RUFF_EXE=""
    if command -v ruff >/dev/null 2>&1; then
      RUFF_EXE="ruff"
    elif [ -x "$REPO_ROOT/.venv/bin/ruff" ]; then
      RUFF_EXE="$REPO_ROOT/.venv/bin/ruff"
    elif command -v uv >/dev/null 2>&1; then
      RUFF_EXE="uv run --with ruff ruff"
    fi

    if [ -n "$RUFF_EXE" ]; then
      PY_FILES=()
      if [ "$QG_SCOPE" = "changed" ] && [ "$NOTHING_NEW" = "0" ]; then
        while IFS= read -r f; do
          [ -n "$f" ] && [ -f "$f" ] && PY_FILES+=("$f")
        done < <(changed_files '*.py' '*.pyi')
      fi

      if [ "$QG_SCOPE" = "changed" ]; then
        if [ "${#PY_FILES[@]}" -gt 0 ]; then
          LINT_RAN=1
          note "ruff sobre ${#PY_FILES[@]} archivo(s) del push"
          run_to "$QG_TIMEOUT" $RUFF_EXE check "${PY_FILES[@]}" || LINT_OK=0
        else
          note "Sin archivos Python en el push, se omite ruff."
        fi
      else
        LINT_RAN=1
        run_to "$QG_TIMEOUT" $RUFF_EXE check . || LINT_OK=0
      fi
    fi
  fi

  # --- Go ---
  if [ -f "$REPO_ROOT/go.mod" ] && command -v go >/dev/null 2>&1; then
    LINT_RAN=1
    note "go vet sobre el repositorio"
    run_to "$QG_TIMEOUT" go vet ./... || LINT_OK=0
  fi

  # --- Rust ---
  if [ -f "$REPO_ROOT/Cargo.toml" ] && command -v cargo >/dev/null 2>&1; then
    LINT_RAN=1
    note "cargo clippy"
    run_to "$QG_TIMEOUT" cargo clippy -- -D warnings || LINT_OK=0
  fi

  # --- Flutter / Dart ---
  if [ -f "$REPO_ROOT/pubspec.yaml" ]; then
    if command -v flutter >/dev/null 2>&1; then
      LINT_RAN=1
      note "flutter analyze"
      run_to "$QG_TIMEOUT" flutter analyze || LINT_OK=0
    elif command -v dart >/dev/null 2>&1; then
      LINT_RAN=1
      note "dart analyze"
      run_to "$QG_TIMEOUT" dart analyze || LINT_OK=0
    fi
  fi

  # --- PHP ---
  if [ -f "$REPO_ROOT/composer.json" ]; then
    PHP_FILES=()
    while IFS= read -r f; do
      [ -n "$f" ] && [ -f "$f" ] && PHP_FILES+=("$f")
    done < <(changed_files '*.php')

    if [ -f "$REPO_ROOT/vendor/bin/phpcs" ]; then
      if [ "$QG_SCOPE" = "changed" ] && [ "$NOTHING_NEW" = "0" ]; then
        if [ "${#PHP_FILES[@]}" -gt 0 ]; then
          LINT_RAN=1
          note "phpcs sobre ${#PHP_FILES[@]} archivo(s) del push"
          run_to "$QG_TIMEOUT" "$REPO_ROOT/vendor/bin/phpcs" "${PHP_FILES[@]}" || LINT_OK=0
        else
          note "Sin archivos PHP en el push, se omite phpcs."
        fi
      else
        LINT_RAN=1
        run_to "$QG_TIMEOUT" "$REPO_ROOT/vendor/bin/phpcs" || LINT_OK=0
      fi
    elif command -v php >/dev/null 2>&1 && [ "${#PHP_FILES[@]}" -gt 0 ]; then
      LINT_RAN=1
      note "php -l sobre ${#PHP_FILES[@]} archivo(s) del push"
      for f in "${PHP_FILES[@]}"; do
        php -l "$f" >/dev/null || LINT_OK=0
      done
    fi
  fi

  if [ "$LINT_RAN" = "0" ]; then
    note "No se detectaron linters aplicables; se omite."
    pass "Linters y Análisis Estático"
  elif [ "$LINT_OK" = "1" ]; then
    pass "Linters y Análisis Estático"
  else
    fail "Linters y Análisis Estático"
  fi
fi

# ---------- [4/5] Suites de tests ----------
echo ""
echo "🧪 [4/5] Ejecutando suites de tests..."
if skipped tests; then
  warn "Suites de Tests: salteado por QG_SKIP"
else
  TESTS_OK=1
  RAN_ANY=0
  SCOPED_TESTS=0
  [ "$QG_SCOPE" = "changed" ] && [ "$NOTHING_NEW" = "0" ] && SCOPED_TESTS=1

  # --- JS / TS ---
  if [ -f "$REPO_ROOT/package.json" ] && command -v npm >/dev/null 2>&1 && command -v node >/dev/null 2>&1; then
    if node -e "const p=require('$REPO_ROOT/package.json'); process.exit(p.scripts && p.scripts.test ? 0 : 1)" 2>/dev/null; then
      TEST_SCRIPT="$(node -e "const p=require('$REPO_ROOT/package.json'); process.stdout.write(String(p.scripts.test||''))" 2>/dev/null)"

      JS_FILES=()
      if [ "$SCOPED_TESTS" = "1" ]; then
        while IFS= read -r f; do
          [ -n "$f" ] && [ -f "$f" ] && JS_FILES+=("$f")
        done < <(changed_files '*.js' '*.jsx' '*.mjs' '*.cjs' '*.ts' '*.tsx' '*.vue' '*.svelte')
      fi

      RUNNER=""
      case "$TEST_SCRIPT" in
        *vitest*) [ -x "$REPO_ROOT/node_modules/.bin/vitest" ] && RUNNER="vitest" ;;
        *jest*)   [ -x "$REPO_ROOT/node_modules/.bin/jest" ] && RUNNER="jest" ;;
      esac

      if [ "$SCOPED_TESTS" = "1" ] && [ -n "$RUNNER" ] && [ "${#JS_FILES[@]}" -gt 0 ]; then
        RAN_ANY=1
        note "$RUNNER acotado a ${#JS_FILES[@]} archivo(s) del push"
        if [ "$RUNNER" = "jest" ]; then
          run_to "$QG_TIMEOUT" "$REPO_ROOT/node_modules/.bin/jest" --ci --watchAll=false \
            --passWithNoTests --findRelatedTests "${JS_FILES[@]}" || TESTS_OK=0
        else
          run_to "$QG_TIMEOUT" "$REPO_ROOT/node_modules/.bin/vitest" related --run \
            --passWithNoTests "${JS_FILES[@]}" || TESTS_OK=0
        fi
      elif [ "$SCOPED_TESTS" = "1" ] && [ -n "$RUNNER" ]; then
        note "Sin archivos JS/TS en el push, se omite $RUNNER."
      else
        RAN_ANY=1
        [ "$SCOPED_TESTS" = "1" ] && note "No se pudo acotar '$TEST_SCRIPT'; corriendo la suite completa."
        run_to "$QG_TIMEOUT" npm test || TESTS_OK=0
      fi
    fi
  fi

  # --- Python ---
  PYTEST_EXE=""
  if [ -x "$REPO_ROOT/.venv/bin/pytest" ]; then
    PYTEST_EXE="$REPO_ROOT/.venv/bin/pytest"
  elif command -v pytest >/dev/null 2>&1; then
    PYTEST_EXE="pytest"
  elif command -v uv >/dev/null 2>&1; then
    PYTEST_EXE="uv run pytest"
  fi

  if [ -n "$PYTEST_EXE" ]; then
    PY_TEST_FILES=()
    if [ "$SCOPED_TESTS" = "1" ]; then
      while IFS= read -r f; do
        [ -n "$f" ] && [ -f "$f" ] && PY_TEST_FILES+=("$f")
      done < <(changed_files '*test_*.py' '*_test.py' '*/tests/*.py')
    fi

    if [ "$SCOPED_TESTS" = "1" ]; then
      if [ "${#PY_TEST_FILES[@]}" -gt 0 ]; then
        RAN_ANY=1
        note "pytest acotado a ${#PY_TEST_FILES[@]} archivo(s) de test del push"
        run_to "$QG_TIMEOUT" $PYTEST_EXE -q "${PY_TEST_FILES[@]}"; pt_rc=$?
        if [ "$pt_rc" != "0" ] && [ "$pt_rc" != "5" ]; then TESTS_OK=0; fi
      fi
    elif find "$REPO_ROOT" -maxdepth 6 -not -path "*/node_modules/*" -not -path "*/.venv/*" \
              -not -path "*/vendor/*" -not -path "*/.git/*" \
              \( -iname "test_*.py" -o -iname "*_test.py" \) 2>/dev/null | grep -q .; then
      RAN_ANY=1
      run_to "$QG_TIMEOUT" $PYTEST_EXE -q; pt_rc=$?
      if [ "$pt_rc" != "0" ] && [ "$pt_rc" != "5" ]; then TESTS_OK=0; fi
    fi
  fi

  # --- Go Tests ---
  if [ -f "$REPO_ROOT/go.mod" ] && command -v go >/dev/null 2>&1; then
    RAN_ANY=1
    note "go test ./..."
    run_to "$QG_TIMEOUT" go test ./... || TESTS_OK=0
  fi

  # --- Rust Tests ---
  if [ -f "$REPO_ROOT/Cargo.toml" ] && command -v cargo >/dev/null 2>&1; then
    RAN_ANY=1
    note "cargo test"
    run_to "$QG_TIMEOUT" cargo test || TESTS_OK=0
  fi

  # --- Flutter / Dart Tests ---
  if [ -f "$REPO_ROOT/pubspec.yaml" ]; then
    if command -v flutter >/dev/null 2>&1; then
      RAN_ANY=1
      note "flutter test"
      run_to "$QG_TIMEOUT" flutter test || TESTS_OK=0
    elif command -v dart >/dev/null 2>&1; then
      RAN_ANY=1
      note "dart test"
      run_to "$QG_TIMEOUT" dart test || TESTS_OK=0
    fi
  fi

  # --- PHP ---
  if [ -f "$REPO_ROOT/composer.json" ]; then
    if [ -f "$REPO_ROOT/vendor/bin/phpunit" ]; then
      PHP_TEST_FILES=()
      if [ "$SCOPED_TESTS" = "1" ]; then
        while IFS= read -r f; do
          [ -n "$f" ] && [ -f "$f" ] && PHP_TEST_FILES+=("$f")
        done < <(changed_files '*Test.php' '*/tests/*.php' '*/Tests/*.php')
      fi

      if [ "$SCOPED_TESTS" = "1" ]; then
        if [ "${#PHP_TEST_FILES[@]}" -gt 0 ]; then
          RAN_ANY=1
          note "phpunit acotado a ${#PHP_TEST_FILES[@]} archivo(s) de test del push"
          run_to "$QG_TIMEOUT" "$REPO_ROOT/vendor/bin/phpunit" "${PHP_TEST_FILES[@]}" || TESTS_OK=0
        fi
      else
        RAN_ANY=1
        run_to "$QG_TIMEOUT" "$REPO_ROOT/vendor/bin/phpunit" || TESTS_OK=0
      fi
    elif command -v composer >/dev/null 2>&1 && grep -q '"test"' "$REPO_ROOT/composer.json" 2>/dev/null; then
      RAN_ANY=1
      run_to "$QG_TIMEOUT" composer test || TESTS_OK=0
    fi
  fi

  # --- JVM (sin acotar: mvn/gradle no exponen un "solo estos tests" confiable) ---
  if [ -f "$REPO_ROOT/pom.xml" ]; then
    if command -v mvn >/dev/null 2>&1; then
      RAN_ANY=1
      [ "$SCOPED_TESTS" = "1" ] && note "Maven no se puede acotar de forma confiable; suite completa."
      run_to "$QG_TIMEOUT" mvn -q -B test || TESTS_OK=0
    else
      warn "Hay pom.xml pero 'mvn' no está instalado; se omiten los tests de Maven."
    fi
  fi

  if [ -f "$REPO_ROOT/build.gradle" ] || [ -f "$REPO_ROOT/build.gradle.kts" ]; then
    if [ -x "$REPO_ROOT/gradlew" ]; then
      RAN_ANY=1
      [ "$SCOPED_TESTS" = "1" ] && note "Gradle no se puede acotar de forma confiable; suite completa."
      run_to "$QG_TIMEOUT" "$REPO_ROOT/gradlew" test || TESTS_OK=0
    elif command -v gradle >/dev/null 2>&1; then
      RAN_ANY=1
      run_to "$QG_TIMEOUT" gradle test || TESTS_OK=0
    else
      warn "Hay build.gradle pero no hay ./gradlew ni 'gradle' instalado; se omiten los tests."
    fi
  fi

  if [ "$RAN_ANY" = "0" ]; then
    note "No se ejecutaron suites de tests para este stack; se omite."
    pass "Suites de Tests"
  elif [ "$TESTS_OK" = "1" ]; then
    pass "Suites de Tests"
  else
    fail "Suites de Tests"
  fi
fi

# ---------- [5/5] Hooks propios del repositorio ----------
# core.hooksPath global hace que git IGNORE el pre-push del repo (Husky incluido).
# Acá lo recuperamos: buscamos el hook del repo y lo corremos con el mismo stdin y argumentos.
echo ""
echo "🪝 [5/5] Delegando al hook pre-push del repositorio (Husky u otro)..."
if [ "${QG_IN_REPO_HOOK:-0}" = "1" ]; then
  note "Ya estamos dentro de un hook delegado; no se re-delega."
elif skipped repohooks; then
  warn "HOOKS DEL REPO SALTEADOS por QG_SKIP=repohooks. Los checks propios del proyecto NO corrieron."
else
  HOOK_CANDS=()
  LOCAL_HP="$(git config --local --get core.hooksPath 2>/dev/null || true)"
  [ -n "$LOCAL_HP" ] && HOOK_CANDS+=("$LOCAL_HP/pre-push")
  HOOK_CANDS+=(".husky/_/pre-push" ".husky/pre-push" ".git/hooks/pre-push" ".githooks/pre-push")

  REPO_HOOK=""
  for cand in "${HOOK_CANDS[@]}"; do
    [ -f "$cand" ] || continue
    case "$cand" in *.sample) continue ;; esac
    cand_abs="$(abspath "$cand")" || continue
    [ -n "$cand_abs" ] || continue
    # Nunca delegar a nosotros mismos ni a otro hook de este mismo directorio: sería recursión infinita.
    [ "$cand_abs" = "$SELF_ABS" ] && continue
    [ "$(dirname "$cand_abs")" = "$SELF_DIR" ] && continue
    REPO_HOOK="$cand_abs"
    break
  done

  if [ -z "$REPO_HOOK" ]; then
    note "El repo no tiene hook pre-push propio."
    pass "Hooks del Repositorio"
  else
    note "Ejecutando ${REPO_HOOK#$REPO_ROOT/}"
    export QG_IN_REPO_HOOK=1
    rh_rc=0
    if [ -x "$REPO_HOOK" ]; then
      run_to "$QG_TIMEOUT" "$REPO_HOOK" "$@" < "$STDIN_FILE" || rh_rc=$?
    else
      run_to "$QG_TIMEOUT" sh "$REPO_HOOK" "$@" < "$STDIN_FILE" || rh_rc=$?
    fi
    unset QG_IN_REPO_HOOK
    if [ "$rh_rc" = "0" ]; then
      pass "Hooks del Repositorio"
    else
      fail "Hooks del Repositorio (${REPO_HOOK#$REPO_ROOT/} salió con código $rh_rc)"
    fi
  fi
fi

echo ""
if [ "$FAILED" = "1" ]; then
  echo "🛑 Quality Gate falló. Push cancelado. Checks en rojo:"
  printf '%s' "$FAILED_STEPS"
  echo ""
  echo "Para saltear un check puntual (no todo el gate):"
  echo "  QG_SKIP=gitleaks git push          # gitleaks,commits,lint,tests,repohooks"
  echo "Para acotar lint y tests a los archivos del push:"
  echo "  QG_SCOPE=changed git push"
  exit 1
fi

echo "🚀 Todo en orden. Procediendo con git push..."
exit 0
"""


def install_git_hooks(
    target_dir: str | Path | None = None,
    is_global: bool = False,
    force: bool = True,
) -> dict[str, Any]:
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
    target_dir: str | Path | None = None,
    is_global: bool = False,
) -> dict[str, Any]:
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
    target_dir: str | Path | None = None,
) -> dict[str, Any]:
    """
    Diagnóstico del estado de Git Hooks local y global.
    """
    root = Path(target_dir).resolve() if target_dir else Path.cwd().resolve()

    # Estado Local
    local_hook = root / ".githooks" / "pre-push"
    _, local_cfg_raw, _ = run_command_safe(
        "git config --get core.hooksPath", cwd=root, isolated_git=True
    )
    local_cfg = local_cfg_raw.strip()
    local_active = (
        local_hook.exists()
        and os.access(local_hook, os.X_OK)
        and (local_cfg in [".githooks", str(root / ".githooks")])
    )

    # Estado Global
    global_hook = Path.home() / ".githooks" / "pre-push"
    _, global_cfg_raw, _ = run_command_safe(
        "git config --global --get core.hooksPath", cwd=Path.home(), isolated_git=False
    )
    global_cfg = global_cfg_raw.strip()
    global_active = (
        global_hook.exists()
        and os.access(global_hook, os.X_OK)
        and (global_cfg in ["~/.githooks", str(Path.home() / ".githooks")])
    )

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


def run_quality_gate(
    target_dir: str | Path | None = None,
    scope: str = "all",
    skip: str | None = None,
    timeout: int = 900,
    commit_style: str | None = None,
) -> int:
    """
    Ejecuta el Quality Gate de Git Hooks a demanda en el repositorio indicado.
    Retorna el código de salida del script pre-push.
    """
    root = Path(target_dir).resolve() if target_dir else Path.cwd().resolve()
    local_hook = root / ".githooks" / "pre-push"
    global_hook = Path.home() / ".githooks" / "pre-push"

    hook_to_run = None
    if local_hook.is_file() and os.access(local_hook, os.X_OK):
        hook_to_run = local_hook
    elif global_hook.is_file() and os.access(global_hook, os.X_OK):
        hook_to_run = global_hook

    # Si no existe ningún hook instalado, escribir temporalmente el canónico
    temp_hook = None
    if not hook_to_run:
        script = generate_canonical_pre_push_script()
        temp_dir = Path(tempfile.mkdtemp(prefix="ws_qg_"))
        temp_hook = temp_dir / "pre-push"
        temp_hook.write_text(script, encoding="utf-8")
        temp_hook.chmod(temp_hook.stat().st_mode | stat.S_IXUSR)
        hook_to_run = temp_hook

    # Obtener el commit actual para stdin
    _, head_sha, _ = run_command_safe("git rev-parse HEAD", cwd=root)
    head_sha = head_sha.strip() or "0000000000000000000000000000000000000000"
    _, prev_sha, _ = run_command_safe("git rev-parse HEAD~1", cwd=root)
    prev_sha = prev_sha.strip() or "0000000000000000000000000000000000000000"

    ref_line = f"refs/heads/current {head_sha} refs/heads/current {prev_sha}\n"

    env = os.environ.copy()
    env["QG_SCOPE"] = scope
    if skip:
        env["QG_SKIP"] = skip
    env["QG_TIMEOUT"] = str(timeout)
    if commit_style:
        env["QG_COMMIT_STYLE"] = commit_style

    try:
        proc = subprocess.run(
            [str(hook_to_run), "origin"],
            cwd=root,
            input=ref_line,
            text=True,
            env=env,
        )
        return proc.returncode
    finally:
        if temp_hook and temp_hook.exists():
            shutil.rmtree(temp_hook.parent, ignore_errors=True)
