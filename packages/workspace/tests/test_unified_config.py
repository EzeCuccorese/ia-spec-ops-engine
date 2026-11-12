"""Focused tests for unified config files and the 3 configuration layers."""

import subprocess
from pathlib import Path

import pytest
from workspace_engine.config.init_config import _show
from workspace_engine.design.config import DesignConfig
from workspace_engine.services.gate_config import shell_assignments
from workspace_engine.settings import (
    effective,
    personal_repo_config_path,
    stable_repo_name,
)


def test_three_layers_precedence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Precedence: user global < in-repo < personal per-repo."""
    user_config_dir = tmp_path / "user_config" / "workspace"
    user_config_dir.mkdir(parents=True)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "user_config"))

    repo_dir = tmp_path / "my-project"
    repo_dir.mkdir()
    subprocess.run(["git", "init"], cwd=repo_dir, check=True, capture_output=True)

    # 1. User config sets default
    (user_config_dir / "config.toml").write_text(
        '[gate]\nstrict = false\nscope = "staged"\noutput = "errors"\n'
    )

    settings = effective(repo_dir)
    assert settings["gate.scope"].value == "staged"
    assert settings["gate.scope"].origin == "user"

    # 2. In-repo config overrides user
    repo_cfg = repo_dir / ".workspace" / "config.toml"
    repo_cfg.parent.mkdir()
    repo_cfg.write_text('[gate]\nscope = "all"\n')

    settings = effective(repo_dir)
    assert settings["gate.scope"].value == "all"
    assert settings["gate.scope"].origin == "repo"

    # 3. Personal per-repo overrides in-repo
    personal_dir = user_config_dir / "repos"
    personal_dir.mkdir()
    (personal_dir / f"{repo_dir.name}.toml").write_text(
        '[gate]\nscope = "staged"\noutput = "summary"\n'
    )

    settings = effective(repo_dir)
    assert settings["gate.scope"].value == "staged"  # from personal
    assert settings["gate.output"].value == "summary"  # from personal
    assert str(personal_dir) in settings["gate.scope"].source
    assert str(personal_dir) in settings["gate.output"].source


def test_stable_repo_name_across_worktrees(tmp_path: Path) -> None:
    """Repo name is canonical across main checkout and git worktrees."""
    main_repo = tmp_path / "canonical-repo"
    main_repo.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=main_repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=main_repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=main_repo, check=True)
    (main_repo / "README.md").write_text("hello\n")
    subprocess.run(["git", "add", "."], cwd=main_repo, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=main_repo, check=True)

    # Create worktree
    worktree_dir = tmp_path / "wt-feature-branch"
    subprocess.run(
        ["git", "worktree", "add", "-b", "feat", str(worktree_dir)],
        cwd=main_repo,
        check=True,
        capture_output=True,
    )

    assert stable_repo_name(main_repo) == "canonical-repo"
    assert stable_repo_name(worktree_dir) == "canonical-repo"

    personal_main = personal_repo_config_path(main_repo)
    personal_wt = personal_repo_config_path(worktree_dir)
    assert personal_main == personal_wt
    assert personal_main.name == "canonical-repo.toml"


def test_ai_governance_config_ignored(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """.ai-governance/config.toml is completely ignored."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "user_config"))
    repo_dir = tmp_path / "clean-repo"
    repo_dir.mkdir()
    subprocess.run(["git", "init"], cwd=repo_dir, check=True, capture_output=True)

    # Put a fake setting in legacy .ai-governance/config.toml
    legacy_dir = repo_dir / ".ai-governance"
    legacy_dir.mkdir()
    (legacy_dir / "config.toml").write_text(
        '[gate]\nscope = "legacy_scope"\n[design]\nprofiles = ["legacy_profile"]\n'
    )

    settings = effective(repo_dir)
    assert settings["gate.scope"].value == "all"  # default, not legacy_scope
    assert "legacy_scope" not in str(settings["gate.scope"].value)
    assert settings["gate.scope"].origin != "repo"

    design_cfg = DesignConfig.load(repo_dir)
    assert "legacy_profile" not in design_cfg.profiles


