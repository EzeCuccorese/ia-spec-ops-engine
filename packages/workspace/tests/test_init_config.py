from __future__ import annotations

import json
from pathlib import Path

from workspace_engine.config.init_config import (
    generate_default_config,
    init_config,
    resolve_config_target,
    run_config_init,
)


def test_generate_default_config() -> None:
    cfg = generate_default_config("my-test-proj", "my-domain.io")
    assert cfg["project_name"] == "my-test-proj"
    assert cfg["domain"] == "my-domain.io"
    assert "environments" in cfg
    assert len(cfg["environments"]) == 3
    assert "vpn" in cfg


def test_resolve_config_target(tmp_path: Path, monkeypatch) -> None:
    # Local target
    local_target = resolve_config_target(is_local=True, cwd=tmp_path)
    assert local_target == tmp_path / ".specops" / "config.json"

    # Global target with XDG_CONFIG_HOME
    xdg = tmp_path / "xdg_config"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))
    global_target = resolve_config_target(is_local=False, cwd=tmp_path)
    assert global_target == xdg / "specops" / "config.json"


def test_init_config_local_creation(tmp_path: Path) -> None:
    target = init_config(
        is_local=True,
        project_name="custom-project",
        domain="custom.corp",
        non_interactive=True,
        cwd=tmp_path,
    )
    assert target.exists()
    assert target == tmp_path / ".specops" / "config.json"

    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["project_name"] == "custom-project"
    assert data["domain"] == "custom.corp"


def test_init_config_existing_preserves_without_force(tmp_path: Path) -> None:
    target = tmp_path / ".specops" / "config.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"project_name": "original"}), encoding="utf-8")

    res = init_config(
        is_local=True,
        project_name="new-attempt",
        non_interactive=True,
        force=False,
        cwd=tmp_path,
    )
    assert res == target
    # Should not be overwritten
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["project_name"] == "original"


def test_init_config_force_overwrites(tmp_path: Path) -> None:
    target = tmp_path / ".specops" / "config.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"project_name": "original"}), encoding="utf-8")

    res = init_config(
        is_local=True,
        project_name="overwritten",
        domain="new.domain",
        non_interactive=True,
        force=True,
        cwd=tmp_path,
    )
    assert res == target
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["project_name"] == "overwritten"
    assert data["domain"] == "new.domain"


def test_run_config_init_cli(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    exit_code = run_config_init(["--local", "--yes", "--name", "cli-proj", "--domain", "cli.test"])
    assert exit_code == 0

    target = tmp_path / ".specops" / "config.json"
    assert target.exists()
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["project_name"] == "cli-proj"
    assert data["domain"] == "cli.test"
