#!/usr/bin/env python3
"""
workspace_engine.cli.clean_workspace — Limpieza determinista de artefactos de build y caches en el workspace.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path
from typing import Optional

from workspace_engine.utils import find_project_root, log_info, log_success


def clean_workspace(start_dir: Optional[Path] = None) -> int:
    """Limpia caches de build y temporales en repositories/ y .ai-toolkit/."""
    workspace_dir = find_project_root(start_dir)
    log_info(f"[clean-workspace] {workspace_dir}")

    ai_dir = workspace_dir / ".ai-toolkit"
    if ai_dir.is_dir():
        for entry in ai_dir.iterdir():
            if entry.name == "workspace.json":
                continue
            log_info(f"  eliminando: {entry}")
            if entry.is_dir() and not entry.is_symlink():
                shutil.rmtree(entry, ignore_errors=True)
            else:
                entry.unlink(missing_ok=True)

    repos_dir = workspace_dir / "repositories"
    if repos_dir.is_dir():
        for repo in repos_dir.iterdir():
            if not repo.is_dir():
                continue
            for cache_folder in ("node_modules", ".gradle", "build", "dist", "target"):
                cache_dir = repo / cache_folder
                if cache_dir.exists():
                    log_info(f"  eliminando: {cache_dir}")
                    if cache_dir.is_dir() and not cache_dir.is_symlink():
                        shutil.rmtree(cache_dir, ignore_errors=True)
                    else:
                        cache_dir.unlink(missing_ok=True)

    log_success("[clean-workspace] Limpieza completada.")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Limpia artefactos de compilación y caches en el workspace.")
    parser.parse_args()
    sys.exit(clean_workspace())


if __name__ == "__main__":
    main()
