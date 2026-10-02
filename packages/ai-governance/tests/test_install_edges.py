"""Edge cases of the ledger engine, doctor, budget, probe and hooks."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from ai_governance import hooks
from ai_governance.install import installer, probe
from ai_governance.install.budget import fixed_cost
from ai_governance.install.doctor import FAIL, WARN, check
from ai_governance.install.engine import Ledger
from ai_governance.install.installer import PROJECT_DIR, install_user, sync_project


@pytest.fixture
def project(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    monkeypatch.setenv("AI_GOVERNANCE_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.delenv("CODEX_HOME", raising=False)
    monkeypatch.setattr(installer, "detect_stacks", lambda root: {"java"})
    root = tmp_path / "repo"
    root.mkdir()
    return root


def test_removal_keeps_locally_edited_files(project: Path) -> None:
    sync_project(project, add_agents=["codex"])
    rule = project / ".agents/rules/ai-governance-java-spring.md"
    rule.write_text("mine")
    report = sync_project(project, remove_agents=["codex"])
    assert rule.read_text() == "mine"
    assert any("not removed" in w for w in report.warnings)


def test_removal_tolerates_files_deleted_by_hand(project: Path) -> None:
    sync_project(project, add_agents=["codex"])
    (project / ".agents/rules/ai-governance-java-spring.md").unlink()
    (project / "AGENTS.md").unlink()
    sync_project(project, remove_agents=["codex"])
    assert not (project / ".agents").exists()


def test_doctor_reports_missing_edited_and_legacy(project: Path) -> None:
    sync_project(project, add_agents=["claude", "antigravity"])
    (project / ".agents/rules/ai-governance-java-spring.md").unlink()
    (project / ".agents/rules/ai-governance-06-security-privacy.md").write_text("x")
    (project / ".agent").mkdir()
    rows = check(project)
    assert any(s == FAIL and "missing" in d for _, s, d in rows)
    assert any(s == WARN and "edited locally" in d for _, s, d in rows)
    assert any("legacy .agent/" in d for _, _, d in rows)
    assert any(c == "project:drift" and s == WARN for c, s, _ in rows)


def test_budget_counts_shared_blocks_and_no_codex_project_rules(project: Path) -> None:
    install_user(["codex"])
    sync_project(project, add_agents=["codex"])
    user = fixed_cost(installer.global_ledger())
    lock = fixed_cost(Ledger(project / PROJECT_DIR / "lock.json", base=project))
    assert 0 < user["codex"] <= 1024
    assert lock.get("codex", 0) == 0 and lock["project"] > 0


def test_probe_record_tolerates_bad_payloads(monkeypatch, project: Path) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO("not json"))
    assert probe.record("codex", "Stop") == 0
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"tool_response": "text"})))
    assert probe.record("codex", "PostToolUse") == 0
    shape = json.loads((probe.records_dir("codex") / "PostToolUse.json").read_text())
    assert shape["tool_response"] == "str" and shape["has_command"] is False


def test_stop_gate_ignores_unparseable_ws_output(monkeypatch) -> None:
    class Proc:
        stdout, returncode = "garbage", 0

    monkeypatch.setattr(hooks.shutil, "which", lambda name: "/bin/ws")
    monkeypatch.setattr(hooks.subprocess, "run", lambda *a, **k: Proc())
    monkeypatch.setattr("sys.stdin", io.StringIO("[]"))
    assert hooks.main(["claude", "stop-gate"]) == 0


def test_session_end_without_task_is_noop(monkeypatch, project: Path) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"cwd": str(project)})))
    assert hooks.main(["claude", "session-end"]) == 0


def test_claude_hook_handlers_delegate(monkeypatch) -> None:
    from ai_governance.frugality import cli as frugal
    from ai_governance.telemetry import cli as telemetry

    calls: list[str] = []
    monkeypatch.setattr(frugal, "run_pre_bash", lambda cfg: calls.append("pre"))
    monkeypatch.setattr(frugal, "run_post_bash", lambda cfg: calls.append("post"))
    monkeypatch.setattr(telemetry, "main", lambda argv: calls.append(" ".join(argv)) or 0)
    for event in ("pre-tool-use", "post-tool-use", "stop"):
        assert hooks.main(["claude", event]) == 0
    assert calls == ["pre", "post", "thresholds --notify"]


def test_codex_config_block_is_prepended_and_reversible(project: Path, tmp_path: Path) -> None:
    config = tmp_path / "home/.codex/config.toml"
    config.parent.mkdir(parents=True)
    config.write_text('model = "x"\n\n[mcp_servers.a]\ncommand = "a"\n')
    install_user(["codex"])
    text = config.read_text()
    assert text.startswith('# ai-governance:start\nagents.default_subagent_model = "terra"')
    assert text.index("ai-governance:end") < text.index("[mcp_servers.a]")
    import tomllib

    assert tomllib.loads(text)["agents"]["default_subagent_model"] == "terra"
    installer.uninstall_user(["codex"])
    assert config.read_text() == 'model = "x"\n\n[mcp_servers.a]\ncommand = "a"\n'


def test_codex_config_block_skipped_when_user_defines_agents(project: Path, tmp_path: Path) -> None:
    config = tmp_path / "home/.codex/config.toml"
    config.parent.mkdir(parents=True)
    config.write_text('[agents]\ndefault_subagent_model = "mine"\n')
    report = install_user(["codex"])
    assert "ai-governance" not in config.read_text()
    assert any("already defines" in w for w in report.warnings)


def test_doctor_warns_on_unread_antigravity_settings(project: Path) -> None:
    sync_project(project, add_agents=["antigravity"])
    (project / ".agents" / "settings.json").write_text("{}")
    details = [d for _, _, d in check(project)]
    assert any(".gemini/config.json" in d for d in details)


def test_doctor_warns_on_leftover_gemini_md_block(project: Path) -> None:
    home = project.parent / "home"
    install_user(["antigravity"])
    legacy = home / ".gemini" / "GEMINI.md"
    legacy.write_text("<!-- ai-governance:start -->\nold\n<!-- ai-governance:end -->\n")
    rows = [r for r in check(None) if r[0] == "user:antigravity"]
    assert rows and rows[0][1] == WARN and "delete it" in rows[0][2]


def test_antigravity_rules_stay_within_its_rules_budget(project: Path, monkeypatch) -> None:
    every_stack = {
        "java",
        "kotlin",
        "node",
        "typescript",
        "react",
        "python",
        "go",
        "rust",
        "php",
        "flutter",
        "dotnet",
        "docker",
        "kubernetes",
        "sql",
        "migrations",
        "github-actions",
    }
    monkeypatch.setattr(installer, "detect_stacks", lambda root: every_stack)
    sync_project(project, add_agents=["antigravity"])
    total = sum(len(p.read_bytes()) for p in (project / ".agents/rules").glob("*.md"))
    assert total // 4 < 20_000  # Antigravity 2.17: dedicated 20k-token rules budget


def test_probe_scout_and_frontmatter_hooks(monkeypatch, project: Path, tmp_path: Path) -> None:
    root = probe.build("antigravity", tmp_path / "p")
    scout = (root / ".agents/agents/probe-scout.md").read_text()
    assert "hooks:\n  - probe-scout-hooks.json" in scout and "CANARY-SCOUT" in scout
    assert (root / ".agents/agents/probe-scout-hooks.json").exists()
    monkeypatch.setattr("sys.stdin", io.StringIO("{}"))
    probe.record("antigravity", "agent-PreToolUse")
    result = probe.verify("antigravity", ["CANARY-SCOUT"])
    assert result["scout_verified"] is True
    assert result["agent_frontmatter_hooks_fired"] == ["PreToolUse"]
    for agent, path in (
        ("claude", ".claude/agents/probe-scout.md"),
        ("codex", ".codex/agents/probe-scout.toml"),
    ):
        assert "CANARY-SCOUT" in (probe.build(agent, tmp_path / agent) / path).read_text()
