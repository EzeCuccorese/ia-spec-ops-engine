"""Shared fixtures: isolate tests from the agent that may be running them and from the
developer's own Git configuration."""

import os
from pathlib import Path

import pytest
from workspace_engine.common.colors import AGENT_ENV_MARKERS


@pytest.fixture(autouse=True)
def _no_agent_markers(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in AGENT_ENV_MARKERS:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def _isolated_git_config(
    monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory
) -> None:
    """The developer's Git setup must not leak into test repositories: a global
    `core.hooksPath`/`includeIf`, or the `GIT_*` variables Git exports to hooks
    (e.g. `GIT_CONFIG_PARAMETERS` from `git -c ...`, `GIT_DIR` of the pushing repo)."""
    for name in list(os.environ):
        if name.startswith("GIT_"):
            monkeypatch.delenv(name)
    config = Path(tmp_path_factory.getbasetemp()) / "gitconfig"
    if not config.exists():
        config.write_text("[user]\n\tname = Test\n\temail = test@example.com\n")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")


@pytest.fixture(autouse=True)
def _isolated_user_config(
    monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory
) -> None:
    """The developer's own ``~/.config/workspace/config.toml`` (design limits, gate settings)
    and the quality gate's ``QG_*`` variables (set when the suite runs inside ``git push``)
    must not change what a test sees. Each test gets an empty config home; a test that needs
    one sets its own."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path_factory.mktemp("xdg-config")))
    for name in list(os.environ):
        if name.startswith("QG_") or name in ("WORKSPACE_CONFIG_DIR", "AI_GOVERNANCE_CONFIG_DIR"):
            monkeypatch.delenv(name)
