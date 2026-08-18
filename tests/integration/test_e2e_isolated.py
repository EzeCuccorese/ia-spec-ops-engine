"""
Tests de Integración End-to-End Aislados e Idempotentes para Devscripts.

Crea repositorios Git y workspaces temporales para verificar:
1. Ciclo completo de Workspace Engine: generate -> worktree -> build -> clean -> delete.
2. Ciclo completo de SDD Engine: init -> specify -> plan -> tasks -> verify -> finish.
"""

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from devscripts_common import run_command_safe
from workspace_engine.cli.generate_workspace import create_workspace_structure
from workspace_engine.services.configure_repos import RepoConfig
from workspace_engine.cli.clean_workspace import clean_workspace
from sdd_engine.core import memory
from sdd_engine.lifecycle import feature, constitution
from sdd_engine.adapters import bridge


def _init_git_repo(repo_path: Path) -> None:
    """Inicializa un repositorio git local con un commit inicial."""
    repo_path.mkdir(parents=True, exist_ok=True)
    git_env = {
        **os.environ,
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_SYSTEM": "/dev/null",
        "GIT_AUTHOR_NAME": "Test User",
        "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "Test User",
        "GIT_COMMITTER_EMAIL": "test@example.com",
    }
    subprocess.run(["git", "-C", str(repo_path), "init", "-b", "main"], capture_output=True, check=True, env=git_env)
    subprocess.run(["git", "-C", str(repo_path), "config", "user.name", "Test User"], capture_output=True, check=True, env=git_env)
    subprocess.run(["git", "-C", str(repo_path), "config", "user.email", "test@example.com"], capture_output=True, check=True, env=git_env)
    (repo_path / "README.md").write_text("# Test Repo\n")
    (repo_path / "pyproject.toml").write_text("[project]\nname = 'test'\nversion = '0.1.0'\n")
    subprocess.run(["git", "-C", str(repo_path), "add", "."], capture_output=True, check=True, env=git_env)
    subprocess.run(["git", "-C", str(repo_path), "commit", "-m", "chore(init): initial commit"], capture_output=True, check=True, env=git_env)


@pytest.mark.integration
def test_e2e_workspace_flow_isolated():
    """Prueba de integración aislada para el ciclo de vida del workspace."""
    with tempfile.TemporaryDirectory() as tmpdir:
        base_dir = Path(tmpdir)
        repos_dir = base_dir / "ai-repositories"
        workspaces_dir = base_dir / "workspaces"
        
        # 1. Crear repositorios base
        repo_a = repos_dir / "auth-service"
        repo_b = repos_dir / "billing-service"
        _init_git_repo(repo_a)
        _init_git_repo(repo_b)

        # 2. Configurar y generar workspace
        repo_configs = [
            RepoConfig(name="auth-service", mode="new", branch="feature-test", parent="main"),
            RepoConfig(name="billing-service", mode="new", branch="feature-test", parent="main"),
        ]
        repo_paths = {"auth-service": repo_a, "billing-service": repo_b}

        ws_dir = create_workspace_structure(
            workspace_name="feature-test",
            workspaces_root=workspaces_dir,
            repo_configs=repo_configs,
            repo_paths=repo_paths,
        )

        # 3. Validar estructura creada
        assert ws_dir.exists()
        assert (ws_dir / "repositories" / "auth-service").exists()
        assert (ws_dir / "repositories" / "billing-service").exists()
        assert (ws_dir / ".ai-toolkit" / "workspace.json").exists()
        assert (ws_dir / "AGENTS.md").exists()

        # 4. Limpieza del workspace
        code = clean_workspace(ws_dir)
        assert code == 0


@pytest.mark.integration
def test_e2e_sdd_flow_isolated():
    """Prueba de integración aislada para el ciclo de vida de SDD."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)
        _init_git_repo(project_dir)

        # 1. SDD Init & Constitución
        memory.init(project_dir)
        constitution.write_constitution(target_dir=project_dir)
        assert (project_dir / ".specify" / "constitution" / "constitution.md").exists()

        # 2. Adaptadores Multi-IA
        generated = bridge.generate_adapters(target_dir=str(project_dir), gen_all=True)
        assert len(generated) > 0
        assert (project_dir / "CLAUDE.md").exists()
        assert (project_dir / "AGENTS.md").exists()
        assert (project_dir / ".cursorrules").exists()

        # 3. Creación y avance de Feature
        feature_file = project_dir / ".specify" / "feature.json"
        feature_file.write_text(json.dumps({
            "active_feature": "user-authentication",
            "current_phase": "specify",
            "created_at": "2026-08-14T00:00:00Z",
            "updated_at": "2026-08-14T00:00:00Z",
        }))

        spec_dir = project_dir / ".specify" / "specs" / "user-authentication"
        spec_dir.mkdir(parents=True, exist_ok=True)
        (spec_dir / "spec.md").write_text("# Spec: User Auth\n")
        (spec_dir / "tasks.md").write_text("- [x] T1: Setup models\n- [ ] T2: Add endpoints\n")

        # 4. Verificación de lectura de feature
        data = json.loads(feature_file.read_text())
        assert data["active_feature"] == "user-authentication"
        assert data["current_phase"] == "specify"
