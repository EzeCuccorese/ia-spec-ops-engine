"""
Unit tests for workspace_engine.run_local.service_wiring: service name normalization,
Spring/Node metadata discovery, service link generation, and env var URL/DB rewiring.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from workspace_engine.run_local import service_wiring as sw


def test_assign_port_is_deterministic_and_in_range() -> None:
    p1 = sw.assign_port("checkout-service")
    p2 = sw.assign_port("checkout-service")
    assert p1 == p2
    assert 8000 <= p1 < 9000


def test_assign_port_differs_for_different_names() -> None:
    assert sw.assign_port("service-a") != sw.assign_port("service-b-xyz")


def test_service_name_from_subdomain_strips_known_prefix() -> None:
    assert sw.service_name_from_subdomain("merchants-orders.example.com") == "orders"


def test_service_name_from_subdomain_no_prefix_match() -> None:
    assert sw.service_name_from_subdomain("unknown-service.example.com") == "unknown-service"


def test_service_name_from_subdomain_strips_env_slug() -> None:
    result = sw.service_name_from_subdomain("prt-bgal-orders-dev.example.com", strip_env=True)
    assert result == "orders"


def test_service_name_from_subdomain_keeps_env_slug_when_disabled() -> None:
    result = sw.service_name_from_subdomain("prt-bgal-orders-dev.example.com", strip_env=False)
    assert result == "orders-dev"


def test_service_name_from_subdomain_env_slug_with_trailing_suffix() -> None:
    result = sw.service_name_from_subdomain("orders-stg-01-canary.example.com", strip_env=True)
    assert result == "orders"


def test_service_name_from_subdomain_no_env_match() -> None:
    assert sw.service_name_from_subdomain("orders.example.com", strip_env=True) == "orders"


def test_spring_context_path_no_resources_dir(tmp_path: Path) -> None:
    assert sw.spring_context_path(tmp_path) == ""


def test_spring_context_path_no_matching_file(tmp_path: Path) -> None:
    res_dir = tmp_path / "src" / "main" / "resources"
    res_dir.mkdir(parents=True)
    assert sw.spring_context_path(tmp_path) == ""


@pytest.mark.parametrize(
    ("filename", "content", "expected"),
    [
        ("application.yml", "server:\n  servlet:\n    context-path: /api\n", "/api"),
        ("application.yml", "context-path: api\n", "/api"),
        ("application.yml", "context-path: /\n", ""),
        ("application.properties", "server.servlet.context-path=/api2\n", "/api2"),
        (
            "application.properties",
            "unrelated.key=value\nserver.context-path=/\nserver.context-path=api3\n",
            "/api3",
        ),
    ],
    ids=[
        "yaml-nested",
        "yaml-adds-slash",
        "yaml-root-skipped",
        "properties",
        "properties-short-key",
    ],
)
def test_spring_context_path(tmp_path: Path, filename: str, content: str, expected: str) -> None:
    res_dir = tmp_path / "src" / "main" / "resources"
    res_dir.mkdir(parents=True)
    (res_dir / filename).write_text(content)
    assert sw.spring_context_path(tmp_path) == expected


def test_spring_context_path_yaml_file_read_error_is_ignored(tmp_path: Path) -> None:
    res_dir = tmp_path / "src" / "main" / "resources"
    res_dir.mkdir(parents=True)
    (res_dir / "application.yml").write_text("context-path: /api\n")
    with patch("pathlib.Path.read_text", side_effect=OSError("boom")):
        assert sw.spring_context_path(tmp_path) == ""


def test_node_health_path_no_js_files(tmp_path: Path) -> None:
    assert sw.node_health_path(tmp_path) is None


def test_node_health_path_skips_node_modules(tmp_path: Path) -> None:
    nm = tmp_path / "node_modules" / "pkg"
    nm.mkdir(parents=True)
    (nm / "index.js").write_text("const health = '/health';")
    assert sw.node_health_path(tmp_path) is None


def test_node_health_path_with_version_and_route(tmp_path: Path) -> None:
    (tmp_path / "app.js").write_text("const versionPath = '/v1';\nconst route = '/health/check';\n")
    # A second file with another health route is processed after health_route is
    # already set, exercising the "already found" (skip) branch. Glob order is
    # forced deterministically since Path.glob does not guarantee ordering.
    other = tmp_path / "other.js"
    other.write_text("const route = '/health/other';\n")
    first = tmp_path / "app.js"
    with patch.object(Path, "glob", return_value=iter([first, other])):
        assert sw.node_health_path(tmp_path) == "/v1/health/check"


def test_node_health_path_route_without_version(tmp_path: Path) -> None:
    (tmp_path / "app.js").write_text("const route = '/health';\n")
    assert sw.node_health_path(tmp_path) == "/health"


def test_node_health_path_read_error_is_ignored(tmp_path: Path) -> None:
    (tmp_path / "app.js").write_text("const route = '/health';\n")
    with patch("pathlib.Path.read_text", side_effect=OSError("boom")):
        assert sw.node_health_path(tmp_path) is None


def test_service_link_spring_with_context_path(tmp_path: Path) -> None:
    res_dir = tmp_path / "src" / "main" / "resources"
    res_dir.mkdir(parents=True)
    (res_dir / "application.yml").write_text("context-path: /api\n")
    label, url = sw.service_link("spring-gradle", 8123, tmp_path)
    assert label == "Swagger"
    assert url == "http://localhost:8123/api/swagger-ui/index.html"


def test_service_link_spring_without_repo_path() -> None:
    label, url = sw.service_link("spring", 8123, None)
    assert label == "Swagger"
    assert url == "http://localhost:8123/swagger-ui/index.html"


def test_service_link_node_with_health_route(tmp_path: Path) -> None:
    (tmp_path / "app.js").write_text("const route = '/health';\n")
    label, url = sw.service_link("node", 8200, tmp_path)
    assert label == "Health"
    assert url == "http://localhost:8200/health"


@pytest.mark.parametrize(
    "with_repo", [True, False], ids=["repo-without-health-route", "no-repo-path"]
)
def test_service_link_node_without_health_route_falls_back(tmp_path: Path, with_repo: bool) -> None:
    label, url = sw.service_link("react", 8300, tmp_path if with_repo else None)
    assert label == "App"
    assert url == "http://localhost:8300/"


def test_service_link_default_app() -> None:
    label, url = sw.service_link("unknown-type", 8400)
    assert label == "App"
    assert url == "http://localhost:8400/"


@pytest.mark.parametrize(
    "env", [{"NAME": "plain-value"}, {"COUNT": 5}], ids=["non-url", "non-string"]
)
def test_wire_urls_skips_values_that_are_not_urls(env: dict) -> None:
    res, wired = sw.wire_urls(env, {})
    assert res == env
    assert wired == {}


def test_wire_urls_replaces_when_port_known() -> None:
    env = {"API_URL": "https://merchants-orders.example.com/v1/items"}
    res, wired = sw.wire_urls(env, {"orders": 8123})
    assert res["API_URL"] == "http://localhost:8123/v1/items"
    assert wired == {"orders": 8123}


def test_wire_urls_leaves_unmatched_service_untouched() -> None:
    env = {"API_URL": "https://merchants-orders.example.com/v1/items"}
    res, wired = sw.wire_urls(env, {})
    assert res["API_URL"] == "https://merchants-orders.example.com/v1/items"
    assert wired == {}


def test_wire_urls_multiple_matches_in_one_value() -> None:
    env = {
        "URLS": ("https://merchants-orders.example.com/a https://merchants-billing.example.com/b")
    }
    res, wired = sw.wire_urls(env, {"orders": 8001, "billing": 8002})
    assert "http://localhost:8001/a" in res["URLS"]
    assert "http://localhost:8002/b" in res["URLS"]
    assert wired == {"orders": 8001, "billing": 8002}


def test_wire_db_urls_mongo_single_uri() -> None:
    res = sw.wire_db_urls({"MONGO": "mongodb://localhost:27017/db"})
    assert res == {"SPRING_DATA_MONGODB_URI": "mongodb://localhost:27017/db"}


def test_wire_db_urls_mongo_srv_uri() -> None:
    res = sw.wire_db_urls({"MONGO": "mongodb+srv://cluster.example.net/db"})
    assert res["SPRING_DATA_MONGODB_URI"] == "mongodb+srv://cluster.example.net/db"


def test_wire_db_urls_mongo_multiple_distinct_uris_excluded() -> None:
    res = sw.wire_db_urls(
        {
            "MONGO_A": "mongodb://host-a/db",
            "MONGO_B": "mongodb://host-b/db",
        }
    )
    assert "SPRING_DATA_MONGODB_URI" not in res


def test_wire_db_urls_postgres_plain_uri_gets_jdbc_prefix() -> None:
    res = sw.wire_db_urls({"PG": "postgres://user:pass@host/db"})
    assert res["SPRING_DATASOURCE_URL"] == "jdbc:postgresql://user:pass@host/db"


def test_wire_db_urls_postgresql_uri_gets_jdbc_prefix() -> None:
    res = sw.wire_db_urls({"PG": "postgresql://user:pass@host/db"})
    assert res["SPRING_DATASOURCE_URL"] == "jdbc:postgresql://user:pass@host/db"


def test_wire_db_urls_jdbc_postgresql_uri_unchanged() -> None:
    uri = "jdbc:postgresql://user:pass@host/db"
    res = sw.wire_db_urls({"PG": uri})
    assert res["SPRING_DATASOURCE_URL"] == uri


def test_wire_db_urls_postgres_multiple_distinct_uris_excluded() -> None:
    res = sw.wire_db_urls(
        {
            "PG_A": "postgres://host-a/db",
            "PG_B": "postgres://host-b/db",
        }
    )
    assert "SPRING_DATASOURCE_URL" not in res


def test_wire_db_urls_skips_non_string_values() -> None:
    res = sw.wire_db_urls({"COUNT": 5})  # type: ignore[dict-item]
    assert res == {}


def test_wire_db_urls_no_matches_returns_empty() -> None:
    assert sw.wire_db_urls({"NAME": "value"}) == {}
