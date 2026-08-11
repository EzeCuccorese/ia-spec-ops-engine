"""
Unit tests for devscripts.adapters.bridge — Multi-AI Native Adapter Generator.
"""

import json
import tempfile
from pathlib import Path
import pytest

from devscripts.adapters.bridge import generate_adapters, get_sdd_core_rules


def test_get_sdd_core_rules():
    rules = get_sdd_core_rules()
    assert "Spec-Driven Development" in rules
    assert "Conventional Commits" in rules
    assert "ZERO AI MENTIONS" in rules
    assert "Protocolo Híbrido" in rules


def test_generate_all_adapters():
    with tempfile.TemporaryDirectory() as tmp_dir:
        files = generate_adapters(target_dir=tmp_dir, gen_all=True)
        td = Path(tmp_dir)

        # 1. Claude Code
        assert "CLAUDE.md" in files
        assert ".claude/settings.json" in files
        assert ".claude/agents/worker.json" in files
        assert ".claude/agents/qa-reviewer.json" in files

        settings_path = td / ".claude" / "settings.json"
        assert settings_path.exists()
        with open(settings_path, encoding="utf-8") as f:
            settings = json.load(f)
        assert "PreToolUse" in settings["hooks"]
        assert "PostToolUse" in settings["hooks"]
        assert "sdd hook pre-tool" in settings["hooks"]["PreToolUse"][0]["command"]

        worker_path = td / ".claude" / "agents" / "worker.json"
        assert worker_path.exists()
        with open(worker_path, encoding="utf-8") as f:
            worker = json.load(f)
        assert worker["name"] == "worker"

        qa_path = td / ".claude" / "agents" / "qa-reviewer.json"
        assert qa_path.exists()
        with open(qa_path, encoding="utf-8") as f:
            qa = json.load(f)
        assert qa["name"] == "qa-reviewer"

        # 2. Antigravity 2.0
        assert "AGENTS.md" in files
        assert ".agents/rules/sdd-rules.md" in files
        assert ".agents/skills/sdd-init/SKILL.md" in files
        assert ".agents/skills/sdd-verify/SKILL.md" in files
        assert ".agents/skills/sdd-harness/SKILL.md" in files

        init_skill = (td / ".agents" / "skills" / "sdd-init" / "SKILL.md").read_text(encoding="utf-8")
        assert "name: sdd-init" in init_skill
        assert "Protocolo Híbrido" in init_skill
        assert "Paso 1: Ejecución Determinística CLI" in init_skill
        assert "Paso 2: Auditoría & Validación Dinámica del Repositorio por IA" in init_skill

        verify_skill = (td / ".agents" / "skills" / "sdd-verify" / "SKILL.md").read_text(encoding="utf-8")
        assert "name: sdd-verify" in verify_skill
        assert "Protocolo Híbrido" in verify_skill

        harness_skill = (td / ".agents" / "skills" / "sdd-harness" / "SKILL.md").read_text(encoding="utf-8")
        assert "name: sdd-harness" in harness_skill
        assert "Protocolo Híbrido" in harness_skill

        # 3. GitHub Copilot
        assert ".github/copilot-instructions.md" in files
        assert ".github/hooks/pre-tool.json" in files
        assert ".github/hooks/post-tool.json" in files

        pre_hook = json.loads((td / ".github" / "hooks" / "pre-tool.json").read_text(encoding="utf-8"))
        assert pre_hook["type"] == "pre-tool"
        assert "sdd hook pre-tool" in pre_hook["command"]

        post_hook = json.loads((td / ".github" / "hooks" / "post-tool.json").read_text(encoding="utf-8"))
        assert post_hook["type"] == "post-tool"

        # 4. Cursor IDE
        assert ".cursorrules" in files
        assert ".cursor/rules/sdd-harness.mdc" in files
        assert ".cursor/hooks.json" in files

        mdc_content = (td / ".cursor" / "rules" / "sdd-harness.mdc").read_text(encoding="utf-8")
        assert mdc_content.startswith("---")
        assert "alwaysApply: true" in mdc_content

        cursor_hooks = json.loads((td / ".cursor" / "hooks.json").read_text(encoding="utf-8"))
        assert "pre-tool" in cursor_hooks["hooks"]

        # 5. Windsurf
        assert ".windsurfrules" in files
        windsurf_content = (td / ".windsurfrules").read_text(encoding="utf-8")
        assert "Windsurf Cascade Rules" in windsurf_content


