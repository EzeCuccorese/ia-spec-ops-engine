import tempfile
from pathlib import Path
import pytest

from workspace_engine.run_local.service_wiring import (
    assign_port,
    service_name_from_subdomain,
    spring_context_path,
    wire_urls,
    wire_db_urls,
)
from workspace_engine.run_local.profiles import load_profiles, save_profiles


def test_assign_port():
    port1 = assign_port("auth-service")
    port2 = assign_port("auth-service")
    port3 = assign_port("payment-service")
    assert 8000 <= port1 <= 8999
    assert port1 == port2
    assert isinstance(port3, int)


def test_service_name_from_subdomain():
    assert service_name_from_subdomain("merchants-auth-service-faf-01.dev.generic.com") == "auth-service"
    assert service_name_from_subdomain("core-payment-service.prod.generic.com") == "payment-service"


def test_wire_urls():
    env = {
        "AUTH_URL": "http://merchants-auth-service-faf.dev.generic.com/api/v1",
        "OTHER_VAR": "constant_value"
    }
    running = {"auth-service": 8085}
    wired, updated = wire_urls(env, running)
    assert wired["AUTH_URL"] == "http://localhost:8085/api/v1"
    assert wired["OTHER_VAR"] == "constant_value"
    assert updated["auth-service"] == 8085


def test_wire_db_urls():
    env = {
        "DB_URI": "mongodb://localhost:27017/mydb",
        "PG_URI": "postgres://user:pass@localhost:5432/pgdb"
    }
    wired = wire_db_urls(env)
    assert wired.get("SPRING_DATA_MONGODB_URI") == "mongodb://localhost:27017/mydb"
    assert wired.get("SPRING_DATASOURCE_URL") == "jdbc:postgresql://user:pass@localhost:5432/pgdb"


def test_spring_context_path():
    with tempfile.TemporaryDirectory() as tmpdir:
        res = Path(tmpdir) / "src" / "main" / "resources"
        res.mkdir(parents=True)
        (res / "application.yml").write_text("server:\n  servlet:\n    context-path: /my-api\n")
        assert spring_context_path(Path(tmpdir)) == "/my-api"
