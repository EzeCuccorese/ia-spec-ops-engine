"""A repository's taskflow.toml has priority over the user's controls (add, replace, disable)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from ai_governance.config_cli import main as config_main
from ai_governance.settings import effective
from ai_governance.taskflow.config import load_config
from ai_governance.taskflow.policy import policy_reductions, policy_summary


@pytest.fixture
def setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    monkeypatch.setenv("AI_GOVERNANCE_CONFIG_DIR", str(cfg))
    repo = tmp_path / "repo"
    (repo / ".ai-governance").mkdir(parents=True)
    (repo / ".git").mkdir()
    (cfg / "taskflow.toml").write_text(
        '[[judges]]\nfocus = "correctness"\nagent = "codex"\nmodel = "m1"\n'
        '[[judges]]\nfocus = "security"\nagent = "antigravity"\nmodel = "m2"\n'
        '[checks]\ncommands = ["lint", "unit"]\n'
        '[[risk.rules]]\nname = "migrations"\npaths = ["db/**"]\njudges = ["security"]\n'
        '[[risk.rules]]\nname = "infra"\npaths = ["infra/**"]\n'
    )
    return cfg, repo


def _repo_file(repo: Path, text: str) -> None:
    (repo / ".ai-governance" / "taskflow.toml").write_text(text)


def test_repo_adds_controls(setup: tuple[Path, Path]) -> None:
    _, repo = setup
    _repo_file(
        repo,
        '[checks]\ncommands = ["e2e"]\n[[risk.rules]]\nname = "api"\npaths = ["api/**"]\n',
    )
    config = load_config([repo])
    assert config.checks == ("lint", "unit", "e2e")
    assert [r.name for r in config.risk_rules] == ["migrations", "infra", "api"]


def test_repo_replaces_a_rule_and_a_judge_but_not_who_runs_it(setup: tuple[Path, Path]) -> None:
    _, repo = setup
    _repo_file(
        repo,
        '[[risk.rules]]\nname = "migrations"\npaths = ["db/**", "sql/**"]\nrestaging = true\n'
        '[[judges]]\nfocus = "security"\nagent = "claude"\nmodel = "evil"\n',
    )
    config = load_config([repo])
    rule = next(r for r in config.risk_rules if r.name == "migrations")
    assert rule.paths == ("db/**", "sql/**") and rule.restaging and rule.judges == ()
    assert len([r for r in config.risk_rules if r.name == "migrations"]) == 1
    security = next(j for j in config.judges if j["focus"] == "security")
    assert (security["agent"], security["model"]) == ("antigravity", "m2")


def test_repo_disables_controls(setup: tuple[Path, Path]) -> None:
    _, repo = setup
    _repo_file(
        repo,
        '[disable]\njudges = ["security"]\nchecks = ["unit"]\nrisk = ["infra"]\n',
    )
    config = load_config([repo])
    assert [j["focus"] for j in config.judges] == ["correctness"]
    assert config.checks == ("lint",)
    assert [r.name for r in config.risk_rules] == ["migrations"]


def test_disabling_is_a_policy_reduction_needing_approval(setup: tuple[Path, Path]) -> None:
    _, repo = setup
    before = policy_summary(load_config([]))
    _repo_file(repo, '[disable]\nchecks = ["unit"]\n')
    assert "checks:unit" in policy_reductions(before, policy_summary(load_config([repo])))


def test_user_only_keys_are_still_ignored_from_the_repo(setup: tuple[Path, Path]) -> None:
    _, repo = setup
    _repo_file(repo, 'workflow = "single-agent"\n[roles.builder]\nagent = "codex"\nmodel = "x"\n')
    (repo / ".ai-governance" / "config.toml").write_text(
        '[taskflow]\nbuilder_agent = "codex"\n[hooks]\ngate_command = "evil"\n'
        '[agents]\nclaude_binary = "evil"\n[corporate]\npacks = ["x"]\n'
    )
    config = load_config([repo])
    assert config.workflow == "tri-agent" and config.roles["builder"]["agent"] == "claude"
    found = effective(repo)
    for key in (
        "taskflow.builder_agent",
        "hooks.gate_command",
        "agents.claude_binary",
        "corporate.packs",
    ):
        assert found[key].origin == "default", key


def test_config_show_reports_who_set_each_control(
    setup: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _, repo = setup
    _repo_file(
        repo,
        '[checks]\ncommands = ["e2e"]\n[[risk.rules]]\nname = "migrations"\npaths = ["x"]\n'
        '[disable]\nchecks = ["unit"]\n',
    )
    monkeypatch.chdir(repo)
    assert config_main(["show", "--origin", "--json"]) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["taskflow.check.lint"]["origin"] == "user"
    assert shown["taskflow.check.e2e"]["value"] == "repo (added)"
    assert shown["taskflow.risk.migrations"]["value"] == "repo (replaced)"
    assert shown["taskflow.check.unit"]["value"] == "repo (disabled)"
    assert shown["taskflow.check.e2e"]["source"].endswith(".ai-governance/taskflow.toml")
