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
from importlib.resources import files
from pathlib import Path
from typing import Any

from workspace_engine.common import run_command_safe


def generate_canonical_pre_push_script() -> str:
    """Genera el script bash canónico de 5 etapas para el hook pre-push."""
    return (
        files("workspace_engine")
        .joinpath("resources", "hooks", "pre-push")
        .read_text(encoding="utf-8")
    )


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
    output: str = "errors",
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
    env["QG_OUTPUT"] = output
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
