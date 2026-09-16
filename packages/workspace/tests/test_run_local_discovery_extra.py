"""
Additional coverage-focused unit tests for workspace_engine.run_local.discovery,
covering env resolution, kubectl helpers, and env-var wiring paths not exercised
by test_run_local_discovery.py.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

from workspace_engine.run_local import discovery as disc


def test_parse_set_env_sh(tmp_path: Path) -> None:
    f = tmp_path / "set-env-local.sh"
    f.write_text(
        "export FOO='bar'\nexport BAZ=\"qux\"\nexport UNQUOTED=hello\n# comment\nnot an export\n",
        encoding="utf-8",
    )
    env = disc.parse_set_env_sh(f)
    assert env == {"FOO": "bar", "BAZ": "qux", "UNQUOTED": "hello"}


def test_parse_set_env_sh_missing_file(tmp_path: Path) -> None:
    assert disc.parse_set_env_sh(tmp_path / "nope.sh") == {}


def test_find_envs_root_and_global_env_path(tmp_path: Path) -> None:
    (tmp_path / "local-envs").mkdir()
    sub = tmp_path / "workspaces" / "ws1" / "repositories" / "svc"
    sub.mkdir(parents=True)

    root = disc.find_envs_root(sub)
    assert root == tmp_path

    gpath = disc.global_env_path(sub, "svc")
    assert gpath == tmp_path / "local-envs" / "svc.sh"


def test_workspace_env_path(tmp_path: Path) -> None:
    (tmp_path / "local-envs").mkdir()
    repo_path = tmp_path / "workspaces" / "ws1" / "repositories" / "svc"
    repo_path.mkdir(parents=True)

    wpath = disc.workspace_env_path(repo_path, "svc")
    assert wpath == tmp_path / "local-envs" / "ws1" / "svc.sh"


def test_workspace_env_path_none_when_root_is_parent(tmp_path: Path) -> None:
    (tmp_path / "local-envs").mkdir()
    repo_path = tmp_path / "repos" / "svc"
    repo_path.mkdir(parents=True)
    assert disc.workspace_env_path(repo_path, "svc") is None


def test_resolve_local_env_prefers_repo_env(tmp_path: Path) -> None:
    repo_path = tmp_path / "svc"
    repo_path.mkdir()
    (repo_path / "set-env-local.sh").write_text("export X=1", encoding="utf-8")
    result = disc.resolve_local_env(repo_path, "svc")
    assert result == repo_path / "set-env-local.sh"


def test_resolve_local_env_none_found(tmp_path: Path) -> None:
    repo_path = tmp_path / "svc"
    repo_path.mkdir()
    assert disc.resolve_local_env(repo_path, "svc") is None


def test_parse_app_vars_spring(tmp_path: Path) -> None:
    res_dir = tmp_path / "src" / "main" / "resources"
    res_dir.mkdir(parents=True)
    (res_dir / "application.yaml").write_text(
        "server:\n  port: ${SERVER_PORT:8080}\ndb:\n  url: ${DB_URL}\n",
        encoding="utf-8",
    )
    result = disc.parse_app_vars(tmp_path)
    assert result == ["DB_URL", "SERVER_PORT"]


def test_parse_app_vars_node(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    src = tmp_path / "src"
    src.mkdir()
    (src / "index.js").write_text("const x = process.env.MY_VAR;", encoding="utf-8")
    result = disc.parse_app_vars(tmp_path)
    assert result == ["MY_VAR"]


def test_parse_app_vars_no_files(tmp_path: Path) -> None:
    assert disc.parse_app_vars(tmp_path) == []


def test_ensure_config_creates_defaults(tmp_path: Path) -> None:
    with (
        patch.object(disc.constants, "CONFIG_DIR", tmp_path / "config"),
        patch.object(disc.constants, "LOGS_DIR", tmp_path / "logs"),
        patch.object(disc.constants, "PIDS_DIR", tmp_path / "pids"),
        patch.object(disc.constants, "DB_CFG_FILE", tmp_path / "config" / "databases.yml"),
    ):
        cfg = disc._ensure_config()
    assert cfg["mongodb"] == "mongodb://localhost:27018"
    assert cfg["postgresql"] == "postgresql://localhost:5432"
    assert (tmp_path / "config" / "databases.yml").exists()


def test_ensure_config_reads_custom_values(tmp_path: Path) -> None:
    db_file = tmp_path / "databases.yml"
    db_file.parent.mkdir(parents=True, exist_ok=True)
    db_file.write_text(
        'local:\n  mongodb: "mongodb://custom:1"\n  postgresql: "postgresql://custom:2"\n',
        encoding="utf-8",
    )
    with (
        patch.object(disc.constants, "CONFIG_DIR", tmp_path),
        patch.object(disc.constants, "LOGS_DIR", tmp_path / "logs"),
        patch.object(disc.constants, "PIDS_DIR", tmp_path / "pids"),
        patch.object(disc.constants, "DB_CFG_FILE", db_file),
    ):
        cfg = disc._ensure_config()
    assert cfg["mongodb"] == "mongodb://custom:1"
    assert cfg["postgresql"] == "postgresql://custom:2"


def test_read_pkg_missing(tmp_path: Path) -> None:
    assert disc._read_pkg(tmp_path) is None


def test_read_pkg_invalid_json(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text("{not json", encoding="utf-8")
    assert disc._read_pkg(tmp_path) is None


def test_is_fe_framework_next(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text(
        '{"dependencies": {"next": "^14.0.0"}}', encoding="utf-8"
    )
    assert disc._is_fe_framework(tmp_path) == "next"


def test_is_fe_framework_none(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text('{"dependencies": {}}', encoding="utf-8")
    assert disc._is_fe_framework(tmp_path) is None


def test_is_go_service_true_main_go(tmp_path: Path) -> None:
    (tmp_path / "go.mod").write_text("module x\n", encoding="utf-8")
    (tmp_path / "main.go").write_text("package main", encoding="utf-8")
    assert disc._is_go_service(tmp_path) is True


def test_is_go_service_true_cmd_dir(tmp_path: Path) -> None:
    (tmp_path / "go.mod").write_text("module x\n", encoding="utf-8")
    cmd_dir = tmp_path / "cmd" / "server"
    cmd_dir.mkdir(parents=True)
    (cmd_dir / "main.go").write_text("package main", encoding="utf-8")
    assert disc._is_go_service(tmp_path) is True


def test_is_go_service_false_no_gomod(tmp_path: Path) -> None:
    assert disc._is_go_service(tmp_path) is False


def test_go_run_cmd_variants(tmp_path: Path) -> None:
    assert disc._go_run_cmd(tmp_path) == ["go", "run", "."]

    (tmp_path / "cmd" / "api").mkdir(parents=True)
    (tmp_path / "cmd" / "api" / "main.go").write_text("package main", encoding="utf-8")
    assert disc._go_run_cmd(tmp_path) == ["go", "run", "./cmd/api"]


def test_node_start_cmd_dev_and_start(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text('{"scripts": {"dev": "vite"}}', encoding="utf-8")
    assert disc._node_start_cmd(tmp_path) == ["npm", "run", "dev"]

    (tmp_path / "package.json").write_text(
        '{"scripts": {"start": "node index.js"}}', encoding="utf-8"
    )
    assert disc._node_start_cmd(tmp_path) == ["npm", "start"]

    (tmp_path / "package.json").write_text('{"scripts": {}}', encoding="utf-8")
    assert disc._node_start_cmd(tmp_path) is None

    assert disc._node_start_cmd(tmp_path.parent / "does-not-exist") is None


def test_has_spring_boot_app_true(tmp_path: Path) -> None:
    main_dir = tmp_path / "src" / "main" / "java" / "com" / "example"
    main_dir.mkdir(parents=True)
    (main_dir / "MyApplication.java").write_text(
        "@SpringBootApplication\nclass MyApplication {}", encoding="utf-8"
    )
    assert disc._has_spring_boot_app(tmp_path) is True


def test_has_spring_boot_app_false_no_main_dir(tmp_path: Path) -> None:
    assert disc._has_spring_boot_app(tmp_path) is False


def test_detect_service_none(tmp_path: Path) -> None:
    assert disc.detect_service(tmp_path) is None


def test_find_project_root_via_repositories_dir(tmp_path: Path) -> None:
    (tmp_path / "repositories").mkdir()
    sub = tmp_path / "a" / "b"
    sub.mkdir(parents=True)
    assert disc.find_project_root(sub) == tmp_path


def test_find_project_root_none_found(tmp_path: Path) -> None:
    # Nest deep enough that all 6 checked ancestors stay inside our own
    # controlled, empty tmp_path subtree — otherwise sibling directories left
    # behind by other tests in the shared pytest tmp base could coincidentally
    # satisfy the "3+ git dirs" heuristic and make this test flaky.
    deep = tmp_path.joinpath(*("level" + str(i) for i in range(7)))
    deep.mkdir(parents=True)
    assert disc.find_project_root(deep) is None


def test_resolve_repos_dir_with_and_without_subdir(tmp_path: Path) -> None:
    (tmp_path / "repositories").mkdir()
    assert disc.resolve_repos_dir({"path": tmp_path}) == tmp_path / "repositories"

    other = tmp_path / "flat"
    other.mkdir()
    assert disc.resolve_repos_dir({"path": other}) == other


def test_override_urls_from_env() -> None:
    with patch.object(disc.constants, "PROJECT_CONFIG", {"domain": "example.com"}):
        env_vars = {"API_URL": "https://svc.dev.example.com", "OTHER": "x"}
        src_env = {"API_URL": "https://svc.local:8080"}
        result = disc.override_urls_from_env(env_vars, src_env)
    assert result["API_URL"] == "https://svc.local:8080"
    assert result["OTHER"] == "x"


def test_wire_db_pod_mongo_and_pg() -> None:
    env_vars = {
        "SOME_MONGO_URI": "mongodb://host:27017/db",
        "SOME_PG_URL": "postgres://host:5432/db",
    }
    result = disc.wire_db_pod(env_vars)
    assert result["SPRING_DATA_MONGODB_URI"] == "mongodb://host:27017/db"
    assert result["SPRING_DATASOURCE_URL"] == "jdbc:postgresql://host:5432/db"


def test_wire_db_pod_already_set() -> None:
    env_vars = {
        "SPRING_DATA_MONGODB_URI": "mongodb://existing",
        "SPRING_DATASOURCE_URL": "jdbc:postgresql://existing",
    }
    assert disc.wire_db_pod(env_vars) == {}


def test_kubectl_runs_subprocess() -> None:
    fake = subprocess.CompletedProcess(args=[], returncode=0, stdout="ctx1\n", stderr="")
    with patch("subprocess.run", return_value=fake) as mock_run:
        result = disc._kubectl(["get", "pods"])
    assert result.stdout == "ctx1\n"
    called_args = mock_run.call_args[0][0]
    assert called_args[0] == "kubectl"


def test_kubectl_available_caches(monkeypatch) -> None:
    disc._KUBECTL_AVAILABLE = None
    with patch.object(disc.shutil, "which", return_value="/usr/bin/kubectl") as mock_which:
        assert disc._kubectl_available() is True
        assert disc._kubectl_available() is True
    mock_which.assert_called_once()
    disc._KUBECTL_AVAILABLE = None


def test_get_kubectl_contexts_unavailable() -> None:
    disc._KUBECTL_AVAILABLE = False
    disc._kubectl_contexts_cache = None
    assert disc._get_kubectl_contexts() == []
    disc._KUBECTL_AVAILABLE = None
    disc._kubectl_contexts_cache = None


def test_get_kubectl_contexts_available() -> None:
    disc._KUBECTL_AVAILABLE = True
    disc._kubectl_contexts_cache = None
    fake = subprocess.CompletedProcess(
        args=[], returncode=0, stdout="dev-ctx\nprod-ctx\n", stderr=""
    )
    with patch.object(disc, "_kubectl", return_value=fake):
        result = disc._get_kubectl_contexts()
    assert result == ["dev-ctx", "prod-ctx"]
    disc._KUBECTL_AVAILABLE = None
    disc._kubectl_contexts_cache = None


def test_resolve_context() -> None:
    disc._kubectl_contexts_cache = ["dev-ctx", "prod-ctx"]
    assert disc._resolve_context("prod") == "prod-ctx"
    assert disc._resolve_context("dev") == "dev-ctx"
    disc._kubectl_contexts_cache = None


def test_resolve_context_no_match() -> None:
    disc._kubectl_contexts_cache = []
    assert disc._resolve_context("dev") is None
    disc._kubectl_contexts_cache = None


def test_find_pod_kubectl_failure() -> None:
    fake = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="boom")
    with patch.object(disc, "_kubectl", return_value=fake):
        pod, err = disc.find_pod("svc", "dev", "ctx", "ns")
    assert pod is None
    assert err == "boom"


def test_find_pod_found_running() -> None:
    fake = subprocess.CompletedProcess(
        args=[],
        returncode=0,
        stdout="NAME READY STATUS\nsvc-dev-abc123 1/1 Running\n",
        stderr="",
    )
    with patch.object(disc, "_kubectl", return_value=fake):
        pod, err = disc.find_pod("svc", "dev", "ctx", "ns")
    assert pod == "svc-dev-abc123"
    assert err is None


def test_find_pod_found_not_running() -> None:
    fake = subprocess.CompletedProcess(
        args=[],
        returncode=0,
        stdout="NAME READY STATUS\nsvc-dev-abc123 1/1 Pending\n",
        stderr="",
    )
    with patch.object(disc, "_kubectl", return_value=fake):
        pod, err = disc.find_pod("svc", "dev", "ctx", "ns")
    assert pod is None
    assert "not Running" in err


def test_find_pod_not_found() -> None:
    fake = subprocess.CompletedProcess(
        args=[], returncode=0, stdout="NAME READY STATUS\n", stderr=""
    )
    with patch.object(disc, "_kubectl", return_value=fake):
        pod, err = disc.find_pod("svc", "dev", "ctx", "ns")
    assert pod is None
    assert err is None


def test_get_pod_env_failure() -> None:
    fake = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="")
    with patch.object(disc, "_kubectl", return_value=fake):
        assert disc.get_pod_env("pod", "ctx", "ns") == {}


def test_get_pod_env_multiline_value() -> None:
    fake = subprocess.CompletedProcess(
        args=[],
        returncode=0,
        stdout="FOO=bar\nBAZ=line1\nstill part of BAZ\nQUX=qux\n",
        stderr="",
    )
    with patch.object(disc, "_kubectl", return_value=fake):
        env = disc.get_pod_env("pod", "ctx", "ns")
    assert env["FOO"] == "bar"
    assert env["BAZ"] == "line1\nstill part of BAZ"
    assert env["QUX"] == "qux"
