"""Spec settings: the verify timeout default and its layers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from spec.settings import effective
from spec.verify.engine import load_checks


def _project(tmp_path: Path, config: str = "") -> Path:
    root = tmp_path / "proj"
    (root / ".spec").mkdir(parents=True)
    (root / ".spec" / "verification.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "checks": [
                    {"id": "unit", "command": ["true"]},
                    {"id": "slow", "command": ["true"], "timeout_seconds": 7},
                ],
            }
        )
    )
    if config:
        (root / ".spec" / "config.toml").write_text(config)
    return root


@pytest.fixture(autouse=True)
def _isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SPEC_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.delenv("SPEC_VERIFY_TIMEOUT_SECONDS", raising=False)


def test_default_timeout_is_still_300(tmp_path: Path) -> None:
    checks = load_checks(_project(tmp_path))
    assert [c.timeout_seconds for c in checks] == [300, 7]


def test_repo_file_then_env_change_only_the_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _project(tmp_path, "[verify]\ntimeout_seconds = 60\n")
    assert [c.timeout_seconds for c in load_checks(root)] == [60, 7]
    assert effective(root)["verify.timeout_seconds"].origin == "repo"
    monkeypatch.setenv("SPEC_VERIFY_TIMEOUT_SECONDS", "90")
    assert [c.timeout_seconds for c in load_checks(root)] == [90, 7]