def test_generate_individual_adapters():
    with tempfile.TemporaryDirectory() as tmp_dir:
        td = Path(tmp_dir)
        files = generate_adapters(target_dir=tmp_dir, claude=True)
        assert ".claude/settings.json" in files
        assert ".windsurfrules" not in files
        assert (td / ".claude" / "settings.json").exists()
        assert not (td / ".windsurfrules").exists()

    with tempfile.TemporaryDirectory() as tmp_dir:
        td = Path(tmp_dir)
        files = generate_adapters(target_dir=tmp_dir, windsurf=True)
        assert ".windsurfrules" in files
        assert ".claude/settings.json" not in files
        assert (td / ".windsurfrules").exists()


def test_generate_adapters_from_agents_json():
    with tempfile.TemporaryDirectory() as tmp_dir:
        td = Path(tmp_dir)
        spec_dir = td / ".specify"
        spec_dir.mkdir()
        (spec_dir / "agents.json").write_text('{"selected_agents": ["claude", "gemini"]}')

        files = generate_adapters(target_dir=tmp_dir)  # No explicit flags
        assert "CLAUDE.md" in files
        assert ".gemini/GEMINI.md" in files
        assert ".windsurfrules" not in files


def test_generate_adapters_saves_agents_json():
    with tempfile.TemporaryDirectory() as tmp_dir:
        td = Path(tmp_dir)
        files = generate_adapters(target_dir=tmp_dir, agy=True, claude=True)
        assert "AGENTS.md" in files
        assert "CLAUDE.md" in files

        aj_file = td / ".specify" / "agents.json"
        assert aj_file.exists()
        agents = json.loads(aj_file.read_text(encoding="utf-8"))["selected_agents"]
        assert "agy" in agents
        assert "claude" in agents
        assert "copilot" not in agents


def test_prompt_select_agents(monkeypatch):
    from devscripts.adapters.bridge import prompt_select_agents
    monkeypatch.setattr("builtins.input", lambda _: "1, 2")
    selected = prompt_select_agents()
    assert selected == ["agy", "claude"]


def test_generate_adapters_cleans_unselected_agents():
    with tempfile.TemporaryDirectory() as tmp_dir:
        td = Path(tmp_dir)
        # First generate all
        generate_adapters(target_dir=tmp_dir, gen_all=True)
        assert (td / "CLAUDE.md").exists()
        assert (td / "AGENTS.md").exists()
        assert (td / ".gemini/GEMINI.md").exists()

        # Now re-generate with ONLY gemini
        files = generate_adapters(target_dir=tmp_dir, gemini=True)
        assert ".gemini/GEMINI.md" in files
        assert (td / ".gemini/GEMINI.md").exists()

        # Check that unselected adapters were cleaned up!
        assert not (td / "CLAUDE.md").exists()
        assert not (td / ".claude").exists()
        assert not (td / "AGENTS.md").exists()
        assert not (td / ".agents").exists()
        assert not (td / ".cursorrules").exists()


def test_detect_existing_agents():
    from devscripts.adapters.bridge import detect_existing_agents
    with tempfile.TemporaryDirectory() as tmp_dir:
        td = Path(tmp_dir)
        # Empty repo defaults to agy
        assert detect_existing_agents(target_dir=tmp_dir) == ["agy"]

        # Creating CLAUDE.md detects claude
        (td / "CLAUDE.md").write_text("# Claude Code")
        assert set(detect_existing_agents(target_dir=tmp_dir)) == {"claude"}


def test_non_interactive_adapter_generation_defaults_to_detected_agents():
    with tempfile.TemporaryDirectory() as tmp_dir:
        td = Path(tmp_dir)
        # Non-interactive generation without flags or agents.json should NOT generate all 7 agents
        files = generate_adapters(target_dir=tmp_dir)
        assert "AGENTS.md" in files
        assert "CLAUDE.md" not in files
        assert ".windsurfrules" not in files
        assert "CHATGPT.md" not in files



