"""Tests for SSE directory signature computation, event streaming, and /api/events."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from ai_governance.brain.store import BrainStore, NoteDraft
from ai_governance.taskflow.models import Task
from ai_governance.taskflow.store import TaskStore
from ai_governance.ui.app import create_app
from ai_governance.ui.events import compute_dir_signature, stream_store_events
from ai_governance.ui.security import SessionSecurity
from fastapi.testclient import TestClient


def test_compute_dir_signature_handles_missing_and_changes(tmp_path: Path) -> None:
    missing = tmp_path / "missing"
    assert compute_dir_signature(missing) == ""

    root = tmp_path / "store"
    root.mkdir()
    (root / "ignore.txt").write_text("ignored", encoding="utf-8")
    empty_sig = compute_dir_signature(root)

    (root / "note.md").write_text("hello", encoding="utf-8")
    md_sig = compute_dir_signature(root)
    assert md_sig != empty_sig

    (root / "broken.json").symlink_to(tmp_path / "does-not-exist.json")
    assert compute_dir_signature(root) == md_sig

    (root / "task.json").write_text("{}", encoding="utf-8")
    assert compute_dir_signature(root) != md_sig


def test_stream_store_events_snapshot_and_changed(tmp_path: Path) -> None:
    task_root = tmp_path / "tf"
    brain_root = tmp_path / "brain"
    task_root.mkdir()
    brain_root.mkdir()

    async def _collect() -> list[str]:
        stream = stream_store_events(task_root, brain_root, poll_interval=0.01, max_events=2)
        first = await anext(stream)
        (brain_root / "note.md").write_text("# changed", encoding="utf-8")
        second = await anext(stream)
        return [first, second]

    events = asyncio.run(_collect())
    assert events[0].startswith("event: snapshot\n")
    assert events[1].startswith("event: changed\n")
    payload = json.loads(events[1].split("data: ", 1)[1].strip())
    assert payload == {"changed": ["brain"]}


def test_stream_store_events_emits_ping_after_ten_idle_ticks(tmp_path: Path) -> None:
    task_root = tmp_path / "tf"
    brain_root = tmp_path / "brain"
    task_root.mkdir()
    brain_root.mkdir()

    async def _collect() -> list[str]:
        stream = stream_store_events(task_root, brain_root, poll_interval=0.001, max_events=2)
        return [chunk async for chunk in stream]

    chunks = asyncio.run(_collect())
    assert len(chunks) == 2
    assert chunks[1] == ": ping\n\n"


def test_api_events_endpoint_returns_snapshot_sse(tmp_path: Path) -> None:
    tf_store = TaskStore(tmp_path / "tf")
    br_store = BrainStore(tmp_path / "brain")
    tf_store.create(Task(id="T-1", title="Seed"))
    br_store.add(NoteDraft(title="Seed", body="Body", slug="seed"))

    sec = SessionSecurity(host="127.0.0.1", port=7474, token="tok-events")
    app = create_app(
        sec,
        task_store_factory=lambda: tf_store,
        brain_store_factory=lambda: br_store,
        static_dir=tmp_path / "static",
    )
    resp = TestClient(app).get("/api/events?max_events=1")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    assert resp.headers["cache-control"] == "no-cache"
    assert resp.headers["x-accel-buffering"] == "no"
    assert "event: snapshot\n" in resp.text
    data_line = next(line for line in resp.text.splitlines() if line.startswith("data: "))
    payload = json.loads(data_line.removeprefix("data: "))
    assert payload["taskflow"] and payload["brain"]
