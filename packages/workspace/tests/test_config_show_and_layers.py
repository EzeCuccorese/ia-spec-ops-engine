"""``ws config show`` and the user layer of ``[design]``."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest
from workspace_engine.config.init_config import _show
from workspace_engine.design.config import DesignConfig
from workspace_engine.services import git_hooks


@pytest.fixture
def xdg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    base = tmp_path / "xdg"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(base))
    monkeypatch.delenv("WORKSPACE_CONFIG_DIR", raising=False)
    return base


def test_config_show_marks_repo_values_and_defaults(
    xdg: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = tmp_path / "repo"
    (repo / ".workspace").mkdir(parents=True)
    (repo / ".git").mkdir()
    (repo / ".workspace" / "config.json").write_text(json.dumps({"domain": "acme.io"}))
    monkeypatch.chdir(repo)
    assert _show(argparse.Namespace(origin=True, json=True)) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["project.domain"]["origin"] == "repo"
    assert shown["project.domain"]["source"].endswith(".workspace/config.json")
    assert shown["project.project_name"] == {
        "value": "generic",
        "origin": "default",
        "source": "",
    }


def test_design_user_layer_is_overridden_key_by_key_by_the_repo(xdg: Path, tmp_path: Path) -> None:
    (xdg / "workspace").mkdir(parents=True)
    (xdg / "workspace" / "config.toml").write_text(
        "[design]\nmax_args = 7\nmax_nesting = 5\nexclude = ['user/**']\n", encoding="utf-8"
    )
    root = tmp_path / "repo"
    (root / ".ai-governance").mkdir(parents=True)
    initial = DesignConfig.load(root)
    assert initial.max_args == 7
    assert "user/**" in initial.exclude
    (root / ".ai-governance" / "config.toml").write_text(
        "[design]\nmax_args = 2\nexclude = ['repo/**']\n"
    )
    loaded = DesignConfig.load(root)
    assert (loaded.max_args, loaded.max_nesting) == (2, 5)
    # exclude is additive across defaults, user, and repo without duplicates
    assert loaded.exclude[: len(initial.exclude) - 1] == initial.exclude[:-1]
    assert "user/**" in loaded.exclude
    assert "repo/**" in loaded.exclude


def test_global_hook_path_follows_the_shared_xdg_rules(
    xdg: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    assert git_hooks.global_hook_path().parent.parent == xdg / "workspace"
    monkeypatch.setenv("WORKSPACE_CONFIG_DIR", str(tmp_path / "ws"))
    assert git_hooks.global_hook_path().parent.parent == tmp_path / "ws"
