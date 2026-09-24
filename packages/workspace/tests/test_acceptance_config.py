"""
test_acceptance_config.py — Acceptance tests for configuration contracts F01–F06.

Contracts from 02-CONTRATOS-DE-TEST.md:
- F01 (test_local_generate_load_roundtrip): Initializing from repo root and loading
      from deep subdirectories loads the root .workspace/config.json without creating
      an unintended nested config.
- F02 (test_global_and_local_precedence): Local config takes precedence over XDG/global config.
- F03 (test_custom_path_roundtrip): Loading with custom path loads exactly that file.
- F04 (test_conflicting_flags_and_bad_config_fail): Conflicting --local and --global,
      or malformed JSON, raises explicit informative errors.
- F05 (test_existing_config_preserved): init_config preserves existing config unless
      explicit overwrite/force is given.
- F06 (test_minimal_and_devops_profiles): Default generation creates a minimal profile
      without clusters/VPN; --enterprise / --devops includes them.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from workspace_engine.config.init_config import (
    generate_default_config,
    init_config,
    resolve_config_target,
    run_config_init,
)
from workspace_engine.run_local.constants import (
    load_project_config,
)


def test_local_generate_load_roundtrip(tmp_path: Path) -> None:
    """F01: Initializing from repo root and loading from deep subdirectories loads the root

    .workspace/config.json without creating an unintended nested config.
    """
    repo_root = tmp_path / "my_project"
    repo_root.mkdir()
    (repo_root / ".git").mkdir()

    # 1. Initialize config at repo root
    init_config(
        is_local=True,
        cwd=repo_root,
        project_name="roundtrip-project",
        domain="roundtrip.dev",
        non_interactive=True,
    )
    root_config_path = repo_root / ".workspace" / "config.json"
    assert root_config_path.exists()

    # 2. Query from deep subdirectory
    deep_dir = repo_root / "services" / "payment" / "src" / "main"
    deep_dir.mkdir(parents=True)

    loaded_cfg = load_project_config(start_dir=deep_dir)
    assert loaded_cfg["project_name"] == "roundtrip-project"
    assert loaded_cfg["domain"] == "roundtrip.dev"

    # Verify no accidental nested .workspace was created anywhere in the tree
    assert not (deep_dir / ".workspace").exists()
    assert not (deep_dir.parent / ".workspace").exists()
    assert not (deep_dir.parent.parent / ".workspace").exists()

    # 3. Running init_config from deep subdirectory resolves to project root
    init_config(
        is_local=True,
        cwd=deep_dir,
        project_name="nested-attempt",
        domain="nested.dev",
        non_interactive=True,
    )
    # Still no nested .workspace in deep_dir
    assert not (deep_dir / ".workspace").exists()


def test_global_and_local_precedence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """F02: Local config takes precedence over XDG/global config."""
    # 1. Establish global configuration via XDG_CONFIG_HOME
    xdg_dir = tmp_path / "global_xdg"
    global_cfg_dir = xdg_dir / "workspace"
    global_cfg_dir.mkdir(parents=True)
    global_cfg_file = global_cfg_dir / "config.json"
    global_cfg_file.write_text(
        json.dumps({"project_name": "global-workspace", "domain": "global.org"}),
        encoding="utf-8",
    )
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg_dir))

    # 2. Establish local configuration in repo
    repo = tmp_path / "local_repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    local_cfg_dir = repo / ".workspace"
    local_cfg_dir.mkdir()
    local_cfg_file = local_cfg_dir / "config.json"
    local_cfg_file.write_text(
        json.dumps({"project_name": "local-workspace", "domain": "local.dev"}),
        encoding="utf-8",
    )

    # When both exist, local config takes precedence
    cfg = load_project_config(start_dir=repo)
    assert cfg["project_name"] == "local-workspace"
    assert cfg["domain"] == "local.dev"

    # When local config is deleted, it falls back to global
    local_cfg_file.unlink()
    cfg_fallback = load_project_config(start_dir=repo)
    assert cfg_fallback["project_name"] == "global-workspace"
    assert cfg_fallback["domain"] == "global.org"


def test_custom_path_roundtrip(tmp_path: Path) -> None:
    """F03: Loading with custom path loads exactly that file."""
    custom_file = tmp_path / "custom_location" / "special-config.json"

    # Initialize via custom_path
    written_path = init_config(
        custom_path=custom_file,
        project_name="custom-location-app",
        domain="custom.io",
        non_interactive=True,
    )
    assert written_path == custom_file
    assert custom_file.exists()

    # Load via custom_path
    loaded = load_project_config(custom_path=custom_file)
    assert loaded["project_name"] == "custom-location-app"
    assert loaded["domain"] == "custom.io"


def test_conflicting_flags_and_bad_config_fail(tmp_path: Path) -> None:
    """F04: Conflicting --local and --global, or malformed JSON, raises explicit informative errors."""
    # 1. Conflicting scope flags in resolution
    with pytest.raises(ValueError, match="Flags --local and --global are mutually exclusive"):
        resolve_config_target(is_local=True, is_global=True)

    with pytest.raises(ValueError, match="Flags --local and --global are mutually exclusive"):
        init_config(is_local=True, is_global=True)

    # CLI mutually exclusive validation
    with pytest.raises(SystemExit):
        run_config_init(["--local", "--global"])

    # 2. Malformed JSON raises explicit informative ValueError
    corrupt_repo = tmp_path / "corrupt_repo"
    corrupt_workspace = corrupt_repo / ".workspace"
    corrupt_workspace.mkdir(parents=True)
    corrupt_cfg = corrupt_workspace / "config.json"
    corrupt_cfg.write_text("{ 'broken': json without quotes ...", encoding="utf-8")

    with pytest.raises(ValueError, match="Invalid JSON in config file"):
        load_project_config(start_dir=corrupt_repo)


def test_existing_config_preserved(tmp_path: Path) -> None:
    """F05: init_config preserves existing config unless explicit overwrite/force is given."""
    repo = tmp_path / "existing_repo"
    repo.mkdir()
    cfg_file = repo / ".workspace" / "config.json"
    cfg_file.parent.mkdir(parents=True)
    cfg_file.write_text(
        json.dumps({"project_name": "precious-project", "domain": "precious.dev"}),
        encoding="utf-8",
    )

    # Call init_config without force in non-interactive mode
    res = init_config(
        is_local=True,
        cwd=repo,
        project_name="new-attempt",
        domain="new.dev",
        non_interactive=True,
        force=False,
    )
    assert res == cfg_file
    preserved = json.loads(cfg_file.read_text(encoding="utf-8"))
    assert preserved["project_name"] == "precious-project"
    assert preserved["domain"] == "precious.dev"

    # Call init_config WITH force
    res_force = init_config(
        is_local=True,
        cwd=repo,
        project_name="overwritten-project",
        domain="overwritten.dev",
        non_interactive=True,
        force=True,
    )
    assert res_force == cfg_file
    overwritten = json.loads(cfg_file.read_text(encoding="utf-8"))
    assert overwritten["project_name"] == "overwritten-project"
    assert overwritten["domain"] == "overwritten.dev"


def test_minimal_and_devops_profiles() -> None:
    """F06: Default generation creates a minimal profile without clusters/VPN; --enterprise / --devops includes them."""
    # 1. Minimal profile
    minimal = generate_default_config("min-proj", "min.dev", enterprise=False)
    assert minimal["project_name"] == "min-proj"
    assert minimal["domain"] == "min.dev"
    assert "environments" not in minimal
    assert "vpn" not in minimal
    assert "artifact_registry_domain" not in minimal

    # 2. Enterprise profile
    enterprise = generate_default_config("ent-proj", "ent.dev", enterprise=True)
    assert enterprise["project_name"] == "ent-proj"
    assert enterprise["domain"] == "ent.dev"
    assert "environments" in enterprise
    assert len(enterprise["environments"]) == 3
    assert "vpn" in enterprise
    assert "artifact_registry_domain" in enterprise
