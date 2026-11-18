"""Allowed agents per repository, provider normalization, effort and denied models."""

from __future__ import annotations

import json
import os
import signal
import subprocess
from pathlib import Path

import pytest
from ai_governance import config_cli
from ai_governance._config_core import ConfigError
from ai_governance.install.content import TASKFLOW_SKILL
from ai_governance.settings import SETTINGS
from ai_governance.taskflow.agents import DEFAULT_MODELS, provider
from ai_governance.taskflow.config import FlowConfig, load_config

REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(autouse=True)
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("AI_GOVERNANCE_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("AI_GOVERNANCE_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.delenv("AI_GOVERNANCE_ALLOWED_AGENTS", raising=False)
    monkeypatch.delenv("AI_GOVERNANCE_DENIED_MODELS", raising=False)
    for role in ("PLANNER", "VALIDATOR", "BUILDER", "JUDGE", "DEBATER"):
        for field in ("AGENT", "MODEL", "EFFORT"):
            monkeypatch.delenv(f"AI_GOVERNANCE_{role}_{field}", raising=False)
    monkeypatch.chdir(tmp_path)
    return tmp_path / "cfg"


def _repo(tmp_path: Path, name: str, toml: str | None) -> Path:
    path = tmp_path / name
    (path / ".ai-governance").mkdir(parents=True)
    if toml is not None:
        (path / ".ai-governance" / "config.toml").write_text(toml, encoding="utf-8")
    return path


def _restricted(tmp_path: Path, *agents: str, name: str = "r") -> Path:
    listed = ", ".join(f'"{a}"' for a in agents)
    return _repo(tmp_path, name, f"[taskflow]\nallowed_agents = [{listed}]\n")


def _problems(config: FlowConfig) -> list[str]:
    return list(config.validate())


# --- provider normalization -------------------------------------------------------------


def test_provider_compares_the_prefix_only() -> None:
    assert provider("codex/gpt-6.1-sol") == "codex"
    assert provider("Claude") == "claude"
    assert provider("claude/opus") == provider("claude")
    assert provider("human") == "human"
    assert provider("something-new/x") == "something-new"


def test_agy_alias_is_antigravity() -> None:
    assert provider("agy") == "antigravity" == provider("antigravity/gemini")


# --- allowed agents: narrowing only ---------------------------------------------------


def test_restricted_repo_defaults(tmp_path: Path) -> None:
    config = load_config([_restricted(tmp_path, "claude", "codex")])
    assert config.roles["debater"]["agent"] == "codex"
    assert config.roles["builder"]["agent"] == "claude"
    assert _problems(config) == []


def test_this_repository_ends_with_claude_and_codex(isolated: Path) -> None:
    config = load_config([REPO_ROOT])
    assert sorted(config.allowed.agents) == ["claude", "codex"]
    assert config.roles["debater"]["agent"] == "codex"
    assert _problems(config) == []


def test_unrestricted_repo_keeps_global_defaults(tmp_path: Path) -> None:
    config = load_config([_repo(tmp_path, "free", None)])
    assert "antigravity" in config.allowed.agents
    assert _problems(config) == []


def test_antigravity_stays_valid_for_another_repository(tmp_path: Path) -> None:
    restricted = load_config([REPO_ROOT])
    elsewhere = load_config([_repo(tmp_path, "other", "")])
    assert "antigravity" not in restricted.allowed.agents
    assert elsewhere.allowed.permits("antigravity") and elsewhere.allowed.permits("agy")


def test_effective_set_is_user_intersect_repo(tmp_path: Path, isolated: Path) -> None:
    isolated.mkdir(parents=True)
    (isolated / "config.toml").write_text('[taskflow]\nallowed_agents = ["claude", "codex"]\n')
    config = load_config([_restricted(tmp_path, "codex", "antigravity")])
    assert sorted(config.allowed.agents) == ["codex"]  # the repo only removes


def test_repo_cannot_widen(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_GOVERNANCE_ALLOWED_AGENTS", "claude,codex")
    config = load_config([_restricted(tmp_path, "claude", "codex", "antigravity")])
    assert sorted(config.allowed.agents) == ["claude", "codex"]
    assert not config.allowed.permits("antigravity")


def test_two_repositories_the_strictest_wins_and_deleting_lifts_only_its_restriction(
    tmp_path: Path,
) -> None:
    wide = _restricted(tmp_path, "claude", "codex", name="wide")
    narrow = _restricted(tmp_path, "codex", name="narrow")
    assert sorted(load_config([wide, narrow]).allowed.agents) == ["codex"]
    (narrow / ".ai-governance" / "config.toml").unlink()
    assert sorted(load_config([wide, narrow]).allowed.agents) == ["claude", "codex"]


# --- allowed agents: fail closed ------------------------------------------------------


@pytest.mark.parametrize(
    "toml",
    [
        "[taskflow\nallowed_agents = [",  # invalid TOML
        '[taskflow]\nallowed_agents = "claude"\n',  # wrong type
        "[taskflow]\nallowed_agents = [1, 2]\n",  # wrong item type
        '[taskflow]\nallowed_agents = ["Claude!"]\n',  # id outside the pattern
        "taskflow = 3\n",  # the table itself has the wrong type
    ],
)
def test_malformed_repo_value_blocks_every_agent_and_names_the_file(
    tmp_path: Path, toml: str
) -> None:
    repo = _repo(tmp_path, "bad", toml)
    config = load_config([repo])
    assert not config.allowed.permits("claude") and not config.allowed.permits("codex")
    errors = config.validate()
    assert any(str(repo / ".ai-governance" / "config.toml") in e for e in errors)


def test_unreadable_repo_file_blocks_agents(tmp_path: Path) -> None:
    repo = _repo(tmp_path, "dir", None)
    (repo / ".ai-governance" / "config.toml").mkdir()
    config = load_config([repo])
    assert not config.allowed.permits("claude")
    assert any("config.toml" in e for e in config.validate())


def test_empty_list_allows_no_agent(tmp_path: Path) -> None:
    config = load_config([_repo(tmp_path, "none", "[taskflow]\nallowed_agents = []\n")])
    assert any("allows no agent" in e for e in config.validate())
    assert not config.allowed.permits("claude")
    assert config.allowed.permits("human")


def test_empty_intersection_is_reported_never_unrestricted(tmp_path: Path) -> None:
    a = _restricted(tmp_path, "claude", name="a")
    b = _restricted(tmp_path, "codex", name="b")
    config = load_config([a, b])
    assert not config.allowed.agents
    assert any("allows no agent" in e for e in config.validate())


def test_malformed_user_value_blocks_agents(isolated: Path) -> None:
    isolated.mkdir(parents=True)
    (isolated / "config.toml").write_text('[taskflow]\nallowed_agents = ["Bad Id"]\n')
    config = load_config([])
    assert not config.allowed.permits("claude")
    assert any("allowed_agents" in e for e in config.validate())


# --- explicit choices are errors, never swapped -----------------------------------------


def test_explicit_disallowed_role_is_an_error_not_a_swap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AI_GOVERNANCE_DEBATER_AGENT", "antigravity")
    config = load_config([_restricted(tmp_path, "claude", "codex")])
    assert config.roles["debater"]["agent"] == "antigravity"
    assert any("debater" in e and "not allowed" in e for e in config.validate())
    assert config.agent_error("antigravity") and config.agent_error("agy/x")
    assert config.agent_error("codex/gpt") is None and config.agent_error("human") is None


def test_setting_is_user_only_and_documented() -> None:
    assert "taskflow.allowed_agents" in {s.key for s in SETTINGS}


# --- a restriction file that exists but cannot be read never lifts the restriction ---------


def _dangling_file(repo: Path) -> None:
    (repo / ".ai-governance" / "config.toml").symlink_to(repo / "nowhere.toml")


def _loop_file(repo: Path) -> None:
    link = repo / ".ai-governance" / "config.toml"
    link.symlink_to(link)


def _unreadable_file(repo: Path) -> None:
    path = repo / ".ai-governance" / "config.toml"
    path.write_text('[taskflow]\nallowed_agents = ["claude"]\n')
    path.chmod(0)


def _directory_file(repo: Path) -> None:
    (repo / ".ai-governance" / "config.toml").mkdir()


def _dangling_parent(repo: Path) -> None:
    (repo / ".ai-governance").rmdir()
    (repo / ".ai-governance").symlink_to(repo / "nowhere")


def _loop_parent(repo: Path) -> None:
    (repo / ".ai-governance").rmdir()
    (repo / ".ai-governance").symlink_to(repo / ".ai-governance")


@pytest.mark.parametrize(
    "break_it",
    [_dangling_file, _loop_file, _unreadable_file, _directory_file, _dangling_parent, _loop_parent],
)
def test_unreadable_restriction_blocks_every_agent(tmp_path: Path, break_it) -> None:
    repo = _repo(tmp_path, "broken", None)
    break_it(repo)
    try:
        try:
            config = load_config([repo])
        except ValueError as exc:
            assert ".ai-governance" in str(exc)
            return
        assert not config.allowed.permits("claude") and not config.allowed.permits("codex")
        assert any(".ai-governance" in e for e in config.validate())
        assert config.agent_error("claude") is not None
    finally:
        cfg = repo / ".ai-governance" / "config.toml"
        if cfg.exists() and not cfg.is_symlink():
            cfg.chmod(0o600)


def test_absent_file_and_absent_directory_are_unrestricted(tmp_path: Path) -> None:
    bare = tmp_path / "bare"
    bare.mkdir()
    assert load_config([bare]).allowed.permits("antigravity")
    assert load_config([_repo(tmp_path, "empty", None)]).allowed.permits("antigravity")
    assert load_config([tmp_path / "gone"]).allowed.permits("antigravity")


def test_empty_id_is_an_invalid_id_not_an_empty_list(tmp_path: Path) -> None:
    config = load_config([_repo(tmp_path, "e", '[taskflow]\nallowed_agents = [""]\n')])
    assert any("not a valid agent id" in e for e in config.validate())


# --- diagnostics ------------------------------------------------------------------------


def _show(capsys: pytest.CaptureFixture[str]) -> tuple[int, dict]:
    code = config_cli.main(["show", "--origin", "--json"])
    return code, json.loads(capsys.readouterr().out)


def test_config_show_marks_the_restriction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _restricted(tmp_path, "claude", "codex")
    monkeypatch.chdir(repo)
    code, rows = _show(capsys)
    row = rows["taskflow.allowed_agents"]
    assert code == 0 and row["value"] == ["claude", "codex"]
    assert row["origin"] == "repo (narrowed)" and row["source"].endswith("config.toml")


def test_config_show_reports_a_blocked_restriction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _repo(tmp_path, "bad", "[taskflow]\nallowed_agents = [1]\n")
    monkeypatch.chdir(repo)
    code, rows = _show(capsys)
    row = rows["taskflow.allowed_agents"]
    assert code == 1 and row["value"] == [] and row["origin"] == "blocked"
    assert str(repo / ".ai-governance" / "config.toml") in row["source"]


def test_taskflow_config_prints_allowed_agents_from_a_child_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from ai_governance.taskflow.cli import main

    repo = _restricted(tmp_path, "claude", "codex")
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (repo / "child").mkdir()
    monkeypatch.chdir(repo / "child")
    main(["config"])
    out = capsys.readouterr().out
    assert "allowed agents" in out and "claude, codex" in out and "antigravity" not in out


def test_run_refusal_names_the_broken_file(tmp_path: Path) -> None:
    repo = _repo(tmp_path, "bad", "[taskflow]\nallowed_agents = [1]\n")
    refusal = load_config([repo]).agent_error("claude")
    assert refusal and str(repo / ".ai-governance" / "config.toml") in refusal


def test_default_models_follow_the_settings_defaults() -> None:
    defaults = {s.key: s.default for s in SETTINGS}
    for role in ("planner", "validator", "builder", "judge", "debater"):
        if f"taskflow.{role}_agent" not in defaults:
            continue
        agent, model = defaults[f"taskflow.{role}_agent"], defaults[f"taskflow.{role}_model"]
        assert DEFAULT_MODELS[str(agent)] == model
        assert defaults[f"taskflow.{role}_effort"] == ""
    assert defaults["taskflow.denied_models"] == []


def test_installed_skill_stays_within_budget() -> None:
    assert len(TASKFLOW_SKILL.encode()) <= 2500


# --- unreadable USER config, special files and secondary files -------------------------------


@pytest.fixture
def deadline():
    """A FIFO must never hang the suite: any test using this fails after 5 seconds instead."""

    def expired(signum: int, frame: object) -> None:
        raise TimeoutError("configuration loading blocked on a special file")

    signal.signal(signal.SIGALRM, expired)
    signal.alarm(5)
    yield
    signal.alarm(0)


def _user_file(isolated: Path, name: str = "config.toml") -> Path:
    isolated.mkdir(parents=True, exist_ok=True)
    return isolated / name


def _user_unreadable(path: Path) -> None:
    path.write_text('[taskflow]\nallowed_agents = ["codex"]\n')
    path.chmod(0)


def _user_directory(path: Path) -> None:
    path.mkdir()


def _user_dangling(path: Path) -> None:
    path.symlink_to(path.parent / "nowhere.toml")


def _user_fifo(path: Path) -> None:
    os.mkfifo(path)


@pytest.mark.parametrize("name", ["config.toml", "config.json", "taskflow.toml"])
@pytest.mark.parametrize(
    "break_it", [_user_unreadable, _user_directory, _user_dangling, _user_fifo]
)
def test_unreadable_user_source_blocks_every_agent(
    isolated: Path, name: str, break_it, deadline
) -> None:
    path = _user_file(isolated, name)
    break_it(path)
    try:
        config = load_config([])
        assert not config.allowed.permits("claude") and not config.allowed.permits("codex")
        assert any(str(path) in e for e in config.validate())
        assert config.allowed.permits("human")
    finally:
        if path.exists() and not path.is_symlink() and path.is_file():
            path.chmod(0o600)


def test_invalid_user_toml_fails_loudly_naming_the_file(isolated: Path) -> None:
    path = _user_file(isolated)
    path.write_text("[taskflow\nallowed_agents = [")
    with pytest.raises(ConfigError, match="config.toml"):
        load_config([])


def test_absent_user_config_uses_the_default(isolated: Path) -> None:
    assert load_config([]).allowed.permits("antigravity")


@pytest.mark.parametrize("value", [",", " "])
def test_degenerate_env_value_never_widens(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("AI_GOVERNANCE_ALLOWED_AGENTS", value)
    assert not load_config([]).allowed.permits("antigravity")


def test_fifo_at_the_repo_restriction_blocks_without_hanging(tmp_path: Path, deadline) -> None:
    repo = _repo(tmp_path, "fifo", None)
    os.mkfifo(repo / ".ai-governance" / "config.toml")
    config = load_config([repo])
    assert not config.allowed.permits("claude")
    assert any("config.toml" in e for e in config.validate())


def test_fifo_at_the_repo_taskflow_file_does_not_hang(tmp_path: Path, deadline) -> None:
    repo = _repo(tmp_path, "fifo2", None)
    os.mkfifo(repo / ".ai-governance" / "taskflow.toml")
    with pytest.raises(ValueError, match="taskflow.toml"):
        load_config([repo])


def test_config_show_reports_a_broken_secondary_taskflow_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _restricted(tmp_path, "claude", "codex")
    (repo / ".ai-governance" / "taskflow.toml").write_text("[broken")
    monkeypatch.chdir(repo)
    code = config_cli.main(["show", "--origin", "--json"])
    captured = capsys.readouterr()
    assert code == 1 and "taskflow.toml" in captured.err


def test_user_source_problem_fails_closed_on_agents_but_preserves_taskflow_denied_models(
    isolated: Path,
) -> None:
    isolated.mkdir(parents=True)
    (isolated / "taskflow.toml").write_text('denied_models = ["user-blocked"]\n')
    (isolated / "config.json").symlink_to(isolated / "nonexistent.json")

    config = load_config([])
    assert config.allowed.agents == frozenset()
    assert not config.allowed.permits("claude")
    assert not config.allowed.permits("codex")
    assert any("config.json" in p for p in config.allowed.problems)
    assert "user-blocked" in config.denied_models


# --- effort and denied_models ---------------------------------------------------------------


def test_effort_and_denied_models_defaults_are_user_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo(
        tmp_path,
        "r",
        '[taskflow]\nplanner_effort = "low"\ndebater_effort = "high"\n',
    )
    cfg = load_config([repo])
    assert cfg.effort("debater") == ""
    assert cfg.denied_models == frozenset()

    monkeypatch.setenv("AI_GOVERNANCE_DEBATER_EFFORT", "medium")
    updated = load_config([repo])
    assert updated.effort("debater") == "medium"


def test_denied_models_union_across_user_and_repos_without_trust(
    tmp_path: Path, isolated: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    isolated.mkdir(parents=True, exist_ok=True)
    (isolated / "config.toml").write_text('[taskflow]\ndenied_models = ["user-cfg-model"]\n')
    (isolated / "taskflow.toml").write_text('denied_models = ["user-tf-model"]\n')
    repo_a = _repo(tmp_path, "a", '[taskflow]\ndenied_models = ["repo-cfg-model"]\n')
    repo_b = _repo(tmp_path, "b", "[taskflow]\ndenied_models = []\n")
    (repo_b / ".ai-governance" / "taskflow.toml").write_text(
        '[taskflow]\ndenied_models = ["repo-tf-model"]\n'
    )
    loaded = load_config([repo_a, repo_b])
    assert loaded.denied_models == frozenset(
        {"user-cfg-model", "user-tf-model", "repo-cfg-model", "repo-tf-model"}
    )

    monkeypatch.setenv("AI_GOVERNANCE_DENIED_MODELS", "env-model")
    with_env = load_config([repo_a, repo_b])
    assert {"env-model", "user-tf-model", "repo-cfg-model", "repo-tf-model"} <= set(
        with_env.denied_models
    )


def _setup_malformed_denied(tmp_path: Path, case: str) -> tuple[Path, str]:
    repo = _repo(tmp_path, f"bad-{case}", None)
    if case.startswith("cfg-"):
        body = {
            "cfg-str": '[taskflow]\ndenied_models = "m"\n',
            "cfg-int": "[taskflow]\ndenied_models = [1]\n",
            "cfg-empty": '[taskflow]\ndenied_models = [""]\n',
        }[case]
        (repo / ".ai-governance" / "config.toml").write_text(body, encoding="utf-8")
        return repo, "config.toml"
    tf_body = {
        "tf-str": 'denied_models = "m"\n',
        "tf-table": '[denied_models]\nwrong = ["m"]\n',
        "tf-int": "[taskflow]\ndenied_models = [1]\n",
    }[case]
    (repo / ".ai-governance" / "taskflow.toml").write_text(tf_body, encoding="utf-8")
    return repo, "taskflow.toml"


@pytest.mark.parametrize(
    "case", ["cfg-str", "cfg-int", "cfg-empty", "tf-str", "tf-table", "tf-int"]
)
def test_malformed_repo_denied_models_fails_closed(tmp_path: Path, case: str) -> None:
    repo, filename = _setup_malformed_denied(tmp_path, case)
    cfg = load_config([repo])
    assert cfg.denied_model_problems
    assert cfg.model_error("gpt-6.1-sol") is not None
    assert cfg.model_error("") is not None
    assert any(filename in err for err in cfg.validate())


def test_denied_model_matching_normalizes_case_and_provider_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AI_GOVERNANCE_DENIED_MODELS", "  GPT-6.1-SOL , Anthropic/Claude-Opus-4 ")
    cfg = load_config([])
    assert cfg.denied_models == frozenset({"gpt-6.1-sol", "anthropic/claude-opus-4"})
    assert cfg.model_error("openai/GPT-6.1-SOL") is not None
    assert cfg.model_error("  GPT-6.1-SOL  ") is not None
    assert cfg.model_error("claude-opus-4") is not None
    assert cfg.model_error("Anthropic/CLAUDE-OPUS-4") is not None
    assert cfg.model_error("openai/claude-opus-4") is None
    assert cfg.model_error("gpt-6.1-mini") is None
    assert cfg.model_error("") is None
