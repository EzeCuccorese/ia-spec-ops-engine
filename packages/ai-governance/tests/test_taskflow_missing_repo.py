"""A bound repository that vanished from disk never blocks notebook/status/close commands."""

# ruff: noqa: F401, F811
from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from pathlib import Path

import pytest
from ai_governance import hooks
from ai_governance.taskflow import cli, repos, stamp
from ai_governance.taskflow.cli import main
from ai_governance.taskflow.config import FlowConfig
from ai_governance.taskflow.models import Task
from ai_governance.taskflow.store import TaskStore
from orca_fakes import attach_orca
from test_taskflow import _git, outside_claude, repo, state  # shared fixtures

WARNING = "bound repo not found, skipped: {}"
GONE = "no bound repo exists on disk"
TASK = "TASK-1"

ConfigFor = Callable[[Task], FlowConfig]


def _new_repo(root: Path, name: str) -> Path:
    path = (root / name).resolve()
    path.mkdir()
    _git(path, "init", "-q", "-b", "main")
    _git(path, "config", "user.email", "t@example.com")
    _git(path, "config", "user.name", "T")
    (path / "app.py").write_text("x = 1\n")
    _git(path, "add", ".")
    _git(path, "commit", "-qm", "init")
    return path


def _bind(*paths: Path, integration: str = "") -> None:
    assert main(["new", TASK, "--title", "t", "--summary", "s"]) == 0
    for path in paths:
        extra = ["--integration-branch", integration] if integration else []
        assert main(["bind", TASK, "--repo", str(path), *extra]) == 0


@pytest.fixture(autouse=True)
def _orca_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    attach_orca(tmp_path / "orca-world", monkeypatch)
    return tmp_path / "orca-world"


def _use(monkeypatch: pytest.MonkeyPatch, config_for: ConfigFor) -> None:
    monkeypatch.setattr(cli, "_config", config_for)


def _stamp_json(capsys: pytest.CaptureFixture[str]) -> dict:
    assert main(["stamp", TASK]) == 0
    return json.loads(capsys.readouterr().out)["stamp"]


ARGV = {
    "status": ["status", TASK],
    "stamp": ["stamp", TASK],
    "approve": ["approve", TASK, "--action", "review", "--target", "x", "--user-reply", "ok"],
    "ask": ["ask", TASK, "--action", "review", "--target", "x"],
}


