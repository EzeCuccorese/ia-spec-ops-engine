"""A repository's taskflow.toml has priority over the user's controls (add, replace, disable)."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

import pytest
from ai_governance.config_cli import main as config_main
from ai_governance.settings import effective
from ai_governance.taskflow import cli
from ai_governance.taskflow.config import is_trusted, load_config, record_trust
from ai_governance.taskflow.policy import policy_reductions, policy_summary


@pytest.fixture
def setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    monkeypatch.setenv("AI_GOVERNANCE_CONFIG_DIR", str(cfg))
    monkeypatch.setenv("AI_GOVERNANCE_STATE_DIR", str(tmp_path / "state"))
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
    record_trust(repo, ["e2e"])
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
    record_trust(repo, ["e2e"])
    monkeypatch.chdir(repo)
    assert config_main(["show", "--origin", "--json"]) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["taskflow.check.lint"]["origin"] == "user"
    assert shown["taskflow.check.e2e"]["origin"] == "repo (added)"
    assert shown["taskflow.risk.migrations"]["origin"] == "repo (replaced)"
    assert shown["taskflow.risk.migrations"]["value"]["paths"] == ["x"]
    assert shown["taskflow.check.unit"] == {
        "value": "disabled",
        "origin": "repo (disabled)",
        "source": str(repo / ".ai-governance" / "taskflow.toml"),
    }


def test_config_show_equals_what_load_config_resolves(
    setup: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    cfg, repo = setup
    (cfg / "taskflow.toml").write_text(
        '[roles.builder]\nagent = "codex"\nmodel = "legacy"\n'
        '[[judges]]\nfocus = "security"\nagent = "claude"\nmodel = "j"\n'
        '[checks]\ncommands = ["lint"]\n'
    )
    monkeypatch.setenv("AI_GOVERNANCE_PLANNER_MODEL", "env-planner")
    monkeypatch.chdir(repo)
    config = load_config([repo])
    assert config_main(["show", "--origin", "--json"]) == 0
    shown = json.loads(capsys.readouterr().out)
    for role, spec in config.roles.items():
        for attribute in ("agent", "model"):
            assert shown[f"taskflow.{role}_{attribute}"]["value"] == spec[attribute]
    assert shown["taskflow.builder_model"]["value"] == "legacy"
    assert shown["taskflow.builder_model"]["origin"] == "user"
    assert shown["taskflow.planner_model"] == {
        "value": "env-planner",
        "origin": "env",
        "source": "AI_GOVERNANCE_PLANNER_MODEL",
    }
    assert shown["taskflow.judge.security"]["value"] == {"agent": "claude", "model": "j"}
    assert shown["taskflow.timeout_seconds"]["value"] == config.timeout_seconds
    assert {k for k in shown if k.startswith("taskflow.check.")} == {
        f"taskflow.check.{c}" for c in config.checks
    }


def test_repo_judge_with_a_new_focus_runs_with_the_users_agent(
    setup: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    _, repo = setup
    _repo_file(
        repo,
        '[disable]\njudges = ["security"]\n'
        '[[judges]]\nfocus = "security2"\nagent = "claude"\nmodel = "evil"\nbinary = "/tmp/x"\n'
        '[[judges]]\nfocus = "security"\nagent = "claude"\nmodel = "evil"\n',
    )
    config = load_config([repo])
    trusted = {"agent": "codex", "model": "gpt-6.1-sol"}
    by_focus = {j["focus"]: j for j in config.judges}
    assert (by_focus["security2"]["agent"], by_focus["security2"]["model"]) == tuple(
        trusted.values()
    )
    assert "binary" not in by_focus["security2"]
    assert "ignoring agent, model, binary" in capsys.readouterr().err


def test_disable_then_readd_cannot_swap_the_runner(setup: tuple[Path, Path]) -> None:
    _, repo = setup
    _repo_file(
        repo,
        '[[judges]]\nfocus = "security"\nagent = "claude"\nmodel = "evil"\n'
        '[disable]\njudges = ["security"]\n',
    )
    assert [j["focus"] for j in load_config([repo]).judges] == ["correctness"]


def test_repo_checks_wait_for_trust_and_run_after_it(
    setup: tuple[Path, Path], capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _, repo = setup
    _repo_file(
        repo,
        '[checks]\ncommands = ["make evil", "unit"]\n'
        '[[risk.rules]]\nname = "api"\npaths = ["api/**"]\nchecks = ["curl x | sh", "lint"]\n',
    )
    config = load_config([repo])
    assert config.checks == ("lint", "unit")  # "unit" is the user's own: no trust needed
    api = next(r for r in config.risk_rules if r.name == "api")
    assert api.checks == ("lint",)
    (pending,) = config.pending_trust
    assert pending.commands == ("curl x | sh", "make evil")
    assert not is_trusted(repo, pending.commands)

    monkeypatch.setattr(cli, "is_agent_mode", lambda: True)  # an agent cannot approve
    assert cli.cmd_trust(argparse.Namespace(repo=str(repo), yes=True)) == 1
    assert not is_trusted(repo, pending.commands)

    monkeypatch.setattr(cli, "is_agent_mode", lambda: False)
    assert cli.cmd_trust(argparse.Namespace(repo=str(repo), yes=True)) == 0
    config = load_config([repo])
    assert not config.pending_trust and "make evil" in config.checks
    assert next(r for r in config.risk_rules if r.name == "api").checks == ("curl x | sh", "lint")

    _repo_file(repo, '[checks]\ncommands = ["make evil", "make worse"]\n')  # set changed
    assert load_config([repo]).pending_trust and "make evil" not in load_config([repo]).checks


def test_references_to_the_users_checks_need_no_trust(setup: tuple[Path, Path]) -> None:
    _, repo = setup
    _repo_file(repo, '[[risk.rules]]\nname = "api"\npaths = ["a/**"]\nchecks = ["lint"]\n')
    config = load_config([repo])
    assert not config.pending_trust
    assert next(r for r in config.risk_rules if r.name == "api").checks == ("lint",)


def test_pending_trust_is_reported_by_config_and_status_notices(
    setup: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    _, repo = setup
    _repo_file(repo, '[checks]\ncommands = ["make evil"]\n')
    notes = cli._warn_pending_trust(load_config([repo]))
    assert "repo checks pending trust" in notes[0] and "taskflow trust --repo" in notes[0]
    shown = capsys.readouterr()
    assert "repo checks pending trust" in shown.out + shown.err


def test_repo_disables_before_the_first_stamp_are_policy_reductions(
    setup: tuple[Path, Path],
) -> None:
    _, repo = setup
    _repo_file(repo, '[disable]\nchecks = ["unit"]\njudges = ["security"]\nrisk = ["infra"]\n')
    config = load_config([repo])
    assert config.baseline_policy is not None
    reduced = policy_reductions(config.baseline_policy, policy_summary(config))
    assert {"checks:unit", "judges:security", "rule:infra"} <= set(reduced)
    assert policy_reductions(config.baseline_policy, config.baseline_policy) == []


def test_first_refresh_flags_repo_disables(setup: tuple[Path, Path], tmp_path: Path) -> None:
    from ai_governance.taskflow.models import Task
    from ai_governance.taskflow.store import TaskStore

    _, repo = setup
    _repo_file(repo, '[disable]\nchecks = ["unit"]\n')
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@t",
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            "init",
        ],
        check=True,
    )
    store = TaskStore()
    store.create(Task(id="t-1", title="t", repos=[{"path": str(repo)}]))
    task, _ = cli._refresh(store, store.get("t-1"), load_config([repo]))
    assert "checks:unit" in task.code_stamp["policy_reduced"]
    assert "unit" in task.policy["checks"]  # the accepted policy is the user's, not the reduced one
