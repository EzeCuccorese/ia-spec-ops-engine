"""Review rounds against the task's own control plane: stamp drift, config origin, close.

Hermetic: GitHub is replaced by fakes, Orca by the fake CLI of ``orca_fakes``.
"""

# ruff: noqa: F401, F811
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from ai_governance.taskflow import dispatch as dispatch_mod
from ai_governance.taskflow import review, review_summary
from ai_governance.taskflow.config import load_config
from ai_governance.taskflow.control import DispatchError
from ai_governance.taskflow.dispatch import DispatchRequest, plan_dispatch
from ai_governance.taskflow.refresh import refresh
from ai_governance.taskflow.review_source import PullSnapshot, parse_pr_url
from orca_fakes import TASK, OrcaWorld, _make_repo, world

PR_ONE = "https://github.com/acme/shop/pull/7"
REVIEW = "FINDING: none\nPOSITION: approve - clean\n"
SOURCE_CONFIG = '[taskflow]\ndenied_models = ["some-model"]\n'


def _commit(repo: Path, name: str, text: str) -> None:
    path = repo / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    subprocess.run(["git", "add", "-f", name], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", name], cwd=repo, check=True, capture_output=True)


@pytest.fixture
def source_files() -> dict[str, str]:
    """Extra files committed into the captured pull request source."""
    return {}


@pytest.fixture
def github(monkeypatch: pytest.MonkeyPatch, source_files: dict[str, str]) -> None:
    def capture(url: str, directory: Path) -> PullSnapshot:
        ref = parse_pr_url(url)
        snapshot = PullSnapshot(ref, f"PR {ref.number}", "a" * 40, "main", False, directory)
        directory.mkdir(parents=True)
        _make_repo(snapshot.source)
        for name, text in source_files.items():
            _commit(snapshot.source, name, text)
        for path in (snapshot.meta_file, snapshot.diff_file, snapshot.references_file):
            path.write_text("{}\n", encoding="utf-8")
        snapshot.threads_file.write_text('{"truncated": false, "threads": []}\n', encoding="utf-8")
        return snapshot

    monkeypatch.setattr(review, "snapshot_pull_request", capture)
    monkeypatch.setattr(review, "viewer_login", lambda: "me")
    monkeypatch.setattr(review_summary, "current_head", lambda ref: "a" * 40)
    monkeypatch.setattr(review_summary, "activity_since", lambda *args: [])


def _open(world: OrcaWorld) -> None:
    result = world.run("review", TASK, "open", "--pr", PR_ONE, "--agent", "claude")
    assert result.code == 0, result.text


def _change_bound_repo(world: OrcaWorld) -> None:
    _commit(world.repo, "app.py", "x = 2\n")
    refresh(world.store, world.task(), load_config([world.repo]))


def _debater(world: OrcaWorld) -> int:
    cfg = load_config([world.repo])
    task = refresh(world.store, world.task(), cfg)
    request = DispatchRequest("debater", "work", "a", "do it", {"agent": "claude", "model": ""})
    return plan_dispatch(world.store, task, cfg, request).n


def _collect(world: OrcaWorld, number: int, answer: str = REVIEW) -> str:
    world.finish(number, f"D{number}", answer=answer, agent="claude")
    return world.collect(number, f"D{number}").text


def test_dispatch_record_keeps_the_review_source(world: OrcaWorld, github) -> None:
    _open(world)
    record = world.dispatch_json(1)
    assert record["source"] == record["repos"][0]["path"]
    assert "task_repos" not in record


def test_review_round_is_valid_after_the_task_repo_changed(world: OrcaWorld, github) -> None:
    _open(world)
    _change_bound_repo(world)
    text = _collect(world, 1)
    assert "control files changed" not in text
    assert world.record(1)["state"] == "valid"


def test_debate_round_is_refused_after_the_task_repo_changed(world: OrcaWorld) -> None:
    number = _debater(world)
    _change_bound_repo(world)
    text = _collect(world, number, "POSITION: approve - fine\n")
    assert "control files changed since dispatch (task.code_stamp" in text
    assert all(r["n"] != number for r in world.task().rounds)


def _settled_debate(world: OrcaWorld) -> int:
    number = _debater(world)
    _collect(world, number, "POSITION: approve - fine\n")
    assert world.record(number)["n"] == number
    return number


@pytest.mark.parametrize("stamp_moved", [False, True], ids=["tamper_only", "tamper_and_stamp"])
def test_review_round_is_refused_when_an_earlier_round_was_tampered(
    world: OrcaWorld, github, stamp_moved: bool
) -> None:
    debate = _settled_debate(world)
    _open(world)
    if stamp_moved:
        _change_bound_repo(world)
    world.edit_state(lambda d: d["rounds"][0].update(verdict="block"))
    text = _collect(world, debate + 1)
    assert f"control files changed since dispatch (round record {debate}" in text
    assert "task.code_stamp" not in text
    assert all(r["n"] != debate + 1 for r in world.task().rounds)


def test_review_round_is_invalid_when_its_source_changed(world: OrcaWorld, github) -> None:
    _open(world)
    source = Path(world.dispatch_json(1)["source"])
    (source / "app.py").write_text("x = 3\n", encoding="utf-8")
    assert "reader changed the tree" in _collect(world, 1)
    assert world.record(1)["state"] != "valid"


@pytest.mark.parametrize(
    "source_files", [{".ai-governance/config.toml": SOURCE_CONFIG}], ids=["denied_models"]
)
def test_config_inside_the_review_source_does_not_affect_collect(world: OrcaWorld, github) -> None:
    _open(world)
    source = Path(world.dispatch_json(1)["source"])
    assert "some-model" in load_config([source]).denied_models
    text = _collect(world, 1)
    assert "taskflow.denied_models" not in text
    assert world.record(1)["state"] == "valid"


def _write_config(repo: Path) -> None:
    (repo / ".ai-governance").mkdir(exist_ok=True)
    (repo / ".ai-governance" / "config.toml").write_text(SOURCE_CONFIG, encoding="utf-8")


def test_denial_in_a_bound_repo_applies_to_a_review_round(world: OrcaWorld, github) -> None:
    _open(world)
    _write_config(world.repo)
    assert "taskflow.denied_models" in _collect(world, 1)
    assert world.task().rounds == []


def test_repo_bound_after_dispatch_configures_a_review_round(
    world: OrcaWorld, github, tmp_path: Path
) -> None:
    _open(world)
    other = tmp_path / "other"
    _make_repo(other)
    _write_config(other)
    bound = world.run("bind", TASK, "--repo", str(other))
    assert bound.code == 0, bound.text
    assert "taskflow.denied_models" in _collect(world, 1)
    assert world.task().rounds == []


def test_close_refuses_with_an_unsettled_reviewer_round(world: OrcaWorld, github) -> None:
    _open(world)
    result = world.run("close", TASK)
    assert result.code != 0
    assert "unsettled round(s) 001" in result.text
    assert world.task().status != "closed"


@pytest.mark.parametrize("override", ["--force", "--abandon", "--done-outside"])
def test_each_override_closes_with_a_pending_reviewer_round(
    world: OrcaWorld, github, override: str
) -> None:
    _open(world)
    assert world.run("close", TASK, override).code == 0
    assert world.task().status == "closed"


def test_aborted_round_counts_as_settled_for_close(world: OrcaWorld, github) -> None:
    _open(world)
    world.finish(1, "D1", answer=REVIEW, agent="claude")
    aborted = world.abort(1, "--dispatch-id", "D1", "--reason", "gone")
    assert aborted.code == 0, aborted.text
    closed = world.run("close", TASK)
    assert closed.code == 0, closed.text


def test_corrupted_dispatch_of_a_pending_reservation_blocks_close(world: OrcaWorld, github) -> None:
    _open(world)
    (world.run_dir(1) / "dispatch.json").write_text("{not json", encoding="utf-8")
    result = world.run("close", TASK)
    assert result.code != 0
    assert "unsettled round(s) 001" in result.text


def test_foreign_dispatch_record_does_not_block_close(world: OrcaWorld) -> None:
    foreign = world.run_dir(5)
    foreign.mkdir(parents=True)
    (foreign / "dispatch.json").write_text('{"task": "other", "n": 5}', encoding="utf-8")
    closed = world.run("close", TASK)
    assert closed.code == 0, closed.text


def test_close_refuses_with_an_unsettled_debater_round(world: OrcaWorld) -> None:
    number = _debater(world)
    result = world.run("close", TASK)
    assert result.code != 0
    assert f"unsettled round(s) {number:03d}" in result.text


def test_verify_dispatch_uses_only_the_sealed_bytes(
    world: OrcaWorld, github, monkeypatch: pytest.MonkeyPatch
) -> None:
    _open(world)
    path = world.run_dir(1) / "dispatch.json"
    sealed = path.read_text(encoding="utf-8")
    forged = sealed.replace('"source": "', '"source": "/elsewhere')
    reads = iter([sealed])
    original = Path.read_text

    def swap_after_first(self: Path, *args: str, **kwargs: str) -> str:
        if self == path:
            return next(reads, forged)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", swap_after_first)
    found = dispatch_mod.verify_dispatch(world.store, TASK, 1)
    assert found["source"] == json.loads(sealed)["source"]


@pytest.mark.parametrize(
    "body",
    [json.dumps({"task": TASK, "n": 9}), json.dumps({"task": TASK})],
    ids=["other_number", "no_number"],
)
def test_own_dispatch_with_a_mismatched_number_blocks_close(world: OrcaWorld, body: str) -> None:
    reservation = world.run_dir(5)
    reservation.mkdir(parents=True)
    (reservation / "dispatch.json").write_text(body, encoding="utf-8")
    result = world.run("close", TASK)
    assert result.code != 0
    assert "unsettled round(s) 005" in result.text


def test_four_digit_round_directory_blocks_close(world: OrcaWorld) -> None:
    reservation = world.store.task_dir(TASK) / "runs" / "1000"
    reservation.mkdir(parents=True)
    (reservation / "dispatch.json").write_text(
        json.dumps({"task": TASK, "n": 1000}), encoding="utf-8"
    )
    result = world.run("close", TASK)
    assert result.code != 0
    assert "unsettled round(s) 1000" in result.text


def test_round_is_not_published_into_a_closed_task(world: OrcaWorld, github) -> None:
    task = world.task()
    assert world.run("close", TASK).code == 0
    source = world.store.task_dir(TASK) / "late-source"
    _make_repo(source)
    request = DispatchRequest(
        "validator", "work", "pr", "review it", {"agent": "claude", "model": ""}, source=str(source)
    )
    with pytest.raises(DispatchError, match="is closed: no round can be dispatched"):
        plan_dispatch(world.store, task, load_config([world.repo]), request)
    assert not (world.store.task_dir(TASK) / "runs").exists()
