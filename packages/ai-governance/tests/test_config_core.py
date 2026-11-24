"""Layered configuration: default < user < repo < env < flag, with origins."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from ai_governance import settings
from ai_governance._config_core import (
    ConfigError,
    Layers,
    Setting,
    is_agent_mode,
    load_layers,
    render_show,
    resolve,
    xdg_dir,
)
from ai_governance.config_cli import main as config_main

KEY = Setting("demo.limit", 10, "DEMO_LIMIT")


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    cfg = tmp_path / "cfg"
    monkeypatch.setenv("AI_GOVERNANCE_CONFIG_DIR", str(cfg))
    monkeypatch.delenv("DEMO_LIMIT", raising=False)
    return cfg


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_precedence_default_user_repo_env_flag(home: Path, tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    layers = lambda: load_layers("ai-governance", repo)  # noqa: E731
    assert resolve([KEY], layers())["demo.limit"].origin == "default"

    _write(home / "config.toml", "[demo]\nlimit = 20\n")
    found = resolve([KEY], layers())["demo.limit"]
    assert (found.value, found.origin) == (20, "user")
    assert found.source == str(home / "config.toml")

    _write(repo / ".ai-governance" / "config.toml", "[demo]\nlimit = 30\n")
    found = resolve([KEY], layers())["demo.limit"]
    assert (found.value, found.origin) == (30, "repo")

    found = resolve([KEY], layers(), environ={"DEMO_LIMIT": "40"})["demo.limit"]
    assert (found.value, found.origin, found.source) == (40, "env", "DEMO_LIMIT")

    found = resolve([KEY], layers(), flags={"demo.limit": 50}, environ={"DEMO_LIMIT": "40"})
    assert (found["demo.limit"].value, found["demo.limit"].origin) == (50, "flag")


def test_legacy_json_is_still_read_and_toml_wins(home: Path) -> None:
    _write(home / "config.json", json.dumps({"demo": {"limit": 7}}))
    layers = load_layers("ai-governance", None)
    assert resolve([KEY], layers)["demo.limit"].value == 7
    _write(home / "config.toml", "[demo]\nlimit = 8\n")
    assert resolve([KEY], load_layers("ai-governance", None))["demo.limit"].value == 8


def test_invalid_file_and_value_raise_config_error(home: Path) -> None:
    _write(home / "config.toml", "[demo\n")
    with pytest.raises(ConfigError, match="config.toml"):
        load_layers("ai-governance", None)
    with pytest.raises(ConfigError, match="demo.limit"):
        resolve([KEY], Layers({}, {}, {}, {}), environ={"DEMO_LIMIT": "many"})


def test_xdg_dir_precedence(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("DEMO_APP_STATE_DIR", raising=False)
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))
    assert xdg_dir("state", "demo-app") == tmp_path / "xdg" / "demo-app"
    monkeypatch.setenv("DEMO_APP_STATE_DIR", str(tmp_path / "explicit"))
    assert xdg_dir("state", "demo-app") == tmp_path / "explicit"


def test_xdg_dir_uses_checkout_config_when_present_and_env_unset(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from ai_governance import _config_core

    checkout_cfg = tmp_path / "checkout" / "config" / "demo-app"
    checkout_cfg.mkdir(parents=True)
    monkeypatch.delenv("DEMO_APP_CONFIG_DIR", raising=False)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setattr(_config_core, "_checkout_config_dir", lambda app: checkout_cfg)

    assert xdg_dir("config", "demo-app") == checkout_cfg
    assert xdg_dir("state", "demo-app") == Path.home() / ".local" / "state" / "demo-app"

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    assert xdg_dir("config", "demo-app") == tmp_path / "xdg" / "demo-app"

    monkeypatch.setenv("DEMO_APP_CONFIG_DIR", str(tmp_path / "explicit"))
    assert xdg_dir("config", "demo-app") == tmp_path / "explicit"

    monkeypatch.delenv("DEMO_APP_CONFIG_DIR", raising=False)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setattr(_config_core, "_checkout_config_dir", lambda app: None)
    assert xdg_dir("config", "demo-app") == Path.home() / ".config" / "demo-app"


def test_agent_mode_forced_and_detected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CLAUDECODE", raising=False)
    assert not is_agent_mode("ai-governance")
    monkeypatch.setenv("CLAUDECODE", "1")
    assert is_agent_mode("ai-governance")
    monkeypatch.setenv("AI_GOVERNANCE_AGENT", "0")
    assert not is_agent_mode("ai-governance")


def test_render_show_text_and_json(home: Path) -> None:
    _write(home / "config.toml", "[demo]\nlimit = 20\n")
    values = resolve([KEY], load_layers("ai-governance", None))
    assert render_show(values, origin=True) == f"demo.limit = 20  # user ({home / 'config.toml'})"
    assert json.loads(render_show(values, as_json=True)) == {"demo.limit": 20}


def test_config_show_reports_the_origin_of_each_value(
    home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    _write(home / "config.toml", "[frugality]\nbudget_chars = 100\n")
    _write(repo / ".ai-governance" / "config.toml", "[frugality]\nthreshold_chars = 9000\n")
    monkeypatch.chdir(repo)
    monkeypatch.setenv("AI_GOVERNANCE_CHECK_TIMEOUT_SECONDS", "60")
    assert config_main(["show", "--origin", "--json"]) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["frugality.budget_chars"]["origin"] == "user"
    assert shown["frugality.threshold_chars"]["origin"] == "repo"
    assert shown["frugality.threshold_chars"]["value"] == 9000
    assert shown["taskflow.timeout_seconds"] == {
        "value": 60,
        "origin": "env",
        "source": "AI_GOVERNANCE_CHECK_TIMEOUT_SECONDS",
    }
    assert shown["atlassian.timeout_seconds"]["origin"] == "default"
    assert shown["deploy_approvals.production"] == {
        "value": "never",
        "origin": "default",
        "source": "",
    }


def test_frugal_json_and_taskflow_toml_feed_the_same_layers(
    home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AI_GOVERNANCE_STATE_DIR", str(tmp_path / "state"))
    from ai_governance.frugality import cli as frugal
    from ai_governance.taskflow.config import load_config

    _write(home / "frugal.json", json.dumps({"threshold_chars": 123}))
    assert frugal.load_config() == {**frugal.DEFAULT_CONFIG, "threshold_chars": 123}
    _write(home / "config.toml", "[frugality]\nthreshold_chars = 456\n")
    assert frugal.load_config()["threshold_chars"] == 456

    repo = tmp_path / "repo"
    _write(home / "taskflow.toml", "timeout_seconds = 100\n")
    assert load_config([repo]).timeout_seconds == 100
    _write(repo / ".ai-governance" / "taskflow.toml", 'denied_models = ["exp-model"]\n')
    assert "exp-model" in load_config([repo]).denied_models
    _write(repo / ".ai-governance" / "config.toml", "[taskflow]\ntimeout_seconds = 200\n")
    assert settings.get("taskflow.timeout_seconds", repo) == 200


@pytest.mark.parametrize(
    ("raw", "like"),
    [
        (True, 10),
        (False, 10),
        (True, 1.5),
        (False, 1.5),
        (float("nan"), 1.5),
        (float("inf"), 1.5),
        (float("-inf"), 1.5),
        ("nan", 1.5),
        ("Infinity", 1.5),
        ("-inf", 1.5),
        ("1e309", 1.5),
    ],
)
def test_coerce_rejects_booleans_for_numbers_and_non_finite_floats(
    raw: object, like: object
) -> None:
    from ai_governance._config_core import coerce

    with pytest.raises(ConfigError, match="demo.num"):
        coerce(raw, like, "demo.num")
    assert coerce(42, 10, "demo.num") == 42
    assert coerce("12.5", 1.5, "demo.num") == 12.5
