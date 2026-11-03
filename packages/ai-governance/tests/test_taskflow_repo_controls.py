"""A repository's taskflow.toml has priority over the user's controls (add, replace, disable)."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import types
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


def _as_terminal(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Fakes an interactive terminal; returns the list that collects what is printed."""
    for name in cli._agent_markers():  # the suite itself may run inside an agent
        monkeypatch.delenv(name)
    printed: list[str] = []
    monkeypatch.setattr(cli.sys, "stdin", types.SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr(
        cli.sys,
        "stdout",
        types.SimpleNamespace(
            isatty=lambda: True,
            write=lambda text: printed.append(text) or len(text),
            flush=lambda: None,
        ),
    )
    return printed


def _trust(repo: Path, repos: list[Path] | None = None) -> None:
    """Approves what `taskflow trust` would show for ``repo`` in the context ``repos``."""
    (waiting,) = [p for p in load_config(repos or [repo]).pending_trust if p.repo == str(repo)]
    record_trust(repo, waiting.plan)


def _repo_file(repo: Path, text: str) -> None:
    (repo / ".ai-governance" / "taskflow.toml").write_text(text)


def test_repo_adds_controls(setup: tuple[Path, Path]) -> None:
    _, repo = setup
    _repo_file(
        repo,
        '[checks]\ncommands = ["e2e"]\n[[risk.rules]]\nname = "api"\npaths = ["api/**"]\n',
    )
    _trust(repo)
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
    _trust(repo)
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
    assert not is_trusted(repo, pending.plan)

    monkeypatch.setenv("CLAUDECODE", "1")  # an agent cannot approve
    assert cli.cmd_trust(argparse.Namespace(repo=str(repo), yes=True)) == 1
    assert not is_trusted(repo, pending.plan)

    monkeypatch.delenv("CLAUDECODE")
    _as_terminal(monkeypatch)
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


def test_command_digest_is_unambiguous_and_old_entries_become_pending(
    setup: tuple[Path, Path],
) -> None:
    from ai_governance.taskflow.config import command_digest, trust_file

    def plan(*commands: str) -> list[tuple[str, str]]:
        return [("check", c) for c in commands]

    assert command_digest(plan("false", "true")) != command_digest(plan("false\ntrue"))
    assert command_digest(plan('a","b')) != command_digest(plan("a", "b"))
    assert command_digest(plan("a", "b")) != command_digest(plan("b", "a"))
    assert command_digest(plan("a", "b")) != command_digest(plan("a", "b", "a"))
    assert command_digest(plan("a")).startswith("v3:")
    _, repo = setup
    _repo_file(repo, '[checks]\ncommands = ["make evil"]\n')
    trust_file().parent.mkdir(parents=True, exist_ok=True)
    old = hashlib.sha256(b"make evil").hexdigest()[:16]  # the previous newline-joined scheme
    trust_file().write_text(json.dumps({str(repo.resolve()): old}))
    assert load_config([repo]).pending_trust  # pending again, no crash
    trust_file().write_text("not json")
    assert load_config([repo]).pending_trust


def test_trust_needs_a_real_terminal_even_with_yes(
    setup: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    _, repo = setup
    _repo_file(repo, '[checks]\ncommands = ["make evil"]\n')
    args = argparse.Namespace(repo=str(repo), yes=True)
    _as_terminal(monkeypatch)
    monkeypatch.setattr(
        cli.sys,
        "stdout",
        types.SimpleNamespace(isatty=lambda: False, write=lambda s: len(s), flush=lambda: None),
    )
    assert cli.cmd_trust(args) == 1  # stdout is not a terminal
    _as_terminal(monkeypatch)
    monkeypatch.setattr(cli.sys, "stdin", types.SimpleNamespace(isatty=lambda: False))
    assert cli.cmd_trust(args) == 1  # stdin is not a terminal
    assert load_config([repo]).pending_trust


@pytest.mark.parametrize(
    "marker", ["CLAUDECODE", "CODEX_SANDBOX", "CODEX_HOME_X", "CLAUDE_CODE_CHILD_SESSION"]
)
def test_trust_ignores_the_agent_override_variable(
    setup: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch, marker: str
) -> None:
    _, repo = setup
    _repo_file(repo, '[checks]\ncommands = ["make evil"]\n')
    _as_terminal(monkeypatch)
    monkeypatch.setenv("AI_GOVERNANCE_AGENT", "0")
    monkeypatch.setenv(marker, "1")
    assert cli.cmd_trust(argparse.Namespace(repo=str(repo), yes=True)) == 1
    assert load_config([repo]).pending_trust
    monkeypatch.delenv(marker)
    assert cli.cmd_trust(argparse.Namespace(repo=str(repo), yes=True)) == 0


def test_each_repo_is_trusted_on_its_own_delta(setup: tuple[Path, Path], tmp_path: Path) -> None:
    _, repo_a = setup
    repo_b = tmp_path / "repo-b"
    (repo_b / ".ai-governance").mkdir(parents=True)
    _repo_file(repo_a, '[[risk.rules]]\nname = "a"\npaths = ["a/**"]\nchecks = ["a-cmd"]\n')
    (repo_b / ".ai-governance" / "taskflow.toml").write_text(
        '[[risk.rules]]\nname = "b"\npaths = ["b/**"]\nchecks = ["b-cmd"]\n'
    )
    _trust(repo_a)
    config = load_config([repo_a, repo_b])
    rules = {r.name: r.checks for r in config.risk_rules}
    assert rules["a"] == ("a-cmd",)  # A's approved command survives B's evaluation
    (pending,) = config.pending_trust
    assert pending.repo == str(repo_b) and pending.commands == ("b-cmd",)
    assert [p.commands for p in load_config([repo_b]).pending_trust] == [("b-cmd",)]
    _trust(repo_b, [repo_a, repo_b])
    both = load_config([repo_a, repo_b])
    assert not both.pending_trust and {r.name: r.checks for r in both.risk_rules}["b"] == ("b-cmd",)


def test_the_trusted_order_is_the_order_that_runs(setup: tuple[Path, Path]) -> None:
    _, repo = setup
    _repo_file(repo, '[checks]\ncommands = ["printf true > payload.sh", "sh payload.sh"]\n')
    assert load_config([repo]).pending_trust
    _trust(repo)
    config = load_config([repo])
    assert not config.pending_trust  # same order: trusted
    assert config.checks[-2:] == ("printf true > payload.sh", "sh payload.sh")

    _repo_file(repo, '[checks]\ncommands = ["sh payload.sh", "printf true > payload.sh"]\n')
    reordered = load_config([repo])
    assert reordered.pending_trust  # same commands, other order: approve again
    assert (
        "sh payload.sh" not in reordered.checks
        and "printf true > payload.sh" not in reordered.checks
    )

    _repo_file(repo, '[checks]\ncommands = ["printf true > payload.sh", "sh payload.sh"]\n')
    assert not load_config([repo]).pending_trust  # back to the approved order


def test_moving_a_risk_rule_command_needs_new_trust(setup: tuple[Path, Path]) -> None:
    _, repo = setup
    rule = '[[risk.rules]]\nname = "api"\npaths = ["a/**"]\nchecks = ["x", "y"]\n'
    _repo_file(repo, '[checks]\ncommands = ["c1"]\n' + rule)
    _trust(repo)
    assert not load_config([repo]).pending_trust

    swapped = rule.replace('["x", "y"]', '["y", "x"]')
    _repo_file(repo, '[checks]\ncommands = ["c1"]\n' + swapped)
    assert load_config([repo]).pending_trust  # order inside the rule

    interleaved = '[checks]\ncommands = ["c1", "x"]\n' + rule.replace('["x", "y"]', '["y"]')
    _repo_file(repo, interleaved)  # x moved from the rule into the checks
    assert load_config([repo]).pending_trust

    other_rule = rule.replace('name = "api"', 'name = "other"')
    _repo_file(repo, '[checks]\ncommands = ["c1"]\n' + other_rule)
    assert load_config([repo]).pending_trust  # same commands under another rule name


def test_trust_shows_the_ordered_plan_it_approves(
    setup: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _, repo = setup
    _repo_file(
        repo,
        '[checks]\ncommands = ["first", "second"]\n'
        '[[risk.rules]]\nname = "api"\npaths = ["a/**"]\nchecks = ["third"]\n',
    )
    printed = _as_terminal(monkeypatch)
    assert cli.cmd_trust(argparse.Namespace(repo=str(repo), yes=True)) == 0
    shown = "".join(printed)
    order = [shown.index(f"$ {c}") for c in ("lint", "first", "second", "third")]
    assert order == sorted(order) and "[rule api]" in shown
    assert not load_config([repo]).pending_trust


def test_v2_entries_are_pending_again(setup: tuple[Path, Path]) -> None:
    from ai_governance.taskflow.config import trust_file

    _, repo = setup
    _repo_file(repo, '[checks]\ncommands = ["make evil"]\n')
    trust_file().parent.mkdir(parents=True, exist_ok=True)
    old = "v2:" + hashlib.sha256(b'["make evil"]').hexdigest()[:16]
    trust_file().write_text(json.dumps({str(repo.resolve()): old}))
    assert load_config([repo]).pending_trust
