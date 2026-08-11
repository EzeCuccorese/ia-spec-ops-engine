"""
Unit tests for devscripts.sdd.global_skills — Global AI Agent Skills Manager.
"""

import tempfile
from pathlib import Path
import pytest

from devscripts.sdd.global_skills import (
    get_canonical_skills_dir,
    get_global_agent_skill_dirs,
    install_global_skills,
)


def test_get_canonical_skills_dir():
    skills_dir = get_canonical_skills_dir()
    assert skills_dir.exists()
    assert (skills_dir / "sdd-init" / "SKILL.md").exists()
    assert (skills_dir / "sdd-verify" / "SKILL.md").exists()


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
        import devscripts.sdd.global_skills as gs
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
