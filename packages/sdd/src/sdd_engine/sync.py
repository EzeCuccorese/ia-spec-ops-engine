"""
devscripts.sdd.sync — Unified global CLI reinstallation and project AI adapter synchronization.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import List, Optional, Tuple, Union

from sdd_engine import bridge
from sdd_engine.utils import find_project_root, run_command_safe
import subprocess
from sdd_engine import memory, global_skills



def get_active_repo_worktrees(target_dir: Union[str, Path] = ".") -> List[Path]:
    """
    Returns absolute Path objects for all active git worktree directories in the repository,
    excluding the primary/current worktree itself.
    """
    td = Path(target_dir).resolve()
    try:
        res = subprocess.run(
            ["git", "-C", str(td), "worktree", "list", "--porcelain"],
            capture_output=True,
            text=True,
            check=True,
        )
        lines = res.stdout.splitlines()
        worktrees: List[Path] = []
        for line in lines:
            if line.startswith("worktree "):
                wt_path = Path(line.split("worktree ", 1)[1]).resolve()
                if wt_path != td and wt_path.exists():
                    worktrees.append(wt_path)
        return worktrees
    except Exception:
        return []


def sync_sdd(
    target_dir: Union[str, Path] = ".",
    quiet: bool = False,
    interactive: bool = False,
) -> Tuple[bool, List[str]]:
    """
    Synchronizes SDD globally and locally:
    1. Re-installs devscripts editable package globally via `pip install -e`.
    2. Synchronizes global skills in ~/.gemini/config/skills and ~/.agents/skills.
    3. Synchronizes active Multi-AI adapters in target_dir and active worktrees.

    Returns:
        Tuple[bool, List[str]]: (success, list_of_synced_files)
    """
    td = Path(target_dir).resolve()

    if not quiet:
        print("=== SDD Sync Orchestrator ===")
        print(f"Target Directory: {td}")

    # 1. Global PIP Editable Sync
    devscripts_root = find_project_root(Path(__file__).parent)
    if not quiet:
        print(f"==> Step 1: Re-installing global SDD CLI package from {devscripts_root}...")

    retcode, stdout, stderr = run_command_safe(
        [sys.executable, "-m", "pip", "install", "-e", str(devscripts_root)],
        cwd=devscripts_root,
    )

    if retcode != 0:
        if not quiet:
            print(f"⚠️ Warning: pip install -e return code {retcode}: {stderr[:200]}")

    if not quiet:
        print("    ✅ Global CLI `sdd` updated.")

    # 2. Global Skills Sync
    if not quiet:
        print("==> Step 2: Synchronizing global AI skills (~/.gemini/config/skills, ~/.agents/skills)...")
    global_skills.install_global_skills()

    # 3. Project AI Adapter Sync & Active Worktrees
    if not quiet:
        print(f"==> Step 3: Synchronizing Multi-AI adapters in {td}...")

    specify_dir = td / ".specify"
    synced_files: List[str] = []

    if not specify_dir.exists():
        do_init = False
        is_tty = sys.stdin and hasattr(sys.stdin, "isatty") and sys.stdin.isatty()
        if not quiet and (interactive or is_tty):
            try:
                ans = input("ℹ️ El proyecto actual no está inicializado con SDD. ¿Deseas inicializarlo ahora (sdd init)? [y/N]: ").strip().lower()
                if ans == "y":
                    do_init = True
            except KeyboardInterrupt:
                print("\n\n🚫 Operación cancelada por el usuario.")
                sys.exit(130)
            except EOFError:
                do_init = False

        if do_init:
            memory.init(td)
            synced_files = bridge.generate_adapters(target_dir=td, interactive=True)
            if not quiet:
                print(f"✅ SDD Sync & Init Completado. Sincronizados {len(synced_files)} adaptadores.")
        else:
            if not quiet:
                print("ℹ️ Inicialización de proyecto omitida. Sincronización global completada exitosamente.")
    else:
        memory.init(td)
        synced_files = bridge.generate_adapters(target_dir=td)

        # Sync active worktrees
        active_wts = get_active_repo_worktrees(td)
        if active_wts:
            if not quiet:
                print(f"🔄 Se detectaron {len(active_wts)} worktree(s) activo(s). Sincronizando SDD en worktrees...")
            for wt in active_wts:
                memory.init(wt)
                wt_files = bridge.generate_adapters(target_dir=wt)
                synced_files.extend([f"{wt.name}/{f}" for f in wt_files])
                if not quiet:
                    print(f"  ✅ Worktree {wt.name}: {len(wt_files)} adaptadores sincronizados.")

        if not quiet:
            print(f"✅ SDD Sync Completado. Sincronizados {len(synced_files)} adaptadores.")

    return True, synced_files
