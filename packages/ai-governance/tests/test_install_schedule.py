"""The retired daily price refresh LaunchAgent: no longer installed, old copies removed."""

from __future__ import annotations

import plistlib
from pathlib import Path

import pytest
from ai_governance.install import installer, schedule
from ai_governance.install.engine import Ledger


@pytest.fixture(autouse=True)
def _isolated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # Pretend to be macOS so the LaunchAgent code runs on every CI runner.
    monkeypatch.setattr(schedule, "supported", lambda: True)
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    monkeypatch.setenv("AI_GOVERNANCE_STATE_DIR", str(tmp_path / "state"))


def test_plist_runs_prices_update_daily() -> None:
    document = plistlib.loads(schedule.render().encode("utf-8"))
    assert document["Label"] == schedule.LABEL
    assert document["ProgramArguments"][1:] == ["telemetry", "prices", "update"]
    assert document["StartCalendarInterval"] == {"Hour": 6, "Minute": 0}
    assert document["RunAtLoad"] is False


def test_install_no_longer_writes_the_plist() -> None:
    installer.install_user(["claude"])
    assert not schedule.plist_path().exists()


def test_install_removes_a_plist_left_by_an_older_version() -> None:
    from ai_governance.install.engine import Owned, sync

    ledger = installer.global_ledger()
    old = [Owned(installer.SCHEDULE_OWNER, a) for a in schedule.artifacts()]
    ledger.save(sync(old, ledger, agents_in_scope={installer.SCHEDULE_OWNER}), False)
    assert schedule.plist_path().is_file()
    installer.install_user(["claude"])
    assert not schedule.plist_path().exists()


def test_plist_uses_the_executable_next_to_the_interpreter(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    venv_bin = tmp_path / "venv" / "bin"
    venv_bin.mkdir(parents=True)
    (venv_bin / "ai-governance").write_text("#!/bin/sh\n")
    monkeypatch.setattr(schedule.shutil, "which", lambda _name: None)
    monkeypatch.setattr(schedule.sys, "executable", str(venv_bin / "python"))
    document = plistlib.loads(schedule.render().encode("utf-8"))
    assert document["ProgramArguments"][0] == str(venv_bin / "ai-governance")


def test_dry_run_leaves_nothing_behind() -> None:
    installer.install_user(["claude"], dry_run=True)
    assert not schedule.plist_path().exists()


def test_load_retires_the_legacy_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, ...]] = []
    monkeypatch.delenv(schedule.LAUNCH_AGENTS_ENV)
    monkeypatch.setattr(schedule, "_launchctl", lambda *args: calls.append(args))
    legacy = schedule.plist_path(schedule.LEGACY_LABEL)
    legacy.parent.mkdir(parents=True)
    legacy.write_text("old")
    schedule.plist_path().write_text(schedule.render())
    schedule.load()
    assert not legacy.exists()
    assert [c[0] for c in calls] == ["bootout", "bootout", "bootstrap"]
    schedule.unload()
    assert calls[-1][0] == "bootout"


def test_unload_retires_the_legacy_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, ...]] = []
    monkeypatch.delenv(schedule.LAUNCH_AGENTS_ENV)
    monkeypatch.setattr(schedule, "_launchctl", lambda *args: calls.append(args))
    legacy = schedule.plist_path(schedule.LEGACY_LABEL)
    legacy.parent.mkdir(parents=True)
    legacy.write_text("old")
    schedule.plist_path().write_text(schedule.render())  # orphan, not in the ledger
    schedule.unload()
    assert not legacy.exists()
    assert not schedule.plist_path().exists()
    assert [c[1].rsplit("/", 1)[1] for c in calls] == [schedule.LABEL, schedule.LEGACY_LABEL]


def test_installed_agents_ignores_the_schedule_owner() -> None:
    installer.install_user(["claude"])
    assert installer.installed_agents(installer.global_ledger()) == {"claude"}
    assert isinstance(installer.global_ledger(), Ledger)
