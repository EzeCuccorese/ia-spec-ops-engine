"""
Unit tests for sdd_engine.global_skills — Global AI Agent Skills Manager.
"""

import tempfile
from pathlib import Path
import pytest

from sdd_engine.adapters.global_skills import (
    get_canonical_skills_dir,
    get_global_agent_skill_dirs,
    install_global_skills,
)


def test_get_canonical_skills_dir():
    skills_dir = get_canonical_skills_dir()
    assert skills_dir.exists()
    assert (skills_dir / "sdd-init" / "SKILL.md").exists()
    assert (skills_dir / "sdd-verify" / "SKILL.md").exists()

    skill_folders = [d for d in skills_dir.iterdir() if d.is_dir() and (d / "SKILL.md").exists()]
    assert len(skill_folders) == 14


    for folder in skill_folders:
        content = (folder / "SKILL.md").read_text(encoding="utf-8")
        assert f"name: {folder.name}" in content, f"Skill {folder.name} missing frontmatter name"
        assert "Execution Steps" in content or "Deterministic" in content or "SDD" in content, f"Skill {folder.name} missing execution steps"


def test_install_global_skills_custom_source():
    with tempfile.TemporaryDirectory() as tmp_src, tempfile.TemporaryDirectory() as tmp_home:
        src_path = Path(tmp_src)
        skill1 = src_path / "sdd-init"
        skill1.mkdir()
        (skill1 / "SKILL.md").write_text("---\nname: sdd-init\n---\n# Test Init")

        # Mock global targets
        gemini_target = Path(tmp_home) / ".gemini" / "config" / "skills"
        agy_target = Path(tmp_home) / ".agents" / "skills"

        monkeypatch_targets = {
            "gemini": gemini_target,
            "agy": agy_target,
        }

        # Override get_global_agent_skill_dirs for test
        import sdd_engine.adapters.global_skills as gs
        orig_func = gs.get_global_agent_skill_dirs
        gs.get_global_agent_skill_dirs = lambda: monkeypatch_targets

        try:
            summary = install_global_skills(skills_source=src_path)
            assert "gemini" in summary
            assert "sdd-init" in summary["gemini"]
            assert (gemini_target / "sdd-init" / "SKILL.md").exists()
            assert (agy_target / "sdd-init" / "SKILL.md").exists()
            content = (gemini_target / "sdd-init" / "SKILL.md").read_text()
            assert "# Test Init" in content
        finally:
            gs.get_global_agent_skill_dirs = orig_func
