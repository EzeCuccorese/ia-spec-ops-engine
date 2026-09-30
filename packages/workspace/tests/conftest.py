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
