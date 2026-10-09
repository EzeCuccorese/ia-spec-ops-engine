"""Per-agent installer: scopes, isolation between agents, idempotency, reversibility."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from ai_governance.install import installer
from ai_governance.install.agents import AGENTS, capability_table
from ai_governance.install.cli import main as install_cli
from ai_governance.install.doctor import FAIL, check
from ai_governance.install.engine import Ledger
from ai_governance.install.installer import (
    ProjectConfig,
    install_user,
    registered_projects,
    sync_project,
    uninstall_user,
)


@pytest.fixture
def home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setenv("AI_GOVERNANCE_STATE_DIR", str(home / "state"))
    monkeypatch.delenv("CODEX_HOME", raising=False)
    return home


@pytest.fixture
def project(home: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = home / "repo"
    (root / "src").mkdir(parents=True)
    (root / "pom.xml").write_text("<project/>")
    monkeypatch.setattr(installer, "detect_stacks", lambda root: {"java"})
    return root


def _tree(root: Path) -> dict[str, str]:
    return {str(p.relative_to(root)): p.read_text() for p in sorted(root.rglob("*")) if p.is_file()}


# -- user scope ---------------------------------------------------------------------


def test_user_install_touches_only_the_chosen_agent(home: Path) -> None:
    install_user(["claude"])
    assert (home / ".claude" / "rules" / "ai-governance.md").exists()
    assert (home / ".claude" / "agents" / "scout.md").read_text().count("effort: medium") == 1
    assert not (home / ".codex").exists()
    assert not (home / ".gemini").exists()
    settings = json.loads((home / ".claude" / "settings.json").read_text())
    commands = [h["command"] for g in settings["hooks"]["PostToolUse"] for h in g["hooks"]]
    assert commands == ["ai-governance hook claude post-tool-use"]


def test_user_install_preserves_foreign_settings_and_is_idempotent(home: Path) -> None:
    settings = home / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(
        json.dumps(
            {
                "theme": "dark",
                "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "mine"}]}]},
            }
        )
    )
    install_user(["claude"])
    second = install_user(["claude"])
    assert not second.changed
    data = json.loads(settings.read_text())
    assert data["theme"] == "dark"
    stop = [h["command"] for g in data["hooks"]["Stop"] for h in g["hooks"]]
    assert stop == ["mine", "ai-governance hook claude stop"]

    uninstall_user(["claude"])
    data = json.loads(settings.read_text())
    assert data == {
        "theme": "dark",
        "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "mine"}]}]},
    }
    assert not (home / ".claude" / "rules" / "ai-governance.md").exists()


def test_codex_and_antigravity_use_marker_blocks(home: Path) -> None:
    (home / ".codex").mkdir()
    (home / ".codex" / "AGENTS.md").write_text("# My rules\n")
    install_user(["codex", "antigravity"])
    codex = (home / ".codex" / "AGENTS.md").read_text()
    assert codex.startswith("# My rules") and "<!-- ai-governance:start -->" in codex
    scout = (home / ".gemini" / "config" / "agents" / "scout.md").read_text()
    assert "model: flash\n" in scout and "commandExecutionPolicy: off\n" in scout
    assert "tools:\n  - view_file\n  - grep_search\n  - find_by_name\n  - list_dir\n" in scout
    rule = (home / ".gemini" / "config" / "rules" / "ai-governance.md").read_text()
    assert rule.startswith("---\ntrigger: always_on\n---\n")
    assert not (home / ".gemini" / "GEMINI.md").exists()
    uninstall_user(["codex"])
    assert (home / ".codex" / "AGENTS.md").read_text() == "# My rules\n"
    assert (home / ".gemini" / "config" / "rules" / "ai-governance.md").exists()


def test_claude_splits_scout_and_researcher(home: Path) -> None:
    install_user(["claude"])
    agents = home / ".claude" / "agents"
    scout, researcher = (agents / "scout.md").read_text(), (agents / "researcher.md").read_text()
    assert "model: haiku\n" in scout and "tools: Read, Grep, Glob\n" in scout
    assert "model: sonnet\n" in researcher and "WebSearch, WebFetch" in researcher
    assert all("omitClaudeMd: true\n" in text for text in (scout, researcher))


def test_every_agent_gets_the_bundled_skills(home: Path) -> None:
    install_user(["claude", "codex", "antigravity"])
    for skills_dir in (
        home / ".claude" / "skills",
        home / ".agents" / "skills",
        home / ".gemini" / "config" / "skills",
    ):
        audit = (skills_dir / "test-audit" / "SKILL.md").read_text()
        assert audit.startswith("---\nname: test-audit\n")
        assert (skills_dir / "progress" / "SKILL.md").is_file()


def test_foreign_file_is_never_overwritten_without_force(home: Path) -> None:
    scout = home / ".claude" / "agents" / "scout.md"
    scout.parent.mkdir(parents=True)
    scout.write_text("my own scout")
    report = install_user(["claude"])
    assert scout.read_text() == "my own scout"
    assert any("not created by ai-governance" in w for w in report.warnings)
    install_user(["claude"], force=True)
    assert "read-only scout" in scout.read_text()


# -- project scope ------------------------------------------------------------------


def test_project_rules_are_written_once_and_linked_for_claude(project: Path) -> None:
    sync_project(project, add_agents=["claude", "antigravity"])
    canonical = project / ".agents" / "rules" / "ai-governance-java-spring.md"
    text = canonical.read_text()
    assert text.startswith("---\npaths:\n") and "trigger: glob" in text
    link = project / ".claude" / "rules" / "ai-governance-java-spring.md"
    assert link.is_symlink() and link.resolve() == canonical.resolve()
    assert (
        (project / ".agents/rules/ai-governance-06-security-privacy.md")
        .read_text()
        .startswith("---\ntrigger: always_on")
    )
    assert not (project / ".agents" / "rules" / "ai-governance-python-async.md").exists()
    assert not (project / ".codex").exists()
    assert ".agents/rules/" in (project / "AGENTS.md").read_text()
    assert ProjectConfig.load(project).agents == ["claude", "antigravity"]
    assert project.resolve() in registered_projects()
    assert not sync_project(project).changed


def test_codex_only_project_uses_the_shared_rules_without_claude_links(project: Path) -> None:
    sync_project(project, add_agents=["codex"])
    assert (project / ".agents" / "rules" / "ai-governance-java-spring.md").is_file()
    assert not (project / ".claude").exists()


def test_project_install_then_uninstall_restores_tree(project: Path) -> None:
    (project / "AGENTS.md").write_text("# Team notes\n")
    before = _tree(project)
    sync_project(project, add_agents=["codex"])
    sync_project(project, remove_agents=["codex"])
    assert _tree(project) == before
    assert project.resolve() not in registered_projects()


def test_uninstalling_claude_and_antigravity_leaves_no_links_or_false_warnings(
    project: Path,
) -> None:
    before = sorted(project.rglob("*"))
    sync_project(project, add_agents=["claude", "antigravity"])
    report = sync_project(project, remove_agents=["claude", "antigravity"])
    assert report.warnings == []
    assert sorted(project.rglob("*")) == before


def test_installed_agents_of_a_project_excludes_the_shared_owner(project: Path) -> None:
    sync_project(project, add_agents=["claude", "antigravity"])
    lock = Ledger(project / installer.PROJECT_DIR / "lock.json", base=project)
    assert installer.installed_agents(lock) == {"claude"}  # antigravity reads the shared rules


def test_update_follows_stack_changes_and_keeps_local_edits(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sync_project(project, add_agents=["claude"])
    rules = project / ".claude" / "rules"
    security = rules / "ai-governance-06-security-privacy.md"
    security.write_text(security.read_text() + "\n- team-specific addition\n")

    monkeypatch.setattr(installer, "detect_stacks", lambda root: {"python"})
    report = sync_project(project)
    assert not (rules / "ai-governance-java-spring.md").exists()
    assert (rules / "ai-governance-python-async.md").exists()
    assert "team-specific addition" in security.read_text()
    assert any("edited locally" in w for w in report.warnings)


def test_claude_memory_is_migrated_into_agents_md(project: Path) -> None:
    (project / "CLAUDE.md").write_text("Use tabs.\n")
    sync_project(project, add_agents=["claude"])
    assert not (project / "CLAUDE.md").exists()
    assert (project / "AGENTS.md").read_text().startswith("Use tabs.")


def test_dry_run_writes_nothing(project: Path) -> None:
    before = _tree(project)
    report = sync_project(project, add_agents=["claude"], dry_run=True)
    assert report.changed
    assert _tree(project) == before


def test_missing_ws_selects_general_rules_and_warns(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(installer, "detect_stacks", lambda root: None)
    report = sync_project(project, add_agents=["claude"])
    assert any("`ws` not found" in w for w in report.warnings)
    assert not (project / ".claude" / "rules" / "ai-governance-java-spring.md").exists()


def test_no_agent_is_an_error(project: Path) -> None:
    with pytest.raises(ValueError, match="No agent selected"):
        sync_project(project)


# -- cli / doctor ---------------------------------------------------------------------


def test_cli_requires_explicit_agent_without_tty(project: Path, capsys) -> None:
    assert install_cli("install", ["--root", str(project)]) == 1
    captured = capsys.readouterr()
    assert "--agent" in captured.err + captured.out


def test_update_check_reports_stale_projects(project: Path, monkeypatch) -> None:
    sync_project(project, add_agents=["claude"])
    assert install_cli("update", ["--root", str(project), "--check"]) == 0
    monkeypatch.setattr(installer, "detect_stacks", lambda root: {"go"})
    assert install_cli("update", ["--all", "--check"]) == 1


def test_doctor_flags_claude_memory_and_duplicate_hooks(project: Path, home: Path) -> None:
    install_user(["claude"])
    sync_project(project, add_agents=["claude"])
    (project / "CLAUDE.local.md").write_text("x")
    (project / ".claude" / "settings.json").write_text(
        json.dumps(
            {
                "hooks": {
                    "Stop": [
                        {
                            "hooks": [
                                {"type": "command", "command": "ai-governance hook claude stop"}
                            ]
                        }
                    ]
                }
            }
        )
    )
    rows = check(project)
    assert any(s == FAIL and "CLAUDE.local.md" in d for _, s, d in rows)
    assert any("run twice" in d for _, _, d in rows)


def test_capability_table_covers_every_agent() -> None:
    table = capability_table()
    for spec in AGENTS.values():
        assert spec.name in table


def test_antigravity_hooks_path_is_shown_in_full() -> None:
    assert AGENTS["antigravity"].global_hooks.startswith("~/.gemini/config/hooks.json ")


def test_report_collapses_many_files_per_folder(project: Path) -> None:
    lines = sync_project(project, add_agents=["claude"]).lines()
    assert any(line.startswith("created: ") and " files in " in line for line in lines)
    assert len(lines) < 10


# -- profiles ------------------------------------------------------------------------


def test_project_config_round_trip_preserves_profiles(project: Path) -> None:
    sync_project(project, add_agents=["claude"], add_profiles=("architecture",))
    config = ProjectConfig.load(project)
    assert config.agents == ["claude"]
    assert config.profiles == ["architecture"]


def test_project_config_preserves_foreign_toml_table(project: Path) -> None:
    sync_project(project, add_agents=["claude"])
    config_path = project / ".ai-governance" / "config.toml"
    config_path.write_text(config_path.read_text() + '\n[design]\nkey = "value"\n')
    sync_project(project)
    text = config_path.read_text()
    assert "[design]" in text
    assert 'key = "value"' in text


def test_install_profile_writes_canonical_rule(project: Path) -> None:
    sync_project(project, add_agents=["claude"], add_profiles=("architecture",))
    assert (
        project / ".agents" / "rules" / "ai-governance-02-clean-architecture-hexagonal.md"
    ).is_file()


def test_uninstall_profile_removes_rule_keeps_agents_and_other_rules(project: Path) -> None:
    sync_project(project, add_agents=["claude"], add_profiles=("architecture",))
    report = sync_project(project, remove_profiles=("architecture",))
    assert not (
        project / ".agents" / "rules" / "ai-governance-02-clean-architecture-hexagonal.md"
    ).exists()
    assert (project / ".agents" / "rules" / "ai-governance-06-security-privacy.md").exists()
    assert ProjectConfig.load(project).agents == ["claude"]
    assert not report.changed or ProjectConfig.load(project).profiles == []


def test_update_reports_removed_rules_for_disabled_profile(project: Path) -> None:
    sync_project(project, add_agents=["claude"], add_profiles=("architecture",))
    config_path = project / ".ai-governance" / "config.toml"
    config_path.write_text(
        config_path.read_text().replace('profiles = ["architecture"]', "profiles = []")
    )
    report = sync_project(project)
    assert any(
        'Rules of profile "architecture" removed because it is not enabled' in w
        and "02-clean-architecture-hexagonal" in w
        for w in report.warnings
    )


def test_unknown_profile_raises(project: Path) -> None:
    with pytest.raises(ValueError, match="Unknown profile"):
        sync_project(project, add_agents=["claude"], add_profiles=("bogus",))


def test_profile_cli_flag_requires_project_scope(
    home: Path, capsys, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AI_GOVERNANCE_AGENT", "1")
    assert (
        install_cli(
            "install", ["--scope", "user", "--agent", "claude", "--profile", "architecture"]
        )
        == 2
    )


def test_rules_cli_lists_profiles(capsys, monkeypatch: pytest.MonkeyPatch) -> None:
    from ai_governance.rules.cli import main as rules_cli

    monkeypatch.setenv("AI_GOVERNANCE_AGENT", "1")
    assert rules_cli(["profiles"]) == 0
    out = capsys.readouterr().out
    assert "architecture" in out
    assert "02-clean-architecture-hexagonal" in out


def test_rules_cli_list_shows_profile_column(capsys, monkeypatch: pytest.MonkeyPatch) -> None:
    from ai_governance.rules.cli import main as rules_cli

    monkeypatch.setenv("AI_GOVERNANCE_AGENT", "1")
    assert rules_cli(["list"]) == 0
    out = capsys.readouterr().out
    assert "Profile" in out


def test_project_gate_hook_is_configurable(project: Path) -> None:
    sync_project(project, add_agents=["claude"])
    settings = json.loads((project / ".claude" / "settings.json").read_text())
    stop = [h["command"] for g in settings["hooks"]["Stop"] for h in g["hooks"]]
    assert stop == ["ai-governance hook claude stop-gate"]

    config = project / ".ai-governance" / "config.toml"
    config.write_text(config.read_text().replace("gate = true", "gate = false"))
    sync_project(project)
    assert (
        not (project / ".claude" / "settings.json").exists()
        or "stop-gate" not in (project / ".claude" / "settings.json").read_text()
    )
