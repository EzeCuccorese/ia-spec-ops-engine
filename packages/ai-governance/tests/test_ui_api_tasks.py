"""API tests for Taskflow CRUD, notebook mutations, Brain archiving, and debates."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from ai_governance.brain.store import BrainStore
from ai_governance.taskflow import orca as orca_mod
from ai_governance.taskflow.models import Task
from ai_governance.taskflow.store import TaskStore
from ai_governance.ui import routes_tasks
from ai_governance.ui.app import create_app
from ai_governance.ui.security import SessionSecurity
from fastapi.testclient import TestClient


def _init_git_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    for cmd in (
        ["git", "init"],
        ["git", "config", "user.name", "Test User"],
        ["git", "config", "user.email", "test@example.com"],
    ):
        subprocess.run(cmd, cwd=path, check=True, capture_output=True)
    (path / "README.md").write_text("# Repo\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=path, check=True, capture_output=True)
    return path


@pytest.fixture
def ui_client(tmp_path: Path) -> tuple[TestClient, dict[str, str], TaskStore, BrainStore]:
    tf_store = TaskStore(tmp_path / "tf")
    br_store = BrainStore(tmp_path / "brain")
    sec = SessionSecurity(host="127.0.0.1", port=7474, token="tok-tasks")
    app = create_app(
        sec,
        task_store_factory=lambda: tf_store,
        brain_store_factory=lambda: br_store,
        static_dir=tmp_path / "static",
    )
    return TestClient(app), {"X-UI-Token": "tok-tasks"}, tf_store, br_store


def test_taskflow_create_conflict_and_status_updates(
    ui_client: tuple[TestClient, dict[str, str], TaskStore, BrainStore],
) -> None:
    client, hdr, _, _ = ui_client
    created = client.post(
        "/api/tasks",
        json={"id": "TASK-1", "title": "Build UI", "summary": "Initial", "workflow": "manual"},
        headers=hdr,
    )
    assert created.status_code == 201
    assert (
        client.post("/api/tasks", json={"id": "TASK-1", "title": "Dup"}, headers=hdr).status_code
        == 409
    )
    assert (
        client.post(
            "/api/tasks", json={"id": "TASK-2", "title": "Bad", "workflow": "nope"}, headers=hdr
        ).status_code
        == 400
    )
    assert client.get("/api/tasks").json()["tasks"][0]["id"] == "TASK-1"
    assert client.get("/api/tasks/MISSING").status_code == 404

    patched = client.patch(
        "/api/tasks/TASK-1", json={"status": "closed", "summary": "Done"}, headers=hdr
    )
    assert patched.status_code == 200 and patched.json()["task"]["status"] == "closed"


def test_taskflow_notebook_mutations_and_archive(
    ui_client: tuple[TestClient, dict[str, str], TaskStore, BrainStore],
) -> None:
    client, hdr, tf_store, br_store = ui_client
    tf_store.create(Task(id="TASK-1", title="Build UI", status="closed"))
    assert (
        client.post("/api/tasks/TASK-1/steps", json={"text": "Write API"}, headers=hdr).status_code
        == 201
    )
    assert (
        client.patch("/api/tasks/TASK-1/steps/0", json={"done": True}, headers=hdr).status_code
        == 200
    )
    assert (
        client.patch("/api/tasks/TASK-1/steps/9", json={"done": True}, headers=hdr).status_code
        == 400
    )
    assert (
        client.post(
            "/api/tasks/TASK-1/facts", json={"text": "FastAPI works"}, headers=hdr
        ).status_code
        == 201
    )
    assert (
        client.post(
            "/api/tasks/TASK-1/decisions", json={"text": "Use React", "why": "Graph"}, headers=hdr
        ).status_code
        == 201
    )
    assert (
        client.post(
            "/api/tasks/TASK-1/links",
            json={"title": "Docs", "url": "https://example.com"},
            headers=hdr,
        ).status_code
        == 201
    )

    archived = client.post("/api/tasks/TASK-1/archive", json={}, headers=hdr)
    assert archived.status_code == 200
    assert br_store.get(archived.json()["ref"]).source == "task:TASK-1"


def test_taskflow_debate_open_abort_and_close_via_api(
    ui_client: tuple[TestClient, dict[str, str], TaskStore, BrainStore],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    client, hdr, tf_store, _ = ui_client
    repo = _init_git_repo(tmp_path / "repo")
    tf_store.create(
        Task(id="DEB-1", title="Debate task", repos=[{"path": str(repo), "branch": "main"}])
    )
    monkeypatch.setattr(orca_mod, "require_orca", lambda: ["orca"])

    opened = client.post(
        "/api/tasks/DEB-1/debates/open",
        json={"topic": "Should we use graph hubs?", "agents": ["claude", "codex"]},
        headers=hdr,
    )
    assert opened.status_code == 200
    rounds = opened.json()["rounds"]
    assert len(rounds) == 2

    corrupt = tf_store.task_dir("DEB-1") / "runs" / "999"
    corrupt.mkdir(parents=True)
    (corrupt / "dispatch.json").write_text("{bad", encoding="utf-8")

    detail = client.get("/api/tasks/DEB-1").json()["task"]
    assert detail["debate"]["active"] is True and len(detail["pending_dispatches"]) == 2

    for rnd in rounds:
        aborted = client.post(
            f"/api/tasks/DEB-1/rounds/{rnd['n']}/abort",
            json={"reason": "Testing abort endpoint"},
            headers=hdr,
        )
        assert aborted.status_code == 200 and aborted.json()["record"]["settlement"] == "aborted"
    synth = tmp_path / "synth.md"
    synth.write_text("# Synthesis\nDone.\n", encoding="utf-8")
    monkeypatch.setattr(routes_tasks, "close_debate", lambda *_a, **_k: synth)
    closed = client.post("/api/tasks/DEB-1/debates/close", json={"partial": True}, headers=hdr)
    assert closed.status_code == 200 and "Synthesis" in closed.json()["synthesis"]


def test_taskflow_patch_fields_and_missing_notebook_404s(
    ui_client: tuple[TestClient, dict[str, str], TaskStore, BrainStore],
) -> None:
    client, hdr, tf_store, _ = ui_client
    tf_store.create(Task(id="ERR-1", title="Error test"))
    assert (
        client.patch("/api/tasks/ERR-1", json={"status": "bogus"}, headers=hdr).status_code == 400
    )
    assert (
        client.patch(
            "/api/tasks/ERR-1",
            json={"title": "New", "phase": "review", "blocked": {"owner": "u", "needs": "x"}},
            headers=hdr,
        ).status_code
        == 200
    )
    for path, body in (
        ("/api/tasks/MISSING/steps", {"text": "s"}),
        ("/api/tasks/MISSING/facts", {"text": "f"}),
        ("/api/tasks/MISSING/decisions", {"text": "d", "why": "w"}),
        ("/api/tasks/MISSING/links", {"title": "l", "url": "u"}),
        ("/api/tasks/MISSING/archive", {}),
    ):
        assert client.post(path, json=body, headers=hdr).status_code == 404


def test_taskflow_debate_launch_collect_cross_and_errors(
    ui_client: tuple[TestClient, dict[str, str], TaskStore, BrainStore],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, hdr, tf_store, _ = ui_client
    tf_store.create(Task(id="ERR-1", title="Error test"))

    monkeypatch.setattr(routes_tasks, "launch_reserved_round", lambda *_a: {"dispatch_id": "D-1"})
    assert (
        client.post("/api/tasks/ERR-1/rounds/1/launch", headers=hdr).json()["dispatch_id"] == "D-1"
    )

    class _Settled:
        record = {"n": 1, "settlement": "collected"}
        already = False

    monkeypatch.setattr(routes_tasks, "collect_round", lambda *_a: _Settled())
    assert (
        client.post(
            "/api/tasks/ERR-1/rounds/1/collect", json={"dispatch_id": "D-1"}, headers=hdr
        ).json()["record"]["settlement"]
        == "collected"
    )
    monkeypatch.setattr(
        routes_tasks,
        "cross_debate",
        lambda *_a: (_ for _ in ()).throw(orca_mod.OrcaError("offline")),
    )
    assert client.post("/api/tasks/ERR-1/debates/cross", headers=hdr).status_code == 502
    assert routes_tasks._map_error(RuntimeError("x")).status_code == 500
    assert routes_tasks._map_error(routes_tasks.SecretContentError("secret")).status_code == 422


def test_extract_jira_key_variants() -> None:
    from ai_governance.ui import jira_lookup

    assert jira_lookup.extract_jira_key("proj-123") == "PROJ-123"
    assert jira_lookup.extract_jira_key("https://co.atlassian.net/browse/PROJ-45") == "PROJ-45"
    assert (
        jira_lookup.extract_jira_key(
            "https://co.atlassian.net/jira/software/boards/1?selectedIssue=ABC-9"
        )
        == "ABC-9"
    )
    with pytest.raises(ValueError, match="Provide a Jira"):
        jira_lookup.extract_jira_key("   ")


def test_jira_lookup_and_create_with_jira_url(
    ui_client: tuple[TestClient, dict[str, str], TaskStore, BrainStore],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ai_governance.ui import jira_lookup

    client, hdr, _, _ = ui_client
    assert client.get("/api/tasks/jira-lookup?q=bad").status_code == 400
    assert client.get("/api/tasks/jira-lookup?q=https://example.com/nope").status_code == 400

    monkeypatch.setattr(jira_lookup.jira, "_get_base_url", lambda: "https://co.atlassian.net")
    monkeypatch.setattr(
        jira_lookup.jira,
        "get",
        lambda _p: {
            "fields": {
                "summary": "Fix auth flow",
                "status": {"name": "In Progress"},
                "issuetype": {"name": "Task"},
                "priority": {"name": "High"},
                "parent": {"key": "PROJ-1"},
            }
        },
    )
    res = client.get("/api/tasks/jira-lookup?q=PROJ-123")
    assert (
        res.status_code == 200 and res.json()["url"] == "https://co.atlassian.net/browse/PROJ-123"
    )

    created = client.post(
        "/api/tasks",
        json={
            "id": "PROJ-123",
            "title": "Fix auth flow",
            "jira_url": "https://co.atlassian.net/browse/PROJ-123",
        },
        headers=hdr,
    )
    assert created.status_code == 201
    assert created.json()["task"]["links"][0]["url"] == "https://co.atlassian.net/browse/PROJ-123"


def test_jira_lookup_error_status_mapping(
    ui_client: tuple[TestClient, dict[str, str], TaskStore, BrainStore],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ai_governance.tools.atlassian_common import AtlassianError
    from ai_governance.ui import jira_lookup

    client, _, _, _ = ui_client
    for msg, expected in (
        ("ATLASSIAN_URL not set", 503),
        ("Issue does not exist (404)", 404),
        ("Gateway timeout", 502),
    ):
        monkeypatch.setattr(
            jira_lookup.jira, "get", lambda _p, m=msg: (_ for _ in ()).throw(AtlassianError(m))
        )
        assert client.get("/api/tasks/jira-lookup?q=PROJ-123").status_code == expected
