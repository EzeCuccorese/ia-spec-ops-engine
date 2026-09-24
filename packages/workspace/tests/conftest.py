"""Shared fixtures: isolate tests from the agent that may be running them."""

import pytest
from workspace_engine.common.colors import AGENT_ENV_MARKERS


@pytest.fixture(autouse=True)
def _no_agent_markers(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in AGENT_ENV_MARKERS:
        monkeypatch.delenv(name, raising=False)
