"""
Tests unitarios calibrados para workspace_engine.run_local.discovery.
"""

import json
import tempfile
from pathlib import Path

from workspace_engine.run_local.discovery import (
    _db_vars_from,
    _fmt_bytes,
    _fmt_uptime,
    _is_noise,
    _service_link,
    _service_name_from_subdomain,
    detect_service,
    list_sources,
    scan_repos,
    wire_db_local,
)


def test_format_helpers():
    assert _fmt_uptime(45) == "45s"
    assert _fmt_uptime(125) == "2m"
    assert _fmt_uptime(3665) == "1h1m"

    assert _fmt_bytes(500) == "500K"
    assert _fmt_bytes(1024 * 500) == "500.0M"
    assert _fmt_bytes(1024 * 1024 * 2) == "2.0G"


def test_service_name_and_noise():
    assert _service_name_from_subdomain("auth-service.api.domain.com") == "auth-service"
    assert _service_name_from_subdomain("simple-domain") == "simple-domain"

    assert _is_noise("HOSTNAME") is True
    assert _is_noise("KUBERNETES_SERVICE_PORT") is True
    assert _is_noise("MY_DATABASE_URL") is False


def test_db_vars_from():
    env_vars = {
        "DATABASE_URL": "postgresql://usr:pwd@db-host:5432/mydb",
        "OTHER_VAR": "value",
    }
    extracted = _db_vars_from(env_vars)
    assert "DATABASE_URL" in extracted
    assert "OTHER_VAR" not in extracted


def test_service_link():
    assert _service_link("spring-gradle", 8080) == "http://localhost:8080/swagger-ui/index.html"
    assert _service_link("node", 3000) == "http://localhost:3000/"


def test_detect_service_spring_boot():
    with tempfile.TemporaryDirectory() as tmpdir:
        p = Path(tmpdir)
        main_dir = p / "src" / "main" / "java" / "com" / "example"
        main_dir.mkdir(parents=True)
        (main_dir / "Application.java").write_text(
            "@SpringBootApplication\npublic class Application {}"
        )
        (p / "gradlew").touch()

        svc = detect_service(p)
        assert svc is not None
        assert svc["type"] == "spring-gradle"
        assert svc["cmd"] == ["./gradlew", "bootRun"]


def test_detect_service_node_and_frontend():
    with tempfile.TemporaryDirectory() as tmpdir:
        p = Path(tmpdir)
        pkg = {
            "name": "my-fe-app",
            "scripts": {"dev": "vite", "start": "node server.js"},
            "dependencies": {"vite": "^4.0.0", "react": "^18.0.0"},
        }
        (p / "package.json").write_text(json.dumps(pkg))

        svc = detect_service(p)
        assert svc is not None
        assert svc["type"] == "vite"


def test_detect_service_go():
    with tempfile.TemporaryDirectory() as tmpdir:
        p = Path(tmpdir)
        (p / "go.mod").write_text("module my-go-service\n\ngo 1.21\n")
        (p / "main.go").write_text("package main\n\nfunc main() {}\n")

        svc = detect_service(p)
        assert svc is not None
        assert svc["type"] == "go"
        assert svc["cmd"] == ["go", "run", "."]


def test_wire_db_local_and_pod():
    env_vars = {
        "SPRING_DATASOURCE_URL": "postgresql://prod-db:5432/mydb",
    }
    with tempfile.TemporaryDirectory() as tmpdir:
        p = Path(tmpdir)
        (p / "build.gradle").touch()
        db_cfg = {
            "mongodb": "mongodb://localhost:27018",
            "postgresql": "postgresql://localhost:5432",
        }

        wired_local = wire_db_local(env_vars, db_cfg, p)
        assert isinstance(wired_local, dict)


def test_scan_repos_and_list_sources():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        repos_dir = root / "repositories"
        repos_dir.mkdir()
        repo1 = repos_dir / "service-a"
        repo1.mkdir()
        (repo1 / ".git").mkdir()
        (repo1 / "go.mod").write_text("module service-a\n")
        (repo1 / "main.go").write_text("package main\nfunc main(){}")

        repos = scan_repos(repos_dir)
        assert len(repos) == 1
        assert repos[0]["name"] == "service-a"

        sources = list_sources(root)
        assert len(sources) >= 1
        assert sources[0]["label"] == "repositories"
