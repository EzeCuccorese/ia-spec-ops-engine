from __future__ import annotations

import json
from pathlib import Path

import pytest

from workspace_engine.run_local.constants import (
    find_project_root,
    load_project_config,
)


def test_find_project_root_with_specops(tmp_path: Path) -> None:
    root = tmp_path / "my_project"
    root.mkdir()
    (root / ".specops").mkdir()

    nested = root / "src" / "deep" / "nested"
    nested.mkdir(parents=True)

    assert find_project_root(nested) == root


def test_find_project_root_with_git(tmp_path: Path) -> None:
    root = tmp_path / "git_project"
    root.mkdir()
    (root / ".git").mkdir()

    nested = root / "a" / "b" / "c"
    nested.mkdir(parents=True)

    assert find_project_root(nested) == root


def test_find_project_root_fallback(tmp_path: Path) -> None:
    nested = tmp_path / "standalone" / "dir"
    nested.mkdir(parents=True)

    # When no .specops or .git exists in ancestors, return the resolved path
    assert find_project_root(nested) == nested.resolve()


def test_load_project_config_deep_subdirectory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "my_repo"
    specops_dir = root / ".specops"
    specops_dir.mkdir(parents=True)
    cfg_file = specops_dir / "config.json"
    cfg_file.write_text(
        json.dumps(
            {
                "project_name": "custom-specops-project",
                "domain": "specops.local",
            }
        ),
        encoding="utf-8",
    )

    deep_dir = root / "apps" / "service_a" / "src"
    deep_dir.mkdir(parents=True)

    # 1. Test passing start_dir explicitly
    cfg = load_project_config(start_dir=deep_dir)
    assert cfg["project_name"] == "custom-specops-project"
    assert cfg["domain"] == "specops.local"

    # 2. Test using cwd
    monkeypatch.chdir(deep_dir)
    cfg_cwd = load_project_config()
    assert cfg_cwd["project_name"] == "custom-specops-project"
    assert cfg_cwd["domain"] == "specops.local"


def test_load_project_config_malformed_json(tmp_path: Path) -> None:
    root = tmp_path / "broken_repo"
    specops_dir = root / ".specops"
    specops_dir.mkdir(parents=True)
    cfg_file = specops_dir / "config.json"
    cfg_file.write_text("{ this is malformed json !!! }", encoding="utf-8")

    deep_dir = root / "sub"
    deep_dir.mkdir()

    with pytest.raises(ValueError, match=r"Invalid JSON in config file.*line \d+, column \d+"):
        load_project_config(start_dir=deep_dir)


def test_load_project_config_default_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()

    monkeypatch.chdir(empty_dir)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)

    # Ensure ~/.config/specops/config.json is not picked up by setting HOME to empty_dir
    monkeypatch.setenv("HOME", str(empty_dir))

    cfg = load_project_config(start_dir=empty_dir)
    assert cfg["project_name"] == "generic"
    assert cfg["domain"] == "generic.com"