def test_gate_scope_and_output_file_and_env_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """gate.scope and gate.output in file are reflected in shell_assignments and overridden by env."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "user_config"))
    repo_dir = tmp_path / "test-repo"
    repo_dir.mkdir()
    subprocess.run(["git", "init"], cwd=repo_dir, check=True, capture_output=True)

    repo_cfg = repo_dir / ".workspace" / "config.toml"
    repo_cfg.parent.mkdir()
    repo_cfg.write_text('[gate]\nscope = "staged"\noutput = "summary"\n')

    assignments = shell_assignments(repo_dir)
    assert "QG_SCOPE=staged" in assignments
    assert "QG_OUTPUT=summary" in assignments

    # Env vars take precedence in effective settings and won't be emitted by shell_assignments (env already has them)
    monkeypatch.setenv("QG_SCOPE", "all")
    monkeypatch.setenv("QG_OUTPUT", "errors")
    assignments_with_env = shell_assignments(repo_dir)
    assert "QG_SCOPE=" not in assignments_with_env
    assert "QG_OUTPUT=" not in assignments_with_env


def test_design_profiles_and_additive_exclude(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Profiles and additive exclude across user, repo, and personal layers."""
    user_config_dir = tmp_path / "user_config" / "workspace"
    user_config_dir.mkdir(parents=True)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "user_config"))

    repo_dir = tmp_path / "test-repo"
    repo_dir.mkdir()
    subprocess.run(["git", "init"], cwd=repo_dir, check=True, capture_output=True)

    # 1. User config: exclude doc/
    (user_config_dir / "config.toml").write_text('[design]\nexclude = ["doc/**"]\n')

    # 2. Repo config: profiles + exclude tests/
    repo_cfg = repo_dir / ".workspace" / "config.toml"
    repo_cfg.parent.mkdir()
    repo_cfg.write_text('[design]\nprofiles = ["architecture"]\nexclude = ["custom_tests/**"]\n')

    # 3. Personal config: profiles override or append + exclude local/
    personal_dir = user_config_dir / "repos"
    personal_dir.mkdir()
    (personal_dir / "test-repo.toml").write_text(
        '[design]\nprofiles = ["architecture", "web"]\nexclude = ["my_scratch/**"]\n'
    )

    design_cfg = DesignConfig.load(repo_dir)
    assert "architecture" in design_cfg.profiles
    assert "web" in design_cfg.profiles
    # Check that exclude is additive across all 3 layers plus default excludes
    assert "doc/**" in design_cfg.exclude
    assert "custom_tests/**" in design_cfg.exclude
    assert "my_scratch/**" in design_cfg.exclude
    # Standard defaults still present
    assert "**/dist/**" in design_cfg.exclude


def test_ws_config_show_human_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """ws config show human output displays found config files and merged settings."""
    user_config_dir = tmp_path / "user_config" / "workspace"
    user_config_dir.mkdir(parents=True)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "user_config"))

    repo_dir = tmp_path / "show-repo"
    repo_dir.mkdir()
    subprocess.run(["git", "init"], cwd=repo_dir, check=True, capture_output=True)

    user_cfg = user_config_dir / "config.toml"
    user_cfg.write_text('[gate]\nscope = "staged"\n')

    repo_cfg = repo_dir / ".workspace" / "config.toml"
    repo_cfg.parent.mkdir()
    repo_cfg.write_text('[gate]\noutput = "errors"\n')

    personal_dir = user_config_dir / "repos"
    personal_dir.mkdir()
    personal_cfg = personal_dir / "show-repo.toml"
    personal_cfg.write_text("[gate]\ntimeout_seconds = 42\n")

    import argparse

    monkeypatch.chdir(repo_dir)
    ret = _show(argparse.Namespace(origin=True, json=False))
    assert ret == 0

    out = capsys.readouterr().out
    assert "Config files found (3):" in out
    assert str(user_cfg) in out
    assert str(repo_cfg) in out
    assert str(personal_cfg) in out
    assert 'gate.scope = "staged"' in out
    assert 'gate.output = "errors"' in out
    assert "gate.timeout_seconds = 42" in out