@pytest.fixture
def gone(state: TaskStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> Path:
    path = _new_repo(tmp_path, "a")
    _bind(path)
    _use(monkeypatch, lambda task: FlowConfig())
    assert main(["stamp", TASK]) == 0
    shutil.rmtree(path)
    capsys.readouterr()
    return path


@pytest.mark.parametrize("name", sorted(ARGV))
def test_command_survives_a_missing_repo(name: str, gone: Path, capsys) -> None:
    assert main(ARGV[name]) == 0
    assert capsys.readouterr().err.splitlines().count(WARNING.format(gone)) == 1


def test_close_succeeds_when_a_bound_repo_is_gone(
    state: TaskStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    path = _new_repo(tmp_path, "a")
    _bind(path)
    _use(monkeypatch, lambda task: FlowConfig())
    assert main(["stamp", TASK]) == 0
    shutil.rmtree(path)
    capsys.readouterr()
    assert main(["close", TASK, "--reason", "repo gone"]) == 0
    assert state.get(TASK).status == "closed"


def test_show_and_digest_do_not_crash(gone: Path, capsys) -> None:
    assert main(["show", TASK]) == 0 and main(["digest", "--id", TASK]) == 0
    captured = capsys.readouterr()
    assert str(gone) in captured.out and "bound repo not found" not in captured.err


def test_session_end_hook_survives_a_vanished_cwd(
    state: TaskStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert main(["new", TASK, "--title", "t", "--summary", "s"]) == 0
    missing = tmp_path / "vanished"
    monkeypatch.setattr(hooks, "_cwd", lambda payload: missing)
    monkeypatch.setattr(hooks, "_payload", lambda: {})
    monkeypatch.setattr(hooks, "_active_task", lambda cwd: (state, TASK))
    assert hooks._claude_session_end() == 0
    log = state.read_log(TASK)
    assert "Session ended on ?" in log and "unknown number of uncommitted" in log


def test_existing_repo_is_unaffected(
    state: TaskStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    path = _new_repo(tmp_path, "a")
    _bind(path)
    _use(monkeypatch, lambda task: FlowConfig())
    capsys.readouterr()
    assert main(["status", TASK]) == 0 and main(["close", TASK]) == 0
    assert "bound repo not found" not in capsys.readouterr().err
    assert not any(e.get("missing") for e in state.get(TASK).code_stamp["repos"])


def test_two_repos_one_deleted_warns_once_for_the_deleted_one(
    state: TaskStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    first, second = _new_repo(tmp_path, "a"), _new_repo(tmp_path, "b")
    _bind(first, second)
    _use(monkeypatch, lambda task: FlowConfig())
    assert main(["stamp", TASK]) == 0
    shutil.rmtree(second)
    capsys.readouterr()
    assert main(["status", TASK]) == 0
    err = capsys.readouterr().err.splitlines()
    assert err == [WARNING.format(second)]
    assert main(["close", TASK]) == 0


def test_two_missing_paths_give_two_lines_and_each_invocation_warns_again(
    state: TaskStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    first, second = _new_repo(tmp_path, "a"), _new_repo(tmp_path, "b")
    _bind(first, second)
    _use(monkeypatch, lambda task: FlowConfig())
    shutil.rmtree(first)
    shutil.rmtree(second)
    capsys.readouterr()
    assert main(["status", TASK]) == 0
    assert sorted(capsys.readouterr().err.splitlines()) == sorted(
        [WARNING.format(first), WARNING.format(second)]
    )
    assert main(["status", TASK]) == 0
    assert len(capsys.readouterr().err.splitlines()) == 2


def test_repo_deleted_between_listing_and_git_is_reported_once(
    state: TaskStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    path = _new_repo(tmp_path, "a")
    _bind(path)
    _use(monkeypatch, lambda task: FlowConfig())

    def vanishing(repo_dir: Path, **kwargs: object) -> dict:
        shutil.rmtree(repo_dir)
        raise stamp.GitError("git branch --show-current: [Errno 2]") from FileNotFoundError(
            2, "No such file or directory", str(repo_dir)
        )

    monkeypatch.setattr(stamp, "repo_stamp", vanishing)
    capsys.readouterr()
    assert main(["status", TASK]) == 0
    assert capsys.readouterr().err.splitlines() == [WARNING.format(path)]


def test_a_failing_repo_that_still_exists_still_raises(
    state: TaskStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    path = _new_repo(tmp_path, "a")
    _bind(path)
    _use(monkeypatch, lambda task: FlowConfig())

    def broken(repo_dir: Path, **kwargs: object) -> dict:
        raise stamp.GitError("git: boom")

    monkeypatch.setattr(stamp, "repo_stamp", broken)
    assert main(["status", TASK]) == 1
    assert "boom" in capsys.readouterr().err


def test_delete_then_status_then_stamp_then_approve_then_close(
    state: TaskStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    first, second = _new_repo(tmp_path, "a"), _new_repo(tmp_path, "b")
    _bind(first, second)
    _use(monkeypatch, lambda task: FlowConfig())
    capsys.readouterr()
    key = _stamp_json(capsys)["key"]
    shutil.rmtree(second)
    capsys.readouterr()
    assert main(["status", TASK]) == 0
    out = capsys.readouterr().out
    assert "repo gone (stamp frozen)" in out and str(second) in out
    assert state.get(TASK).stamp_key == key
    assert _stamp_json(capsys)["key"] == key
    approve = ["approve", TASK, "--action", "review", "--target", "x", "--user-reply", "ok"]
    assert main(approve) == 0 and state.get(TASK).stamp_key == key
    carried = [e for e in state.get(TASK).code_stamp["repos"] if e["repo"] == str(second)]
    assert carried and carried[0]["missing"] is True
    assert main(["close", TASK]) == 0


def test_all_repos_gone_and_no_stored_stamp_does_not_crash(
    state: TaskStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    path = _new_repo(tmp_path, "a")
    _bind(path)
    _use(monkeypatch, lambda task: FlowConfig())
    shutil.rmtree(path)
    assert main(["status", TASK]) == 0 and main(["stamp", TASK]) == 0
    assert main(["close", TASK]) == 0
    assert "Errno 2" not in capsys.readouterr().err


def test_stamp_with_a_live_repo_has_no_missing_flag(
    state: TaskStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    path = _new_repo(tmp_path, "a")
    _bind(path)
    _use(monkeypatch, lambda task: FlowConfig())
    capsys.readouterr()
    assert all("missing" not in entry for entry in _stamp_json(capsys)["repos"])


def test_close_abandon_still_works(
    state: TaskStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _new_repo(tmp_path, "a")
    _bind(path)
    shutil.rmtree(path)
    assert main(["close", TASK, "--abandon", "--reason", "gone"]) == 0


def test_partition_keeps_order_counts_symlinked_dirs_live_and_files_missing(tmp_path: Path) -> None:
    live, link, afile = tmp_path / "live", tmp_path / "link", tmp_path / "file"
    live.mkdir()
    link.symlink_to(live, target_is_directory=True)
    afile.write_text("x")
    bindings = [{"path": str(p)} for p in (afile, live, tmp_path / "none", link)]
    found = repos.partition(bindings)
    assert [b["path"] for b in found.live] == [str(live), str(link)]
    assert [b["path"] for b in found.missing] == [str(afile), str(tmp_path / "none")]


def test_guard_reraises_when_the_path_still_exists(tmp_path: Path) -> None:
    def boom(path: Path) -> str:
        raise stamp.GitError("boom")

    with pytest.raises(stamp.GitError):
        repos.guard({"path": str(tmp_path)}, boom)
    gone = tmp_path / "gone"
    with pytest.raises(stamp.GitError):
        repos.guard({"path": str(gone)}, boom)

    def denied(path: Path) -> str:
        raise PermissionError(13, "denied", str(tmp_path / "store"))

    with pytest.raises(PermissionError):
        repos.guard({"path": str(gone)}, denied)

    def enoent(path: Path) -> str:
        raise stamp.GitError("git x") from FileNotFoundError(2, "no", str(gone))

    assert repos.guard({"path": str(gone)}, enoent) is None


def test_code_stamp_with_carried_entry_keeps_the_key(tmp_path: Path) -> None:
    path = _new_repo(tmp_path, "a")
    binding = {"path": str(path)}
    before = stamp.code_stamp([binding], "digest")
    shutil.rmtree(path)
    after = stamp.code_stamp([binding], "digest", carried=before["repos"])
    assert after["key"] == before["key"] and after["repos"][0]["missing"] is True
    assert stamp.code_stamp([binding], "digest")["repos"] == []


def test_on_live_only_translates_failures_caused_by_the_vanished_path(tmp_path: Path) -> None:
    gone, alive = tmp_path / "gone", tmp_path / "alive"
    alive.mkdir()

    def denied() -> None:
        raise PermissionError(13, "denied", str(tmp_path / "store"))

    with pytest.raises(PermissionError):
        repos.on_live([gone], denied)

    def broken() -> None:
        raise RuntimeError("lease store failure")

    with pytest.raises(RuntimeError, match="lease store"):
        repos.on_live([gone, alive], broken)

    def interrupted() -> None:
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        repos.on_live([gone], interrupted)

    def missing_cwd() -> None:
        raise stamp.GitError("git x") from FileNotFoundError(2, "no", str(gone))

    with pytest.raises(ValueError, match=GONE):
        repos.on_live([gone], missing_cwd)
    with pytest.raises(ValueError, match="vanished during the command") as survivor:
        repos.on_live([gone, alive], missing_cwd)
    assert GONE not in str(survivor.value)
