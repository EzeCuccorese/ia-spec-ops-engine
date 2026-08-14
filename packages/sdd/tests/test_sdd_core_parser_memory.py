"""
Tests unitarios para sdd_engine.core.parser y memory.
"""

import tempfile
from pathlib import Path

import pytest
from sdd_engine.core.parser import parse
from sdd_engine.core import memory


def test_parse_spec_markdown():
    markdown = "Feature: Authentication Flow with JWT tokens"
    spec = parse(markdown)
    assert spec is not None
    assert "Specification Request" in spec or "Authentication" in spec


def test_memory_init_and_log():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        # Inicializar git o pyproject para que find_project_root lo reconozca
        (root / ".git").mkdir()
        memory.init(root)
        
        mem_file = root / ".specify" / "memory.md"
        assert mem_file.exists()
        
        # Log event
        event_path = memory.log_task_event(
            task_id="T01",
            role="worker",
            title="Implement login logic",
            details="Created auth controller and tests",
            status="SUCCESS",
            target_dir=root,
        )
        assert event_path.exists()
        assert "Implement login logic" in event_path.read_text()
