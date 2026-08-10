"""
Integration tests for project detector and technology classification.
"""

from pathlib import Path
from devscripts.core.detector import detect_project_type, ProjectType

def test_detect_spring_boot_gradle(tmp_path: Path):
    (tmp_path / "build.gradle").write_text("// gradle build")
    (tmp_path / "src" / "main" / "resources").mkdir(parents=True)
    (tmp_path / "src" / "main" / "resources" / "application.yml").write_text("server:\n  port: 8080\n")

    p_type = detect_project_type(tmp_path)
    assert p_type == ProjectType.SPRING_BOOT

def test_detect_go_project(tmp_path: Path):
    (tmp_path / "go.mod").write_text("module example.com/service\n")

    p_type = detect_project_type(tmp_path)
    assert p_type == ProjectType.GO
