"""
devscripts.sdd.global_skills — Global AI Agent Skills Manager & Installer.

Installs and synchronizes canonical SDD skills from devscripts into global AI agent directories:
- ~/.gemini/config/skills/ (Google Antigravity & Gemini CLI)
- ~/.agents/skills/ (Antigravity 2.0 Global)
- ~/.claude/skills/ (Claude Code Global)
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Dict, List, Optional, Union

from sdd_engine.core.utils import log_info, log_success, log_warning


def get_canonical_skills_dir() -> Path:
    """
    Retorna la ruta absoluta al directorio canónico de skills en packages/sdd/skills/.
    """
    # Intentar desde la raíz del paquete packages/sdd/skills
    pkg_root = Path(__file__).resolve().parent.parent.parent.parent
    pkg_skills = pkg_root / "skills"
    if pkg_skills.exists() and pkg_skills.is_dir():
        return pkg_skills

    base = pkg_root.parent.parent  # devscripts root
    for candidate in [
        base / "packages" / "sdd" / "skills",
        base / ".agents" / "skills",
        Path.cwd() / "packages" / "sdd" / "skills",
    ]:
        if candidate.exists() and candidate.is_dir():
            return candidate
    return pkg_skills





def get_global_agent_skill_dirs() -> Dict[str, Path]:
    """
    Returns a dictionary of target global skill directories per AI platform.
    """
    home = Path.home()
    return {
        "gemini": home / ".gemini" / "config" / "skills",
        "agy": home / ".agents" / "skills",
        "claude": home / ".claude" / "skills",
    }


def install_global_skills(
    platforms: Optional[List[str]] = None,
    force: bool = True,
    skills_source: Optional[Union[str, Path]] = None,
) -> Dict[str, List[str]]:
    """
    Installs canonical SDD skills globally into the user's home configuration directories
    using atomic copy with overwrite.

    :param platforms: List of platforms ('gemini', 'agy', 'claude'). Default installs gemini & agy.
    :param force: If True, overwrites existing global skill files.
    :param skills_source: Custom path to skills directory if overriding default.
    :return: Dictionary mapping platform key to list of installed skill names.
    """
    if skills_source:
        src_dir = Path(skills_source).resolve()
    else:
        src_dir = get_canonical_skills_dir()

    if not src_dir.exists() or not src_dir.is_dir():
        log_warning(f"⚠️  Canonical skills directory not found at {src_dir}")
        return {}

    target_map = get_global_agent_skill_dirs()
    if not platforms:
        platforms = ["gemini", "agy"]

    installed_summary: Dict[str, List[str]] = {}

    # Discover valid skill subdirectories (directories containing SKILL.md)
    skill_folders = [
        d for d in src_dir.iterdir()
        if d.is_dir() and (d / "SKILL.md").exists()
    ]

    if not skill_folders:
        log_warning(f"⚠️  No valid skill folders found in {src_dir}")
        return {}

    log_info(f"🚀 Synchronizing {len(skill_folders)} global SDD skills into user environment...")

    for platform in platforms:
        if platform not in target_map:
            continue
        dest_base = target_map[platform]
        try:
            dest_base.mkdir(parents=True, exist_ok=True)
            platform_installed: List[str] = []

            for skill_folder in skill_folders:
                skill_name = skill_folder.name
                target_skill_dir = dest_base / skill_name

                if target_skill_dir.exists() and force:
                    shutil.rmtree(target_skill_dir, ignore_errors=True)

                target_skill_dir.mkdir(parents=True, exist_ok=True)

                # Copy all files inside skill folder atomically
                for item in skill_folder.iterdir():
                    if item.is_file():
                        shutil.copy2(item, target_skill_dir / item.name)
                    elif item.is_dir():
                        shutil.copytree(item, target_skill_dir / item.name, dirs_exist_ok=True)

                platform_installed.append(skill_name)

            installed_summary[platform] = platform_installed
            log_success(f"  ✅ Installed {len(platform_installed)} global skills -> {dest_base}")
        except (PermissionError, OSError) as e:
            log_warning(f"⚠️  Could not install skills for platform '{platform}' ({dest_base}): {e}")

    return installed_summary
