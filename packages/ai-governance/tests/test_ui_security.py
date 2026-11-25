"""Security tests for the visual dashboard: loopback binding, Host/Origin, and CSRF token."""

from __future__ import annotations

from pathlib import Path

import pytest
from ai_governance.brain.store import BrainStore
from ai_governance.taskflow.store import TaskStore
from ai_governance.ui.app import create_app, default_static_dir
from ai_governance.ui.security import (
    SessionSecurity,
    inject_token_meta,
    is_allowed_host,
    validate_loopback_host,
)
from fastapi.testclient import TestClient


def _make_client(tmp_path: Path) -> TestClient:
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text(
        "<html><head></head><body>UI</body></html>", encoding="utf-8"
    )
    sec = SessionSecurity(host="127.0.0.1", port=7474, token="secret-tok")
    app = create_app(
        sec,
        task_store_factory=lambda: TaskStore(tmp_path / "tf"),
        brain_store_factory=lambda: BrainStore(tmp_path / "brain"),
        static_dir=static,
    )
    return TestClient(app)


def test_validate_loopback_host_rejects_public_bind() -> None:
    assert validate_loopback_host("127.0.0.1") == "127.0.0.1"
    assert validate_loopback_host("localhost") == "localhost"
    with pytest.raises(ValueError, match="loopback"):
        validate_loopback_host("0.0.0.0")


def test_is_allowed_host_checks_loopback_and_port() -> None:
    assert is_allowed_host("127.0.0.1:7474", 7474)
    assert is_allowed_host("localhost:7474", 7474)
    assert not is_allowed_host("evil.example.com:7474", 7474)
    assert not is_allowed_host("127.0.0.1:9999", 7474)
    assert not is_allowed_host("", 7474)


def test_spa_injects_token_and_unknown_api_returns_404(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    index = client.get("/")
    assert index.status_code == 200
    assert '<meta name="ai-gov-token" content="secret-tok" />' in index.text
    assert client.get("/api/does-not-exist").status_code == 404


def test_security_middleware_enforces_host_origin_and_csrf_token(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    assert client.get("/api/health", headers={"host": "evil.local:7474"}).status_code == 403
    assert client.post("/api/tasks", json={"id": "T-1", "title": "x"}).status_code == 403
    bad_tok = {"X-UI-Token": "wrong"}
    assert (
        client.post("/api/tasks", json={"id": "T-1", "title": "x"}, headers=bad_tok).status_code
        == 403
    )
    bad_orig = {"X-UI-Token": "secret-tok", "Origin": "https://evil.example"}
    assert (
        client.post("/api/tasks", json={"id": "T-1", "title": "x"}, headers=bad_orig).status_code
        == 403
    )
    ok_hdr = {"X-UI-Token": "secret-tok", "Origin": "http://127.0.0.1:7474"}
    assert (
        client.post("/api/tasks", json={"id": "T-1", "title": "Valid"}, headers=ok_hdr).status_code
        == 201
    )


def test_missing_static_bundle_returns_503_help_page(tmp_path: Path) -> None:
    sec = SessionSecurity(host="127.0.0.1", port=7474, token="tok")
    app = create_app(
        sec,
        task_store_factory=lambda: TaskStore(tmp_path / "tf"),
        brain_store_factory=lambda: BrainStore(tmp_path / "brain"),
        static_dir=tmp_path / "missing-static",
    )
    resp = TestClient(app).get("/")
    assert resp.status_code == 503 and "static assets not built" in resp.text


def test_app_health_workers_assets_and_security_helpers(tmp_path: Path) -> None:
    static = tmp_path / "static"
    assets = static / "assets"
    assets.mkdir(parents=True)
    (assets / "app.js").write_text("console.log('ok');", encoding="utf-8")
    (static / "index.html").write_text("<html><head></head></html>", encoding="utf-8")

    sec = SessionSecurity.generate("127.0.0.1", 7474)
    app = create_app(
        sec,
        task_store_factory=lambda: TaskStore(tmp_path / "tf"),
        brain_store_factory=lambda: BrainStore(tmp_path / "brain"),
        static_dir=static,
    )
    client = TestClient(app)
    assert client.get("/api/health").json()["status"] == "ok"
    assert "workers" in client.get("/api/orca/workers").json()
    assert client.get("/assets/app.js").status_code == 200
    assert default_static_dir().name == "static"
    assert is_allowed_host("[::1]:7474", 7474)
    assert not is_allowed_host("127.0.0.1:notaport", 7474)
    assert inject_token_meta("<html>nohead</html>", "t").startswith('<meta name="ai-gov-token"')
