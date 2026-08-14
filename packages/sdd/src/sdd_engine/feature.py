"""
sdd_engine.feature — Gestión del ciclo de vida y estado de features activas en SDD.
"""
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from sdd_engine.utils import find_project_root as get_repo_root, run_command_safe
from sdd_engine.exceptions import FeatureNotFoundError


def get_feature_file() -> Path:
    return get_repo_root() / ".specify" / "feature.json"


def set_feature(
    name: str,
    from_branch: Optional[str] = None,
    force_worktree: bool = False,
    no_worktree: bool = False,
) -> None:
    if not name or not name.strip():
        raise FeatureNotFoundError("El nombre de la feature no puede estar vacío. Uso: sdd feature set <feature-name>")
    name = name.strip()
    repo_root = get_repo_root()

    # Aislamiento automático en Git Worktree para ramas protegidas
    if not no_worktree:
        try:
            from workspace_engine.cli.create_worktree import create_worktree
        except ImportError:
            create_worktree = None

        res_b, cur_b, _ = run_command_safe(["git", "-C", str(repo_root), "branch", "--show-current"])
        cur_b = cur_b.strip()
        if force_worktree or (res_b == 0 and cur_b in ("main", "master", "develop", "staging")) or from_branch:
            branch_name = f"feature/{name}"
            base_str = f" desde '{from_branch}'" if from_branch else f" desde '{cur_b}'"
            print(f"🌿 Aislando en Git Worktree para '{branch_name}'{base_str}...")
            if create_worktree:
                create_worktree(branch_name, from_branch=from_branch, start_dir=repo_root)
            else:
                subprocess.run(["git", "-C", str(repo_root), "checkout", "-b", branch_name])


    ff = get_feature_file()
    ff.parent.mkdir(parents=True, exist_ok=True)
    created_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    data: Dict[str, str] = {
        "active_feature": name,
        "current_phase": "specify",
        "created_at": created_at,
        "updated_at": created_at,
    }
    with open(ff, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    print(f"🟢 Active feature set to: {name} (Phase: specify)")


def get_feature() -> str:
    ff = get_feature_file()
    if not ff.exists():
        raise FeatureNotFoundError("No active feature set.")
    with open(ff, encoding="utf-8") as f:
        feat = json.load(f).get("active_feature", "")
        print(feat)
        return str(feat)


def get_active_feature(repo_root: Optional[Union[Path, str]] = None) -> Optional[str]:
    root = Path(repo_root) if repo_root else get_repo_root()
    ff = root / ".specify" / "feature.json"
    if ff.exists():
        try:
            with open(ff, encoding="utf-8") as f:
                val = json.load(f).get("active_feature")
                return str(val) if val is not None else None
        except (OSError, ValueError, json.JSONDecodeError):
            return None
    return None


def update_phase(phase: str) -> None:
    ff = get_feature_file()
    if not ff.exists():
        raise FeatureNotFoundError("No active feature set. Run 'sdd feature set <name>' first.")
    with open(ff, encoding="utf-8") as f:
        data = json.load(f)
    data["current_phase"] = phase
    data["updated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with open(ff, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    print(f"🔄 Phase updated to: {phase}")


def status() -> None:
    ff = get_feature_file()
    if not ff.exists():
        print("ℹ️ No active feature. Use 'sdd feature set <feature-name>' to start one.")
        return
    with open(ff, encoding="utf-8") as f:
        data = json.load(f)
    name = data.get("active_feature", "")
    phase = data.get("current_phase", "")
    print("========================================================")
    print(f" 📌 Active Feature: {name}")
    print(f" 🔄 Current Phase: {phase}")
    print("========================================================")
    print(" SDD Artifacts:")
    feat_dir = get_repo_root() / ".specify" / "specs" / name
    for art in ["spec.md", "clarify.md", "plan.md", "checklist.md", "tasks.md"]:
        chk = "[✓]" if (feat_dir / art).exists() else "[ ]"
        print(f"   {chk} {art}")
    print("========================================================")


def reset(repo_root: Optional[Union[Path, str]] = None) -> None:
    root = Path(repo_root) if repo_root else get_repo_root()
    ff = root / ".specify" / "feature.json"
    if ff.exists():
        ff.unlink()
    print("🧹 Active feature state reset.")


def list_features(repo_root: Optional[Union[Path, str]] = None) -> List[Dict[str, Any]]:
    root = Path(repo_root) if repo_root else get_repo_root()
    active = get_active_feature(root)
    specs_dir = root / ".specify" / "specs"

    features_list: List[Dict[str, Any]] = []
    if not specs_dir.exists():
        print("ℹ️ No hay especificaciones de características encontradas en .specify/specs/")
        return features_list

    for feat_folder in sorted(specs_dir.iterdir()):
        if not feat_folder.is_dir():
            continue
        fname = feat_folder.name
        artifacts: Dict[str, bool] = {}
        for art in ["spec.md", "clarify.md", "plan.md", "checklist.md", "tasks.md"]:
            artifacts[art] = (feat_folder / art).exists()

        # Infer phase
        inferred_phase = "specify"
        if artifacts.get("tasks.md"):
            inferred_phase = "tasks"
        elif artifacts.get("checklist.md"):
            inferred_phase = "checklist"
        elif artifacts.get("plan.md"):
            inferred_phase = "plan"
        elif artifacts.get("clarify.md"):
            inferred_phase = "clarify"
        elif artifacts.get("spec.md"):
            inferred_phase = "specify"

        is_active = fname == active
        features_list.append({
            "name": fname,
            "phase": inferred_phase,
            "artifacts": artifacts,
            "is_active": is_active,
        })

    print("==========================================================================")
    print(" 📋 Catálogo de Características SDD en el Repositorio (.specify/specs/)")
    print("==========================================================================")
    if not features_list:
        print(" (No existen características aún)")
    else:
        for item in features_list:
            star = " 🟢 [ACTIVA]" if item["is_active"] else "   "
            art_str = " ".join([f"{a.split('.')[0]}:{'✓' if v else '✗'}" for a, v in item["artifacts"].items()])
            print(f"{star} {item['name']:<30} | Fase: {item['phase']:<10} | Artefactos: {art_str}")
    print("==========================================================================")
    return features_list
