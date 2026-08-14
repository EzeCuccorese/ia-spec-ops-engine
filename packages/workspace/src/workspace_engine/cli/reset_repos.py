#!/usr/bin/env python3
"""
workspace_engine.cli.reset_repos — Reseteo determinista de repositorios Git al commit base o HEAD limpio.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import List, Optional, Tuple

from workspace_engine.utils import Color, find_project_root, log_error, log_info, log_success, log_warning


def _git(repo_path: Path, *args) -> subprocess.CompletedProcess:
    return subprocess.run(
        ['git', '-C', str(repo_path)] + list(args),
        capture_output=True, text=True,
    )


def _parent_branch(workspace_dir: Path, repo_name: str) -> Optional[str]:
    manifest = workspace_dir / ".ai-toolkit" / "workspace.json"
    if not manifest.is_file():
        return None
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
        for r in data.get("repositories", []):
            if r.get("name") == repo_name:
                return r.get("parent_branch")
    except Exception:
        pass
    return None


def _branch_point(repo_path: Path, parent: Optional[str]) -> Optional[str]:
    if not parent:
        return None
    remote_check = _git(repo_path, "rev-parse", "--verify", "--quiet", f"origin/{parent}")
    if remote_check.returncode == 0:
        base = f"origin/{parent}"
    else:
        local_check = _git(repo_path, "rev-parse", "--verify", "--quiet", parent)
        if local_check.returncode == 0:
            base = parent
        else:
            return None
    res = _git(repo_path, "merge-base", "HEAD", base)
    if res.returncode == 0 and res.stdout.strip():
        return res.stdout.strip()
    return None


def reset_repositories(
    force: bool = False,
    dry_run: bool = False,
    repo_filter: Optional[List[str]] = None,
    start_dir: Optional[Path] = None,
) -> int:
    workspace_dir = find_project_root(start_dir)
    repos_dir = workspace_dir / "repositories"
    if not repos_dir.is_dir():
        log_error(f"No se encontró directorio repositories/ en {workspace_dir}")
        return 1

    repos: List[Path] = []
    if repo_filter:
        for name in repo_filter:
            p = repos_dir / name
            if not p.is_dir() or not ((p / ".git").exists() or (p / ".git").is_file()):
                log_error(f"No es un repositorio git: {name}")
                return 1
            repos.append(p)
    else:
        for p in sorted(repos_dir.iterdir()):
            if p.is_dir() and ((p / ".git").exists() or (p / ".git").is_file()):
                repos.append(p)

    if not repos:
        log_warning(f"No se encontraron repositorios git en {repos_dir}")
        return 0

    print(f"\n{Color.BOLD}Workspace:{Color.RESET} {workspace_dir}")
    if dry_run:
        print(f"{Color.YELLOW}[MODO SIMULACIÓN — no se realizarán cambios]{Color.RESET}")
    print("")

    dirty_repos: List[Tuple[Path, Optional[str]]] = []
    for r in repos:
        repo_name = r.name
        branch_res = _git(r, "branch", "--show-current")
        branch = branch_res.stdout.strip() or "(detached)"
        parent = _parent_branch(workspace_dir, repo_name)
        b_point = _branch_point(r, parent)

        local_commits = []
        if b_point:
            log_res = _git(r, "log", "--oneline", f"{b_point}..HEAD")
            if log_res.returncode == 0 and log_res.stdout.strip():
                local_commits = log_res.stdout.strip().splitlines()

        status_res = _git(r, "status", "--porcelain")
        dirty = [l for l in status_res.stdout.splitlines() if l.strip()]
        tracked_dirty = [l for l in dirty if not l.startswith("??")]
        untracked = [l for l in dirty if l.startswith("??")]

        has_changes = bool(local_commits or tracked_dirty)
        print(f"{Color.BOLD}{repo_name}{Color.RESET} {Color.DIM}({branch}){Color.RESET}")

        if not has_changes:
            print(f"  {Color.DIM}limpio — nada para resetear{Color.RESET}")
            continue

        if local_commits:
            short = b_point[:7] if b_point else ""
            print(f"  {Color.DIM}{len(local_commits)} commit(s) local(es) serán descartados (→ {short}):{Color.RESET}")
            for c in local_commits[:5]:
                print(f"    {Color.DIM}{c}{Color.RESET}")
        if tracked_dirty:
            print(f"  {Color.DIM}{len(tracked_dirty)} archivo(s) modificado(s) serán restaurados{Color.RESET}")
        if untracked:
            print(f"  {Color.DIM}{len(untracked)} archivo(s) sin seguimiento (se conservan){Color.RESET}")

        dirty_repos.append((r, b_point))
        print("")

    if not dirty_repos:
        log_success("Todos los repositorios están limpios.")
        return 0

    if dry_run:
        return 0

    if not force:
        print(f"{Color.RED}{Color.BOLD}Se descartarán permanentemente cambios en {len(dirty_repos)} repositorio(s).{Color.RESET}")
        resp = input(f"{Color.BOLD}¿Continuar? [y/N]: {Color.RESET}").strip().lower()
        if resp not in ("y", "yes", "s", "si"):
            log_warning("Operación cancelada.")
            return 0

    failed = False
    for r, b_point in dirty_repos:
        print(f"{Color.BOLD}[{r.name}]{Color.RESET} reseteando...")
        target_ref = b_point if b_point else "HEAD"
        res = _git(r, "reset", "--hard", target_ref)
        if res.returncode == 0:
            log_success(f"[{r.name}] reseteado correctamente.")
        else:
            log_error(f"[{r.name}] error al resetear: {res.stderr}")
            failed = True

    return 1 if failed else 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Resetea los repositorios del workspace al commit origen o HEAD limpio.")
    parser.add_argument("--force", action="store_true", help="Omitir confirmación interactiva")
    parser.add_argument("--dry-run", action="store_true", help="Simular sin modificar archivos")
    parser.add_argument("repos", nargs="*", help="Repositorios específicos a resetear")
    args = parser.parse_args()

    sys.exit(reset_repositories(force=args.force, dry_run=args.dry_run, repo_filter=args.repos))


if __name__ == "__main__":
    main()
