import json
import pytest
from pathlib import Path
from unittest.mock import patch
from devscripts.cli import sdd_tui

def test_agents_catalog_structure():
    assert len(sdd_tui.AGENTS_CATALOG) == 6
    agent_ids = [a["id"] for a in sdd_tui.AGENTS_CATALOG]
    assert "agy" in agent_ids
    assert "gemini" in agent_ids
    assert "claude" in agent_ids
    assert "copilot" in agent_ids
    assert "cursor" in agent_ids
    assert "chatgpt" in agent_ids

def test_components_catalog_structure():
    assert len(sdd_tui.COMPONENTS_CATALOG) == 3
    comp_ids = [c["id"] for c in sdd_tui.COMPONENTS_CATALOG]
    assert "rules" in comp_ids
    assert "skills" in comp_ids
    assert "docs" in comp_ids

def test_non_interactive_fallback():
    with patch("sys.stdin.isatty", return_value=False):
        chosen_agents, chosen_comps = sdd_tui.run_agent_selector_tui()
        assert "agy" in chosen_agents
        assert "gemini" in chosen_agents
        assert "claude" not in chosen_agents
        assert "rules" in chosen_comps
        assert "skills" in chosen_comps

def test_save_agent_preferences(tmp_path):
    sdd_tui.save_agent_preferences(tmp_path, ["gemini", "agy", "claude"], ["rules", "docs"])
    
    agents_file = tmp_path / ".specify" / "agents.json"
    assert agents_file.exists()
    
    with open(agents_file) as f:
        data = json.load(f)
        assert data["selected_agents"] == ["gemini", "agy", "claude"]
        assert data["selected_components"] == ["rules", "docs"]

def test_get_bridge_flags_for_agents():
    flags = sdd_tui.get_bridge_flags_for_agents(["gemini", "claude"])
    assert flags == ["--gemini", "--claude"]
