from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from workspace_engine.config.init_config import (
    generate_default_config,
    init_config,
    resolve_config_target,
    run_config,
    run_config_init,
)


def test_generate_default_config_minimal() -> None:
    cfg = generate_default_config("my-test-proj", "my-domain.io")
    assert cfg["project_name"] == "my-test-proj"
    assert cfg["domain"] == "my-domain.io"
    assert cfg["namespaces"] == ["core", "services", "tools"]
    assert cfg["env_slugs"] == ["dev", "staging", "prod"]
    assert cfg["repositories_dir_env_var"] == "PROJECT_REPOSITORIES_DIR"
    assert cfg["local_envs_dir_name"] == "local-envs"
    assert cfg["workspaces_dir_name"] == "workspaces"
    assert cfg["toolkit_dir_name"] == "project-toolkit"
    assert "url_pattern" in cfg
    assert "environments" not in cfg
    assert "artifact_registry_domain" not in cfg
    assert "vpn" not in cfg


def test_generate_default_config_enterprise() -> None:
    cfg = generate_default_config("my-test-proj", "my-domain.io", enterprise=True)
    assert cfg["project_name"] == "my-test-proj"
    assert cfg["domain"] == "my-domain.io"
    assert "environments" in cfg
    assert len(cfg["environments"]) == 3
    assert cfg["artifact_registry_domain"] == "generic"
    assert "vpn" in cfg


def test_resolve_config_target(tmp_path: Path, monkeypatch) -> None:
    # Local target
    local_target = resolve_config_target(is_local=True, cwd=tmp_path)
    assert local_target == tmp_path / ".workspace" / "config.json"

    # Global target with XDG_CONFIG_HOME
    xdg = tmp_path / "xdg_config"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))
    global_target = resolve_config_target(is_local=False, cwd=tmp_path)
    assert global_target == xdg / "workspace" / "config.json"


def test_resolve_config_target_mutually_exclusive() -> None:
    with pytest.raises(ValueError, match="Flags --local and --global are mutually exclusive."):
        resolve_config_target(is_local=True, is_global=True)


def test_init_config_mutually_exclusive() -> None:
    with pytest.raises(ValueError, match="Flags --local and --global are mutually exclusive."):
        init_config(is_local=True, is_global=True)


def test_run_config_init_mutually_exclusive_cli() -> None:
    with pytest.raises(SystemExit):
        run_config_init(["init", "--local", "--global"])


def test_init_config_local_creation(tmp_path: Path) -> None:
    target = init_config(
        is_local=True,
        project_name="custom-project",
        domain="custom.corp",
        non_interactive=True,
        cwd=tmp_path,
    )
    assert target.exists()
    assert target == tmp_path / ".workspace" / "config.json"

    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["project_name"] == "custom-project"
    assert data["domain"] == "custom.corp"
    assert "vpn" not in data


def test_init_config_enterprise_creation(tmp_path: Path) -> None:
    target = init_config(
        is_local=True,
        enterprise=True,
        project_name="corp-project",
        domain="corp.com",
        non_interactive=True,
        cwd=tmp_path,
    )
    assert target.exists()
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["project_name"] == "corp-project"
    assert "vpn" in data
    assert "environments" in data


def test_init_config_existing_preserves_without_force(tmp_path: Path) -> None:
    target = tmp_path / ".workspace" / "config.json"
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
    target = tmp_path / ".workspace" / "config.json"
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
    exit_code = run_config_init(
        ["init", "--local", "--yes", "--name", "cli-proj", "--domain", "cli.test"]
    )
    assert exit_code == 0

    target = tmp_path / ".workspace" / "config.json"
    assert target.exists()
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["project_name"] == "cli-proj"
    assert data["domain"] == "cli.test"
    assert "vpn" not in data


@pytest.mark.parametrize("flag", ["--enterprise", "--devops"])
def test_run_config_init_enterprise_cli(tmp_path: Path, monkeypatch, flag: str) -> None:
    monkeypatch.chdir(tmp_path)
    exit_code = run_config_init(
        ["init", "--local", "--yes", flag, "--name", "ent-proj", "--domain", "ent.test"]
    )
    assert exit_code == 0

    target = tmp_path / ".workspace" / "config.json"
    assert target.exists()
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["project_name"] == "ent-proj"
    assert "vpn" in data
    assert "environments" in data


def test_resolve_config_target_custom_path(tmp_path: Path) -> None:
    custom = tmp_path / "custom" / "config.json"
    target = resolve_config_target(custom_path=custom)
    assert target == custom


def test_init_config_non_interactive_defaults_name_and_domain(tmp_path: Path) -> None:
    target = init_config(is_local=True, non_interactive=True, cwd=tmp_path)
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["project_name"] == tmp_path.name
    assert data["domain"] == "local.dev"


def test_resolve_config_target_default_global_no_xdg(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    target = resolve_config_target(is_local=False, cwd=tmp_path)
    assert target == tmp_path / ".config" / "workspace" / "config.json"


def test_init_config_interactive_overwrite_declined(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / ".workspace" / "config.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"project_name": "original"}), encoding="utf-8")

    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    with patch("builtins.input", return_value="n"):
        res = init_config(is_local=True, force=False, cwd=tmp_path)
    assert res == target
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["project_name"] == "original"


def test_init_config_interactive_overwrite_confirmed(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / ".workspace" / "config.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"project_name": "original"}), encoding="utf-8")

    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    with patch("builtins.input", side_effect=["y", "new-name", "new.domain"]):
        res = init_config(is_local=True, force=False, cwd=tmp_path)
    assert res == target
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["project_name"] == "new-name"
    assert data["domain"] == "new.domain"


def test_init_config_interactive_project_name_prompt_uses_default(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    with patch("builtins.input", side_effect=["", "custom.domain"]):
        res = init_config(is_local=True, cwd=tmp_path)
    data = json.loads(res.read_text(encoding="utf-8"))
    assert data["project_name"] == tmp_path.name
    assert data["domain"] == "custom.domain"


def test_init_config_interactive_domain_prompt_uses_default(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    with patch("builtins.input", side_effect=["my-proj", ""]):
        res = init_config(is_local=True, cwd=tmp_path)
    data = json.loads(res.read_text(encoding="utf-8"))
    assert data["project_name"] == "my-proj"
    assert data["domain"] == "local.dev"


def test_run_config_unknown_subcommand() -> None:
    import argparse

    args = argparse.Namespace(config_command="bogus")
    assert run_config(args) == 1


def test_run_config_error_path(tmp_path: Path, monkeypatch) -> None:
    import argparse

    args = argparse.Namespace(
        config_command="init",
        local=True,
        is_global=False,
        path=None,
        name="proj",
        domain="dom",
        force=False,
        non_interactive=True,
        enterprise=False,
    )
    monkeypatch.chdir(tmp_path)
    with patch(
        "workspace_engine.config.init_config.init_config",
        side_effect=ValueError("bad config"),
    ):
        assert run_config(args) == 1
