"""
workspace_engine.services.git_hooks — Git Hooks manager and Multi-Stack Quality Gate installer.

The quality gate is registered as a Git config-based hook
(``hook.workspace-gate.event=pre-push`` + ``hook.workspace-gate.command=<script>``),
never through ``core.hooksPath``. Git runs config hooks first and the repository's
own hook (``.git/hooks`` or a local ``core.hooksPath`` such as Husky) last, so the
gate never shadows project hooks of any type.

- Global: script in ``$XDG_CONFIG_HOME/workspace/hooks/pre-push``, keys in ``--global``.
- Local: script in ``<git-common-dir>/workspace/hooks/pre-push``, keys in the repo config.
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

HOOK_NAME = "workspace-gate"
HOOK_EVENT = "pre-push"
# Names QG_SKIP / `ws hooks run --skip` accept, in the order the gate runs them.
QG_STAGES = ("gitleaks", "commits", "lint", "design", "tests", "all")
# Companion hooks registered next to the gate: event -> config friendly name.
COMPANION_HOOKS = {"commit-msg": "workspace-commit-msg", "pre-commit": "workspace-pre-commit"}


def generate_canonical_pre_push_script() -> str:
    """Returns the canonical multi-stage bash quality gate script."""
    return (
        files("workspace_engine")
        .joinpath("resources", "hooks", "pre-push")
        .read_text(encoding="utf-8")
    )


def global_hook_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "workspace" / "hooks" / HOOK_EVENT


def local_hook_path(root: Path) -> Path:
    code, out, _ = run_command_safe(
        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
        cwd=root,
        isolated_git=True,
    )
    git_dir = Path(out.strip()) if code == 0 and out.strip() else root / ".git"
    return git_dir / "workspace" / "hooks" / HOOK_EVENT


def supports_config_hooks() -> bool:
    """True when the installed Git runs ``hook.<name>.command`` config hooks.

    Probed inside a throwaway repository: ``git hook list`` only resolves config
    hooks within a repository.
    """
    with tempfile.TemporaryDirectory(prefix="ws-hook-probe-") as probe:
        run_command_safe(["git", "init", "-q", probe], isolated_git=True)
        code, out, _ = run_command_safe(
            [
                "git",
                "-c",
                f"hook.{HOOK_NAME}-probe.event={HOOK_EVENT}",
                "-c",
                f"hook.{HOOK_NAME}-probe.command=true",
                "hook",
                "list",
                HOOK_EVENT,
            ],
            cwd=probe,
            isolated_git=True,
        )
    return code == 0 and f"{HOOK_NAME}-probe" in out


def _git_config(args: list[str], cwd: Path, is_global: bool) -> tuple[int, str, str]:
    scope = ["--global"] if is_global else []
    return run_command_safe(["git", "config", *scope, *args], cwd=cwd, isolated_git=not is_global)


def _write_script(hook_path: Path, event: str = HOOK_EVENT) -> None:
    hook_path.parent.mkdir(parents=True, exist_ok=True)
    source = files("workspace_engine").joinpath("resources", "hooks", event)
    hook_path.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    hook_path.chmod(hook_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _register_companions(hooks_dir: Path, cwd: Path, is_global: bool) -> bool:
    ok = True
    for event, name in COMPANION_HOOKS.items():
        script = hooks_dir / event
        _write_script(script, event)
        code_cmd, _, _ = _git_config([f"hook.{name}.command", str(script)], cwd, is_global)
        code_evt, _, _ = _git_config(["--replace-all", f"hook.{name}.event", event], cwd, is_global)
        ok = ok and code_cmd == 0 and code_evt == 0
    return ok


def install_git_hooks(
    target_dir: str | Path | None = None,
    is_global: bool = False,
) -> dict[str, Any]:
    """Installs the quality gate as a config-based pre-push hook (global or local).

    The scripts live in a workspace-owned directory, so a reinstall overwrites them
    (that is how an upgrade refreshes them); repository hooks are never touched.
    """
    cwd = Path.home() if is_global else Path(target_dir or Path.cwd()).resolve()
    if not supports_config_hooks():
        return {
            "success": False,
            "message": "This Git version does not support config-based hooks "
            "(hook.<name>.command); upgrade Git.",
            "is_global": is_global,
        }
    hook_path = global_hook_path() if is_global else local_hook_path(cwd)
    _write_script(hook_path)
    code_cmd, _, err_cmd = _git_config(
        [f"hook.{HOOK_NAME}.command", str(hook_path)], cwd, is_global
    )
    code_evt, _, err_evt = _git_config(
        ["--replace-all", f"hook.{HOOK_NAME}.event", HOOK_EVENT], cwd, is_global
    )
    success = (
        code_cmd == 0 and code_evt == 0 and _register_companions(hook_path.parent, cwd, is_global)
    )
    scope = "Global" if is_global else "Local"
    return {
        "success": success,
        "message": (
            f"{scope} quality gate registered as hook.{HOOK_NAME} ({hook_path}); "
            "repository hooks keep running after it."
            if success
            else f"git config failed: {(err_cmd or err_evt).strip()}"
        ),
        "hook_path": str(hook_path),
        "is_global": is_global,
    }


def uninstall_git_hooks(
    target_dir: str | Path | None = None,
    is_global: bool = False,
) -> dict[str, Any]:
    """Removes only the workspace-gate config keys and script; other hooks are untouched."""
    cwd = Path.home() if is_global else Path(target_dir or Path.cwd()).resolve()
    hook_path = global_hook_path() if is_global else local_hook_path(cwd)
    for script in (hook_path, *(hook_path.parent / event for event in COMPANION_HOOKS)):
        if script.exists():
            script.unlink()
    for name in (HOOK_NAME, *COMPANION_HOOKS.values()):
        _git_config(["--remove-section", f"hook.{name}"], cwd, is_global)
    scope = "Global" if is_global else "Local"
    return {
        "success": True,
        "message": f"{scope} hook.{HOOK_NAME} removed.",
        "is_global": is_global,
    }


def _scope_status(cwd: Path, is_global: bool, hook_path: Path) -> dict[str, Any]:
    scope = ["--global"] if is_global else ["--local"]
    _, command, _ = run_command_safe(
        ["git", "config", *scope, "--get", f"hook.{HOOK_NAME}.command"],
        cwd=cwd,
        isolated_git=not is_global,
    )
    _, events, _ = run_command_safe(
        ["git", "config", *scope, "--get-all", f"hook.{HOOK_NAME}.event"],
        cwd=cwd,
        isolated_git=not is_global,
    )
    configured = command.strip()
    executable = hook_path.exists() and os.access(hook_path, os.X_OK)
    return {
        "hook_exists": hook_path.exists(),
        "is_executable": executable,
        "hook_path": str(hook_path),
        "configured_command": configured,
        "is_active": executable and configured == str(hook_path) and HOOK_EVENT in events.split(),
    }


def get_hooks_status(
    target_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Diagnoses the local and global workspace-gate registration."""
    root = Path(target_dir).resolve() if target_dir else Path.cwd().resolve()
    _, local_hooks_path, _ = run_command_safe(
        ["git", "config", "--local", "--get", "core.hooksPath"], cwd=root, isolated_git=True
    )
    return {
        "local": _scope_status(root, False, local_hook_path(root)),
        "global": _scope_status(Path.home(), True, global_hook_path()),
        "repository_hooks_path": local_hooks_path.strip(),
    }


