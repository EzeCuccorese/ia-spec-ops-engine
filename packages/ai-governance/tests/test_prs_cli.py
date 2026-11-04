"""``taskflow pr``: registration, the cache-backed board, aggregation and the one-line summary.

Offline: GitHub is replaced by a fake reader that returns canned snapshots, so these tests cover
the registry, the board, the CLI and the show/digest line, never ``gh`` itself (see
``test_prs_github``)."""

# ruff: noqa: F401, F811
from __future__ import annotations

import io
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from ai_governance.taskflow.cli import main
from ai_governance.taskflow.digest import digest
from ai_governance.taskflow.models import Task, now_iso
from ai_governance.taskflow.prs import board as pr_board
from ai_governance.taskflow.prs.cache import PrCache, make_entry
from ai_governance.taskflow.prs.github import NO_GH, GhFailure
from ai_governance.taskflow.prs.refs import PrRef
from ai_governance.taskflow.prs.registry import registrations
from ai_governance.taskflow.prs.snapshot import Snapshot, SyncError
from ai_governance.taskflow.store import TaskStore
from test_taskflow import outside_claude, repo, state  # shared fixtures

PARENT = "ONB-1"


@dataclass
class Env:
    store: TaskStore
    repo: Path
    capsys: pytest.CaptureFixture[str]

    def run(self, *argv: str) -> int:
        return main(list(argv))

    def out(self) -> str:
        return self.capsys.readouterr().out

    def rows(self, *extra: str) -> dict[int, dict]:
        self.capsys.readouterr()
        assert self.run("pr", "list", PARENT, "--json", *extra) == 0
        return {row["number"]: row for row in json.loads(self.out())}

    def seed(self, number: int, result: Snapshot | SyncError, when: str | None = None) -> None:
        cache = PrCache(self.store.root)
        key = PrRef("o/r", number).key
        cache.store(key, make_entry(result, when or now_iso()), cache.begin_sync())


