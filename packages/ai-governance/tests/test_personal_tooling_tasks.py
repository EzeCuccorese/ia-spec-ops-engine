"""Task tracking acceptance coverage for @s1 and @s2."""

from __future__ import annotations

import concurrent.futures
import json
from pathlib import Path

from ai_governance.session.cli import main as progress_main
from ai_governance.session.resolver import TaskResolver
from ai_governance.session.tracker import SessionTracker, TaskState


def test_structured_task_operations_and_bounded_state(tmp_path: Path) -> None:
    tracker = SessionTracker(root_dir=tmp_path, compact_limits={"facts": 2, "steps": 2})
    tracker.create_task(TaskState(id="ONB-42", title="Checkout"))

    tracker.pause_task("ONB-42", "waiting")
    assert tracker.get_task("ONB-42").status == "paused"  # type: ignore[union-attr]
    tracker.resume_task("ONB-42")
    tracker.update_summary("ONB-42", "Ready for validation")
    tracker.add_step("ONB-42", "one")
    tracker.add_step("ONB-42", "two")
    tracker.add_step("ONB-42", "three")
    tracker.complete_step("ONB-42", "three")
    tracker.add_fact("ONB-42", "fact one")
    tracker.add_fact("ONB-42", "fact two")
    tracker.add_fact("ONB-42", "fact three")
    tracker.add_link("ONB-42", "PR", "https://example.test/pr/1")
    tracker.add_reference("ONB-42", "jira", "ONB-42")
    tracker.add_repository("ONB-42", tmp_path / "repo", branch="feat/onb-42", pr="1")

    task = tracker.get_task("ONB-42")
    assert task is not None
    assert task.status == "active"
    assert task.summary == "Ready for validation"
    assert [s["text"] for s in task.steps] == ["two", "three"]
    assert task.steps[-1]["done"] is True
    assert [f["text"] for f in task.facts] == ["fact two", "fact three"]
    assert task.links[0]["url"] == "https://example.test/pr/1"
    assert task.references[0]["value"] == "ONB-42"
    assert task.repos[0]["branch"] == "feat/onb-42"
    assert "Archived steps: one" in tracker.read_log("ONB-42")
    assert "Archived facts: fact one" in tracker.read_log("ONB-42")


def test_repository_resolution_falls_back_after_branch_key(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "shop"
    repo.mkdir()
    task = TaskState(id="personal-task", title="Personal", repos=[{"path": str(repo)}])

    monkeypatch.setattr(TaskResolver, "_git_branch", staticmethod(lambda _p: "feature/no-ticket"))
    monkeypatch.setattr(TaskResolver, "_git_root", staticmethod(lambda _p: repo))
    assert TaskResolver.resolve_from_context([task], repo) == "personal-task"

    monkeypatch.setattr(TaskResolver, "_git_branch", staticmethod(lambda _p: "feat/onb-99"))
    keyed = TaskState(id="ONB-99", title="Keyed")
    assert TaskResolver.resolve_from_context([task, keyed], repo) == "ONB-99"


def test_concurrent_structured_mutations_do_not_lose_updates(tmp_path: Path) -> None:
    tracker = SessionTracker(root_dir=tmp_path, compact_limits={"facts": 100})
    tracker.create_task(TaskState(id="CONCUR-2", title="Concurrent"))

    def add_fact(i: int) -> None:
        SessionTracker(root_dir=tmp_path, compact_limits={"facts": 100}).add_fact(
            "CONCUR-2", f"fact-{i}"
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(add_fact, range(30)))

    task = tracker.get_task("CONCUR-2")
    assert task is not None
    assert {f["text"] for f in task.facts} == {f"fact-{i}" for i in range(30)}


def test_list_all_and_digest_are_compact(tmp_path: Path) -> None:
    tracker = SessionTracker(root_dir=tmp_path)
    tracker.create_task(TaskState(id="active", title="Active", summary="Now"))
    tracker.create_task(TaskState(id="closed", title="Closed"))
    tracker.close_task("closed")
    assert [t.id for t in tracker.list_tasks()] == ["active"]
    assert {t.id for t in tracker.list_tasks(include_closed=True)} == {"active", "closed"}
    digest = tracker.digest(focus_id="active", max_chars=200)
    assert "active" in digest
    assert len(digest) <= 200


def test_progress_cli_exposes_modern_mutations(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("AI_GOVERNANCE_STATE_DIR", str(tmp_path))
    assert progress_main(["new", "cli-task", "--title", "CLI"]) == 0
    assert progress_main(["pause", "cli-task", "--reason", "wait"]) == 0
    assert progress_main(["step", "cli-task", "add", "test it"]) == 0
    assert progress_main(["fact", "cli-task", "verified"]) == 0
    assert progress_main(["link", "cli-task", "PR", "https://example.test/1"]) == 0
    capsys.readouterr()
    assert progress_main(["show", "cli-task", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["status"] == "paused"
    assert data["steps"][0]["text"] == "test it"
    assert data["facts"][0]["text"] == "verified"
    assert data["links"][0]["title"] == "PR"
