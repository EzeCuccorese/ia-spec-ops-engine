"""Shared fixtures: isolate tests from the agent that may be running them."""

import pytest
from ai_governance.output import AGENT_ENV_MARKERS


@pytest.fixture(autouse=True)
def _no_agent_markers(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in AGENT_ENV_MARKERS:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def _no_corporate_packs(
    monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory
) -> None:
    """The developer's own company packs (gitignored, next to the packages) must not leak in."""
    monkeypatch.setenv("AI_GOVERNANCE_CORPORATE_DIR", str(tmp_path_factory.mktemp("no-packs")))


@pytest.fixture(autouse=True)
def _no_real_shell(
    monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory
) -> None:
    """Completions go to a temp data dir and never follow the developer's ZDOTDIR."""
    monkeypatch.delenv("ZDOTDIR", raising=False)
    monkeypatch.setenv("AI_GOVERNANCE_DATA_DIR", str(tmp_path_factory.mktemp("data")))