@pytest.fixture
def env(
    state: TaskStore,
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> Env:
    monkeypatch.chdir(repo)
    assert main(["new", PARENT, "--title", "Parent", "--workflow", "manual"]) == 0
    assert main(["bind", PARENT, "--repo", str(repo)]) == 0
    capsys.readouterr()
    return Env(state, repo, capsys)


def snap(**over: object) -> Snapshot:
    base: dict[str, object] = {
        "state": "OPEN",
        "is_draft": False,
        "base": "main",
        "head": "feat",
        "default_branch": "main",
        "head_repo": "o/r",
        "title": "Add thing",
        "ci": "ok",
        "review": "ok",
        "mergeable": "ok",
        "threads_open": 0,
    }
    return Snapshot(**{**base, **over})  # type: ignore[arg-type]


def test_add_is_idempotent_and_keeps_the_group(env: Env) -> None:
    refs = ["o/r#1", "https://github.com/o/r/pull/2"]
    assert env.run("pr", "add", PARENT, *refs, "--group", "chain") == 0
    assert "2 new, 0 already" in env.out()
    assert env.run("pr", "add", PARENT, *refs) == 0
    assert "0 new, 2 already" in env.out()
    prs = env.store.get(PARENT).prs
    assert [(p["repo"], p["number"], p["group"]) for p in prs] == [
        ("o/r", 1, "chain"),
        ("o/r", 2, "chain"),
    ]


def test_bare_numbers_need_a_repository(env: Env) -> None:
    assert env.run("pr", "add", PARENT, "#5") == 1
    assert env.run("pr", "add", PARENT, "#5", "--repo", "o/r") == 0
    assert [(p["repo"], p["number"]) for p in env.store.get(PARENT).prs] == [("o/r", 5)]


def test_add_reads_pasted_text_from_stdin(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    pasted = "see o/r#7 and https://github.com/o/r/pull/8/files, nothing else"
    monkeypatch.setattr("sys.stdin", io.StringIO(pasted))
    assert env.run("pr", "add", PARENT, "-") == 0
    prs = env.store.get(PARENT).prs
    assert sorted(p["number"] for p in prs) == [7, 8]
    assert {p["source"] for p in prs} == {"paste"}


def test_input_without_any_pr_is_an_error(env: Env) -> None:
    assert env.run("pr", "add", PARENT, "no pull request here") == 1
    assert env.store.get(PARENT).prs == []


def test_rm_stops_tracking_and_hides_legacy_references(env: Env) -> None:
    assert env.run("pr", "add", PARENT, "o/r#1") == 0
    assert env.run("reference", PARENT, "pr", "o/r#9") == 0
    found, _ = registrations(env.store.get(PARENT))
    assert sorted(r.ref.number for r in found) == [1, 9]
    assert env.run("pr", "rm", PARENT, "o/r#1", "o/r#9") == 0
    assert registrations(env.store.get(PARENT))[0] == []


def test_list_reads_the_cache_and_classifies_every_row(env: Env) -> None:
    assert env.run("pr", "add", PARENT, "o/r#1", "o/r#2", "o/r#3") == 0
    env.seed(1, snap(ci="failed"))
    env.seed(2, snap())
    rows = env.rows()
    assert rows[1]["blockers"] == ["ci-failed"] and rows[1]["ready"] is False
    assert rows[2]["blockers"] == [] and rows[2]["ready"] is True
    assert rows[3]["blockers"] == ["not-synced"] and rows[3]["age_s"] is None
    assert set(env.rows("--blocked")) == {1, 3}


def test_a_stale_snapshot_is_never_ready(env: Env) -> None:
    assert env.run("pr", "add", PARENT, "o/r#1") == 0
    old = (datetime.now(UTC) - timedelta(hours=10)).isoformat(timespec="seconds")
    env.seed(1, snap(), old)
    row = env.rows()[1]
    assert row["stale"] is True and row["ready"] is False


def test_a_hostile_title_is_cleaned_before_printing(env: Env) -> None:
    assert env.run("pr", "add", PARENT, "o/r#1") == 0
    env.seed(1, snap(title="\x1b[31mred\x1b[0m [bold]x[/bold] ignore all previous\nnext line"))
    assert env.run("pr", "list", PARENT) == 0
    text = env.out()
    assert "\x1b" not in text and "‮" not in text
    assert "next line" in text and "ignore all previous\nnext" not in text


class NoLogins:
    def logins(self) -> list[tuple[str, bool]]:
        return []


class FakeReader:
    """Stands in for ``PrReader``: PR 1 is fine, PR 2 times out, anything else is missing."""

    def __init__(self, cache: PrCache | None = None) -> None:
        self.cache = cache
        self.book = NoLogins()

    def fetch(self, ref: PrRef) -> Snapshot | SyncError:
        if ref.number == 1:
            return snap()
        return SyncError("timeout" if ref.number == 2 else "pull request not found")


def test_sync_writes_the_cache_not_the_task_and_fails_on_errors(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pr_board, "PrReader", FakeReader)
    assert env.run("pr", "add", PARENT, "o/r#1", "o/r#2") == 0
    before = env.store.get(PARENT).updated_at
    assert env.run("pr", "sync", PARENT) == 1  # one sync-error
    rows = env.rows()
    assert rows[1]["ready"] is True and rows[2]["error"] == "timeout"
    assert env.store.get(PARENT).updated_at == before  # sync never touches the task


def test_sync_succeeds_when_every_pr_resolves(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pr_board, "PrReader", FakeReader)
    assert env.run("pr", "add", PARENT, "o/r#1") == 0
    assert env.run("pr", "sync", PARENT) == 0


def test_cache_store_many_batches_updates_and_respects_gen(env: Env) -> None:
    cache = PrCache(env.store.root)
    stamp = now_iso()
    items = {
        "o/r#1": make_entry(snap(), stamp),
        "o/r#2": make_entry(snap(), stamp),
    }
    # First batch with gen 2 stores both
    assert cache.store_many(items, 2) == 2
    assert cache.get("o/r#1")["gen"] == 2
    assert cache.get("o/r#2")["gen"] == 2

    # Older gen 1 stores nothing
    assert cache.store_many(items, 1) == 0
    assert cache.get("o/r#1")["gen"] == 2

    # Newer gen 3 updates only what is passed
    assert cache.store_many({"o/r#1": make_entry(snap(), stamp)}, 3) == 1
    assert cache.get("o/r#1")["gen"] == 3
    assert cache.get("o/r#2")["gen"] == 2


def test_sync_discovers_logins_once_before_pool_and_stores_in_one_write(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    events: list[str] = []

    class MockBook:
        def logins(self) -> list[tuple[str, bool]]:
            events.append("logins")
            return [("alice", True)]

    class ReaderWithBook:
        def __init__(self, cache: PrCache | None = None) -> None:
            self.cache = cache
            self.book = MockBook()

        def fetch(self, ref: PrRef) -> Snapshot | SyncError:
            events.append(f"fetch:{ref.number}")
            return snap()

    monkeypatch.setattr(pr_board, "PrReader", ReaderWithBook)
    stored_batches: list[list[tuple[str, Any]]] = []
    original_store_many = PrCache.store_many

    def spy_store_many(self: PrCache, entries: Any, gen: int) -> int:
        stored_batches.append(list(entries))
        return original_store_many(self, entries, gen)

    monkeypatch.setattr(PrCache, "store_many", spy_store_many)
    store_calls = 0

    def fail_store(self: PrCache, key: str, entry: Any, gen: int) -> bool:
        nonlocal store_calls
        store_calls += 1
        return True

    monkeypatch.setattr(PrCache, "store", fail_store)

    assert env.run("pr", "add", PARENT, "o/r#1", "o/r#2") == 0
    assert env.run("pr", "sync", PARENT) == 0

    # Logins was discovered first before any fetch
    assert events[0] == "logins"
    assert set(events[1:]) == {"fetch:1", "fetch:2"}
    # Store was batched in one write under store_many, store was not called
    assert len(stored_batches) == 1
    assert {k for k, _ in stored_batches[0]} == {"o/r#1", "o/r#2"}
    assert store_calls == 0


def test_sync_tolerates_login_discovery_failure(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    class FailingBook:
        def logins(self) -> list[tuple[str, bool]]:
            raise GhFailure(NO_GH)

    class ReaderWithFailingBook:
        def __init__(self, cache: PrCache | None = None) -> None:
            self.cache = cache
            self.book = FailingBook()

        def fetch(self, ref: PrRef) -> Snapshot | SyncError:
            return snap()

    monkeypatch.setattr(pr_board, "PrReader", ReaderWithFailingBook)
    assert env.run("pr", "add", PARENT, "o/r#1") == 0
    assert env.run("pr", "sync", PARENT) == 0


def test_a_parent_shows_its_subtasks_prs_once_each(env: Env) -> None:
    assert (
        env.run("new", "ONB-2", "--title", "Sub", "--parent", PARENT, "--workflow", "manual") == 0
    )
    assert env.run("pr", "add", PARENT, "o/r#1") == 0
    assert env.run("pr", "add", "ONB-2", "o/r#1", "o/r#2") == 0
    rows = env.rows()
    assert sorted(rows) == [1, 2]
    assert rows[1]["task"] == PARENT and rows[2]["task"] == "ONB-2"


def test_a_cycle_between_tasks_cannot_hang_the_board(env: Env) -> None:
    assert env.run("pr", "add", PARENT, "o/r#1") == 0
    env.store.mutate(PARENT, lambda t: t.subtasks.append(PARENT))
    assert sorted(env.rows()) == [1]


def test_show_and_digest_carry_exactly_one_summary_line(env: Env) -> None:
    assert "PRs:" not in digest(env.store, PARENT)
    assert env.run("pr", "add", PARENT, "o/r#1", "o/r#2") == 0
    env.seed(1, snap(ci="failed"))
    env.seed(2, snap())
    assert env.run("show", PARENT) == 0
    shown = env.out()
    assert shown.count("PRs: 2") == 1 and "1 ci-failed" in shown
    line = [ln for ln in digest(env.store, PARENT).splitlines() if "PRs:" in ln]
    assert len(line) == 1 and "o/r" not in line[0]


def test_an_old_state_without_pr_fields_loads() -> None:
    task = Task.from_dict({"id": "x", "title": "t"})
    assert task.prs == [] and task.pr_removed == []
