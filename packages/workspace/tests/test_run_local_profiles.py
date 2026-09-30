"""
Unit tests for workspace_engine.run_local.profiles.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from workspace_engine.run_local import profiles


def test_load_profiles_missing_file(tmp_path: Path) -> None:
    with patch.object(profiles.constants, "PROFILES_FILE", tmp_path / "missing.json"):
        assert profiles.load_profiles() == {}


def test_load_profiles_invalid_json(tmp_path: Path) -> None:
    f = tmp_path / "profiles.json"
    f.write_text("not json", encoding="utf-8")
    with patch.object(profiles.constants, "PROFILES_FILE", f):
        assert profiles.load_profiles() == {}


def test_save_and_load_profiles_roundtrip(tmp_path: Path) -> None:
    f = tmp_path / "profiles.json"
    with (
        patch.object(profiles.constants, "PROFILES_FILE", f),
        patch.object(profiles.constants, "CONFIG_DIR", tmp_path),
    ):
        profiles.save_profiles({"backend": {"services": ["a", "b"]}})
        assert profiles.load_profiles() == {"backend": {"services": ["a", "b"]}}


def test_save_last_configs_and_load(tmp_path: Path) -> None:
    last_file = tmp_path / "last-configs.json"
    configs = [
        {
            "name": "svc-a",
            "path": tmp_path / "svc-a",
            "port": 4000,
            "base_env": "local",
            "db_env": "local",
            "up_mode": "auto",
            "service": {"type": "node", "cmd": ["npm", "start"], "port_var": "PORT"},
        }
    ]
    with (
        patch.object(profiles.constants, "DATA_DIR", tmp_path),
        patch.object(profiles.constants, "LAST_CONFIGS_FILE", last_file),
    ):
        profiles.save_last_configs(configs)
        loaded = profiles.load_last_configs()

    assert len(loaded) == 1
    entry = loaded[0]
    assert entry["name"] == "svc-a"
    assert entry["path"] == Path(str(tmp_path / "svc-a"))
    assert entry["port"] == 4000
    assert entry["service"]["cmd"] == ["npm", "start"]


def test_load_last_configs_missing_file(tmp_path: Path) -> None:
    with patch.object(profiles.constants, "LAST_CONFIGS_FILE", tmp_path / "missing.json"):
        assert profiles.load_last_configs() == []


def test_load_last_configs_invalid_json(tmp_path: Path) -> None:
    f = tmp_path / "last-configs.json"
    f.write_text("{not valid", encoding="utf-8")
    with patch.object(profiles.constants, "LAST_CONFIGS_FILE", f):
        assert profiles.load_last_configs() == []


def test_load_last_configs_assigns_port_when_missing(tmp_path: Path) -> None:
    f = tmp_path / "last-configs.json"
    f.write_text(
        '[{"name": "svc-b", "path": "/tmp/svc-b", "type": "node"}]',
        encoding="utf-8",
    )
    with (
        patch.object(profiles.constants, "LAST_CONFIGS_FILE", f),
        patch.object(profiles, "assign_port", return_value=5555) as mock_assign,
    ):
        loaded = profiles.load_last_configs()
    assert loaded[0]["port"] == 5555
    mock_assign.assert_called_once_with("svc-b")


def test_save_last_configs_handles_write_error(tmp_path: Path) -> None:
    configs = [{"name": "svc-a", "path": tmp_path, "port": 4000}]
    with (
        patch.object(profiles.constants, "DATA_DIR", tmp_path),
        patch.object(profiles.constants, "LAST_CONFIGS_FILE", tmp_path / "nope" / "x.json"),
    ):
        # LAST_CONFIGS_FILE's parent ("nope") isn't created, but DATA_DIR.mkdir
        # doesn't create it either, so write_text should raise OSError, which
        # save_last_configs swallows.
        profiles.save_last_configs(configs)
    assert not (tmp_path / "nope").exists()
