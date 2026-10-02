import json
import os
import subprocess
from pathlib import Path

import pytest
from workspace_engine.cli import check as check_cli
from workspace_engine.services import changes


def _git(root: Path, *args: str) -> None:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(
        GIT_CONFIG_GLOBAL="/dev/null",
        GIT_AUTHOR_NAME="t",
        GIT_AUTHOR_EMAIL="t@e.x",
        GIT_COMMITTER_NAME="t",
        GIT_COMMITTER_EMAIL="t@e.x",
    )
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, env=env)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    (root / "a.txt").write_text("a")
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "init")
    _git(root, "checkout", "-q", "-b", "feature")
    return root


def test_changed_files_includes_commits_and_working_tree(repo: Path) -> None:
    (repo / "b.txt").write_text("b")
    _git(repo, "add", "b.txt")
    _git(repo, "commit", "-q", "-m", "b")
    (repo / "a.txt").write_text("changed")
    (repo / "new.txt").write_text("n")
    assert changes.changed_files(repo) == ["a.txt", "b.txt", "new.txt"]


def test_fingerprint_changes_with_untracked_content(repo: Path) -> None:
    first = changes.tree_fingerprint(repo)
    assert changes.tree_fingerprint(repo) == first
    (repo / "u.txt").write_text("1")
    second = changes.tree_fingerprint(repo)
    (repo / "u.txt").write_text("2")
    assert len({first, second, changes.tree_fingerprint(repo)}) == 3


def test_check_caches_passing_tree(repo: Path, monkeypatch, capsys) -> None:
    calls: list[str] = []

    def fake_gate(root, scope="all", skip=None, output="errors", capture=None, **_):
        calls.append(scope)
        capture.append("all good")
        return 0

    monkeypatch.setattr(check_cli, "run_quality_gate", fake_gate)
    assert check_cli.check(["--dir", str(repo), "--changed", "--cache", "--json"]) == 0
    first = json.loads(capsys.readouterr().out)
    assert first["status"] == "passed" and calls == ["changed"]

    assert check_cli.check(["--dir", str(repo), "--cache", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "skipped"
    assert calls == ["changed"]

    (repo / "a.txt").write_text("edited")
    check_cli.check(["--dir", str(repo), "--cache"])
    assert len(calls) == 2


def test_check_failure_is_condensed_with_log(repo: Path, monkeypatch, capsys) -> None:
    noise = "\n".join(f"step {i} ok" for i in range(500))

    def failing_gate(root, capture=None, **_):
        capture.append(f"{noise}\nERROR: tests failed in test_x\n{noise}")
        return 1

    monkeypatch.setenv("WORKSPACE_LOG_DIR", str(repo.parent / "logs"))
    monkeypatch.setattr(check_cli, "run_quality_gate", failing_gate)
    assert check_cli.check(["--dir", str(repo), "--budget", "800"]) == 1
    out = capsys.readouterr().out
    assert "tests failed in test_x" in out and "ws log " in out
    assert len(out) < 1000


def test_changed_cli_json_and_text(repo: Path, capsys) -> None:
    (repo / "x.txt").write_text("x")
    assert check_cli.changed(["--dir", str(repo), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["files"] == ["x.txt"]
    assert check_cli.changed(["--dir", str(repo)]) == 0
    assert capsys.readouterr().out.strip() == "x.txt"


def test_base_ref_without_default_branch(tmp_path: Path) -> None:
    root = tmp_path / "solo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "trunk")
    assert changes.base_ref(root) is None


def test_check_skip_help_lists_the_gate_stages(capsys):
    from workspace_engine.services.git_hooks import QG_STAGES

    with pytest.raises(SystemExit):
        check_cli.check(["--help"])
    help_text = " ".join(capsys.readouterr().out.split())
    assert f"Stages to skip: {','.join(QG_STAGES)}" in help_text
