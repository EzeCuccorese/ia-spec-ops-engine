"""
Tests unitarios para select_repos, configure_repos, tui_utils y benchmark_display.
"""

import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from workspace_engine.services.tui_utils import (
    strip_ansi,
    pad_colored,
    draw_separator,
)
from workspace_engine.services.configure_repos import (
    RepoConfig,
    pre_validate,
    fetch_branches,
)
from workspace_engine.services.select_repos import (
    load_repos,
    apply_filter,
)
from workspace_engine.run_local.profiles import (
    load_profiles,
    save_profiles,
)


def test_tui_utils_helpers():
    ansi_text = "\033[1;32mHello World\033[0m"
    assert strip_ansi(ansi_text) == "Hello World"
    
    padded = pad_colored("Hello World", 20, ansi_text)
    assert len(strip_ansi(padded)) == 20
    
    sep = draw_separator(20, char="─")
    assert strip_ansi(sep) == "─" * 20


def test_select_repos_load_and_filter():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        repos_root = root / "repos"
        repo1 = repos_root / "auth-service"
        repo2 = repos_root / "payment-gateway"
        repo1.mkdir(parents=True)
        (repo1 / ".git").mkdir()
        repo2.mkdir(parents=True)
        (repo2 / ".git").mkdir()

        repos = load_repos(repos_root)
        assert len(repos) == 2
        assert "auth-service" in repos
        assert "payment-gateway" in repos

        # Filtro de búsqueda
        filtered = apply_filter(repos, "auth")
        assert filtered == ["auth-service"]
        
        filtered_empty = apply_filter(repos, "nonexistent")
        assert filtered_empty == []


def test_configure_repos_pre_validate():
    with tempfile.TemporaryDirectory() as tmpdir:
        p = Path(tmpdir)
        (p / ".git").mkdir()

        cfg = RepoConfig(name="my-repo", mode="new", branch="feature", parent=None)
        repo_paths = {"my-repo": p}
        
        errors = pre_validate([cfg], repo_paths)
        assert isinstance(errors, list)


def test_profiles_load_and_save():
    with tempfile.TemporaryDirectory() as tmpdir:
        profile_file = Path(tmpdir) / "profiles.json"
        config_dir = Path(tmpdir)
        
        with patch("workspace_engine.run_local.constants.PROFILES_FILE", profile_file), \
             patch("workspace_engine.run_local.constants.CONFIG_DIR", config_dir):
            profiles = load_profiles()
            assert isinstance(profiles, dict)
            
            profiles["backend"] = ["auth-service", "payment-service"]
            save_profiles(profiles)
            
            reloaded = load_profiles()
            assert "backend" in reloaded
            assert reloaded["backend"] == ["auth-service", "payment-service"]
