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


def test_changed_files_preserves_paths_with_spaces(repo: Path) -> None:
    spaced_dir = repo / "dir with spaces"
    spaced_dir.mkdir()
    committed = spaced_dir / "committed file.txt"
    committed.write_text("c")
    _git(repo, "add", str(committed))
    _git(repo, "commit", "-q", "-m", "spaced")
    untracked = spaced_dir / "untracked file.txt"
    untracked.write_text("u")
    assert changes.changed_files(repo) == [
        "dir with spaces/committed file.txt",
        "dir with spaces/untracked file.txt",
    ]


def test_fingerprint_changes_with_untracked_content(repo: Path) -> None:
    first = changes.tree_fingerprint(repo)
    assert changes.tree_fingerprint(repo) == first
    (repo / "u.txt").write_text("1")
    second = changes.tree_fingerprint(repo)
    (repo / "u.txt").write_text("2")
    assert len({first, second, changes.tree_fingerprint(repo)}) == 3


def test_check_caches_passing_tree(repo: Path, monkeypatch, capsys) -> None:
    calls: list[tuple[str, str | None]] = []

    def fake_gate(root, scope="all", skip=None, output="errors", capture=None, **_):
        calls.append((scope, skip))
        capture.append("all good")
        return 0

    monkeypatch.setattr(check_cli, "run_quality_gate", fake_gate)
    assert check_cli.check(["--dir", str(repo), "--changed", "--cache", "--json"]) == 0
    first = json.loads(capsys.readouterr().out)
    assert first["status"] == "passed" and calls == [("changed", None)]

    # Same scope/skip hits the cache:
    assert check_cli.check(["--dir", str(repo), "--changed", "--cache", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "skipped"
    assert calls == [("changed", None)]

    # Full run (scope="all") must NOT be skipped after only a --changed pass:
    assert check_cli.check(["--dir", str(repo), "--cache", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "passed"
    assert calls == [("changed", None), ("all", None)]

    # Repeat of full run hits the cache:
    assert check_cli.check(["--dir", str(repo), "--cache", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "skipped"
    assert len(calls) == 2

    (repo / "a.txt").write_text("edited")
    check_cli.check(["--dir", str(repo), "--cache"])
    assert len(calls) == 3

    # A run with --skip or QG_SKIP must not satisfy a subsequent run without skip:
    (repo / "a.txt").write_text("edited again")
    assert check_cli.check(["--dir", str(repo), "--skip", "tests", "--cache", "--json"]) == 0
    capsys.readouterr()
    assert check_cli.check(["--dir", str(repo), "--cache", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "passed"

    (repo / "a.txt").write_text("edited with env skip")
    monkeypatch.setenv("QG_SKIP", "tests")
    assert check_cli.check(["--dir", str(repo), "--changed", "--cache", "--json"]) == 0
    capsys.readouterr()
    monkeypatch.delenv("QG_SKIP", raising=False)
    assert check_cli.check(["--dir", str(repo), "--changed", "--cache", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "passed"

    # A broken .workspace/config.toml must not crash ws check; it runs uncached:
    cfg = repo / ".workspace"
    cfg.mkdir()
    (cfg / "config.toml").write_text("not = [valid toml", encoding="utf-8")
    assert check_cli.check(["--dir", str(repo), "--changed", "--cache", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "passed"


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


def test_check_surfaces_warnings_when_gate_passes(repo: Path, monkeypatch, capsys) -> None:
    def passing_with_warn(root, capture=None, **_):
        capture.append("⚠  gitleaks is not installed, skipping.\n🚀 All good.")
        return 0

    monkeypatch.setattr(check_cli, "run_quality_gate", passing_with_warn)
    assert check_cli.check(["--dir", str(repo), "--changed", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "passed"
    assert "✓ gate: passed" in payload["text"]
    assert "⚠  gitleaks is not installed" in payload["text"]


def _write_failing_and_passing_python_repo(repo: Path, fake_home: Path) -> None:
    """Commits an unrelated file on HEAD so HEAD~1..HEAD has no Python files."""
    (repo / "notes.md").write_text("unrelated commit\n", encoding="utf-8")
    _git(repo, "add", "notes.md")
    _git(repo, "commit", "-q", "-m", "docs: add notes")
    (repo / "pyproject.toml").write_text('[project]\nname = "demo"\n', encoding="utf-8")
    pytest_bin = repo / ".venv" / "bin" / "pytest"
    pytest_bin.parent.mkdir(parents=True)
    pytest_bin.write_text(
        '#!/bin/sh\nfor f in "$@"; do\n'
        '  case "$f" in *test_uncommitted.py) grep -q "PASS" "$f" || exit 1 ;; esac\n'
        "done\nexit 0\n",
        encoding="utf-8",
    )
    pytest_bin.chmod(0o755)
    fake_home.mkdir(exist_ok=True)


def test_check_changed_validates_uncommitted_files_end_to_end(
    repo: Path, tmp_path: Path, monkeypatch, capsys
) -> None:
    """Real run_quality_gate (no mock) catches uncommitted failures outside HEAD~1..HEAD."""
    fake_home = tmp_path / "home"
    _write_failing_and_passing_python_repo(repo, fake_home)
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("WORKSPACE_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("QG_SKIP", "gitleaks,commits,lint,design")

    test_file = repo / "test_uncommitted.py"
    test_file.write_text("def test_fail(): assert False\n", encoding="utf-8")
    assert check_cli.check(["--dir", str(repo), "--changed", "--cache", "--json"]) == 1
    failed = json.loads(capsys.readouterr().out)
    assert failed["status"] == "failed"

    test_file.write_text("# PASS\ndef test_ok(): assert True\n", encoding="utf-8")
    assert check_cli.check(["--dir", str(repo), "--changed", "--cache", "--json"]) == 0
    passed = json.loads(capsys.readouterr().out)
    assert passed["status"] == "passed"
    assert check_cli.check(["--dir", str(repo), "--changed", "--cache", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "skipped"


def test_record_cache_cleans_up_temp_file_on_replace_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    marker = tmp_path / ".git" / "ws-check-pass"

    def fail_replace(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(check_cli.os, "replace", fail_replace)
    with pytest.raises(OSError, match="disk full"):
        check_cli._record_cache(marker, "key1")
    assert list(marker.parent.glob(".check-pass-*")) == []
