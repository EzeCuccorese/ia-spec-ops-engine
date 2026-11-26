"""API tests for Second Brain CRUD, secret guard, unified search, and neural graph."""

from __future__ import annotations

from pathlib import Path

import pytest
from ai_governance.brain.store import BrainStore, NoteDraft
from ai_governance.taskflow.models import Task
from ai_governance.taskflow.store import TaskStore
from ai_governance.ui.app import create_app
from ai_governance.ui.security import SessionSecurity
from fastapi.testclient import TestClient


@pytest.fixture
def brain_client(tmp_path: Path) -> tuple[TestClient, dict[str, str], BrainStore, TaskStore]:
    br_store = BrainStore(tmp_path / "brain")
    tf_store = TaskStore(tmp_path / "tf")
    sec = SessionSecurity(host="127.0.0.1", port=7474, token="tok-brain")
    app = create_app(
        sec,
        task_store_factory=lambda: tf_store,
        brain_store_factory=lambda: br_store,
        static_dir=tmp_path / "static",
    )
    return TestClient(app), {"X-UI-Token": "tok-brain"}, br_store, tf_store


def test_brain_crud_and_search(
    brain_client: tuple[TestClient, dict[str, str], BrainStore, TaskStore],
) -> None:
    client, hdr, _, _ = brain_client
    created = client.post(
        "/api/brain/notes",
        json={
            "title": "Hook Gotcha",
            "body": "Always quote paths.",
            "kind": "gotcha",
            "scope": "personal",
            "tags": ["hooks"],
            "repos": ["ia-spec-ops-engine"],
        },
        headers=hdr,
    )
    assert created.status_code == 201
    slug = created.json()["note"]["slug"]

    updated = client.put(
        f"/api/brain/notes/personal/{slug}",
        json={
            "title": "Hook Gotcha Updated",
            "body": "Updated body.",
            "kind": "reference",
            "tags": ["hooks"],
            "repos": [],
        },
        headers=hdr,
    )
    assert updated.status_code == 200 and updated.json()["note"]["kind"] == "reference"

    hits = client.get("/api/brain/search?q=Gotcha").json()["hits"]
    assert any(h["ref"] == f"personal/{slug}" for h in hits)


def test_brain_secret_rejection_returns_422_without_echoing_secret(
    brain_client: tuple[TestClient, dict[str, str], BrainStore, TaskStore],
) -> None:
    client, hdr, _, _ = brain_client
    secret = client.post(
        "/api/brain/notes",
        json={
            "title": "Bad",
            "body": "api_key = 'sk-super-secret-value-123456'",
            "kind": "gotcha",
            "scope": "personal",
        },
        headers=hdr,
    )
    assert secret.status_code == 422
    assert secret.json()["detail"]["code"] == "secret_rejected"
    assert "sk-super-secret-value-123456" not in secret.text


def _seed_graph_notes(br_store: BrainStore, tf_store: TaskStore) -> None:
    tf_store.create(Task(id="T-99", title="Archived Task", status="closed"))
    br_store.add(
        NoteDraft(
            title="Alpha Note",
            body="Connects to [[beta-note]]",
            kind="decision",
            tags=("arch",),
            repos=("repo-a",),
            source="task:T-99",
            slug="alpha-note",
        )
    )
    br_store.add(
        NoteDraft(
            title="Beta Note",
            body="Standalone",
            kind="reference",
            tags=("arch",),
            repos=("repo-a",),
            slug="beta-note",
        )
    )


def test_brain_neural_graph_with_hubs_and_tasks(
    brain_client: tuple[TestClient, dict[str, str], BrainStore, TaskStore],
) -> None:
    client, _, br_store, tf_store = brain_client
    _seed_graph_notes(br_store, tf_store)
    detail = client.get("/api/brain/notes/personal/beta-note").json()
    assert detail["backlinks"] == [
        {"ref": "personal/alpha-note", "title": "Alpha Note", "kind": "decision"}
    ]

    with_hubs = client.get("/api/brain/graph?hubs=true").json()
    node_ids = {n["id"] for n in with_hubs["nodes"]}
    assert {
        "note:personal/alpha-note",
        "note:personal/beta-note",
        "tag:arch",
        "repo:repo-a",
        "task:T-99",
    } <= node_ids
    assert any(edge["kind"] == "reference" for edge in with_hubs["links"])
    assert any(edge["kind"] == "archive" for edge in with_hubs["links"])