def run_quality_gate(
    target_dir: str | Path | None = None,
    scope: str = "all",
    skip: str | None = None,
    timeout: int = 900,
    commit_style: str | None = None,
    output: str = "errors",
    capture: list[str] | None = None,
) -> int:
    """
    Runs the Git Hooks Quality Gate on demand in the given repository.
    Returns the pre-push script's exit code. When ``capture`` is a list, the
    combined output is appended to it instead of being streamed.
    """
    root = Path(target_dir).resolve() if target_dir else Path.cwd().resolve()
    local_hook = local_hook_path(root)
    global_hook = global_hook_path()

    hook_to_run = None
    if local_hook.is_file() and os.access(local_hook, os.X_OK):
        hook_to_run = local_hook
    elif global_hook.is_file() and os.access(global_hook, os.X_OK):
        hook_to_run = global_hook

    # If no hook is installed, temporarily write the canonical one
    temp_hook = None
    if not hook_to_run:
        script = generate_canonical_pre_push_script()
        temp_dir = Path(tempfile.mkdtemp(prefix="ws_qg_"))
        temp_hook = temp_dir / "pre-push"
        temp_hook.write_text(script, encoding="utf-8")
        temp_hook.chmod(temp_hook.stat().st_mode | stat.S_IXUSR)
        hook_to_run = temp_hook

    # Get the current commit for stdin
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
            capture_output=capture is not None,
            errors="replace",
        )
        if capture is not None:
            capture.append(proc.stdout + proc.stderr)
        return proc.returncode
    finally:
        if temp_hook and temp_hook.exists():
            shutil.rmtree(temp_hook.parent, ignore_errors=True)