def test_brain_neural_graph_without_hubs_uses_shared_edges(
    brain_client: tuple[TestClient, dict[str, str], BrainStore, TaskStore],
) -> None:
    client, _, br_store, tf_store = brain_client
    _seed_graph_notes(br_store, tf_store)
    no_hubs = client.get("/api/brain/graph?hubs=false").json()
    assert all(n["type"] in ("note", "task") for n in no_hubs["nodes"])
    assert any(edge["kind"] == "shared" and edge["weight"] == 2 for edge in no_hubs["links"])


def test_brain_filters_and_error_status_codes(
    brain_client: tuple[TestClient, dict[str, str], BrainStore, TaskStore],
) -> None:
    client, hdr, br_store, tf_store = brain_client
    _seed_graph_notes(br_store, tf_store)

    filtered = client.get("/api/brain/notes?scope=personal&kind=decision&repo=repo-a")
    assert filtered.status_code == 200 and len(filtered.json()["notes"]) == 1
    assert client.get("/api/brain/notes?stale_days=30").json()["notes"] == []
    assert client.get("/api/brain/notes/personal/missing").status_code == 404
    assert (
        client.post(
            "/api/brain/notes",
            json={"title": "Dup", "body": "x", "slug": "alpha-note", "kind": "decision"},
            headers=hdr,
        ).status_code
        == 409
    )
    assert (
        client.post(
            "/api/brain/notes",
            json={"title": "Bad", "body": "x", "kind": "invalid-kind"},
            headers=hdr,
        ).status_code
        == 400
    )
    assert (
        client.put(
            "/api/brain/notes/personal/missing",
            json={"title": "X", "body": "Y", "kind": "gotcha"},
            headers=hdr,
        ).status_code
        == 404
    )


def test_brain_unified_search_and_graph_error(
    brain_client: tuple[TestClient, dict[str, str], BrainStore, TaskStore],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _, br_store, tf_store = brain_client
    _seed_graph_notes(br_store, tf_store)
    assert client.get("/api/brain/search?q=").json() == {"hits": []}
    task_hits = client.get("/api/brain/search?q=Archived").json()["hits"]
    assert any(h["source"] == "taskflow" and h["ref"] == "T-99" for h in task_hits)

    monkeypatch.setattr(
        "ai_governance.ui.routes_brain.build_brain_graph",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    assert client.get("/api/brain/graph").status_code == 500


def test_brain_graph_ref_links_and_unseeded_task(
    brain_client: tuple[TestClient, dict[str, str], BrainStore, TaskStore],
) -> None:
    client, _, br_store, tf_store = brain_client
    _seed_graph_notes(br_store, tf_store)
    br_store.add(
        NoteDraft(
            title="Gamma Note",
            body="See personal/beta-note and [[personal/alpha-note]].",
            kind="howto",
            source="task:UNSEEDED-1",
            slug="gamma-note",
        )
    )
    graph = client.get("/api/brain/graph").json()
    node_ids = {n["id"] for n in graph["nodes"]}
    assert "task:UNSEEDED-1" in node_ids
    refs = {(e["source"], e["target"]) for e in graph["links"] if e["kind"] == "reference"}
    assert ("note:personal/gamma-note", "note:personal/beta-note") in refs
    assert ("note:personal/gamma-note", "note:personal/alpha-note") in refs


def test_brain_notes_tag_filter_graph_filters_and_orphans(
    brain_client: tuple[TestClient, dict[str, str], BrainStore, TaskStore],
) -> None:
    client, _, br_store, tf_store = brain_client
    _seed_graph_notes(br_store, tf_store)
    br_store.add(
        NoteDraft(
            title="Orphan Note",
            body="No references or archive links.",
            kind="gotcha",
            tags=("solo",),
            repos=("repo-b",),
            slug="orphan-note",
        )
    )

    by_tag = client.get("/api/brain/notes?tag=solo").json()["notes"]
    assert [n["slug"] for n in by_tag] == ["orphan-note"]

    filtered_graph = client.get("/api/brain/graph?repo=repo-b&tag=solo").json()
    note_nodes = [n for n in filtered_graph["nodes"] if n["type"] == "note"]
    assert [n["slug"] for n in note_nodes] == ["orphan-note"]
    assert note_nodes[0]["orphan"] is True
    assert filtered_graph["stats"]["orphans"] == 1

    full_graph = client.get("/api/brain/graph").json()
    by_slug = {n["slug"]: n for n in full_graph["nodes"] if n["type"] == "note"}
    assert by_slug["alpha-note"]["orphan"] is False
    assert by_slug["beta-note"]["orphan"] is False
    assert by_slug["orphan-note"]["orphan"] is True
    assert full_graph["stats"]["orphans"] == 1
