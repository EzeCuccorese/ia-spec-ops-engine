from __future__ import annotations

import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest
import spec.core.preflight as preflight_module
from spec.cli import main
from spec.core.preflight import PreflightError, PreflightManager
from spec.governance.project import ProjectGovernance


def _init_git_repo(path: Path) -> None:
    git_env = dict(os.environ)
    git_env["GIT_CONFIG_GLOBAL"] = "/dev/null"
    git_env["GIT_CONFIG_SYSTEM"] = "/dev/null"
    subprocess.run(
        ["git", "init", "-b", "main", str(path)], check=True, capture_output=True, env=git_env
    )
    subprocess.run(
        ["git", "-C", str(path), "config", "user.name", "Test User"], check=True, env=git_env
    )
    subprocess.run(
        ["git", "-C", str(path), "config", "user.email", "test@example.com"],
        check=True,
        env=git_env,
    )
    (path / "README.md").write_text("Hello", encoding="utf-8")
    subprocess.run(["git", "-C", str(path), "add", "README.md"], check=True, env=git_env)
    subprocess.run(
        ["git", "-C", str(path), "commit", "-m", "initial commit"], check=True, env=git_env
    )


def test_resolve_branches(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    mgr = PreflightManager(tmp_path)
    info = mgr.resolve_branches()
    assert info.current_branch == "main"
    assert "main" in info.local_branches


def test_baseline_gate_skipped_when_no_verification_config(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    ProjectGovernance(tmp_path).initialize()

    mgr = PreflightManager(tmp_path)
    res = mgr.run("Sample Feature", use_worktree=False)

    assert res["status"] == "FAIL"
    assert res["baseline"] == "SKIPPED"
    assert "No verification checks configured" in res["error"]


def test_baseline_gate_aborts_on_failure(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    ProjectGovernance(tmp_path).initialize()

    # Configure a failing check in .spec/verification.json
    v_config = {
        "schema_version": 1,
        "checks": [
            {
                "id": "failing-check",
                "command": ["false"],
                "required": True,
            }
        ],
    }
    (tmp_path / ".spec" / "verification.json").write_text(json.dumps(v_config), encoding="utf-8")

    mgr = PreflightManager(tmp_path)
    res = mgr.run("Broken Feature", use_worktree=False)

    assert res["status"] == "FAIL"
    assert "Baseline verification checks failed" in res["error"]
    assert res["checks_passed"] == 0
    assert res["checks_total"] == 1
    # Verify no spec was created
    assert not (tmp_path / ".spec" / "specs" / "broken-feature").exists()


def test_baseline_gate_passes_and_provisions_worktree(tmp_path: Path) -> None:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    _init_git_repo(repo_dir)
    ProjectGovernance(repo_dir).initialize()

    # Configure a passing check
    v_config = {
        "schema_version": 1,
        "checks": [
            {
                "id": "passing-check",
                "command": ["true"],
                "required": True,
            }
        ],
    }
    (repo_dir / ".spec" / "verification.json").write_text(json.dumps(v_config), encoding="utf-8")

    # Create dummy .env and .venv to test symlink and copy
    (repo_dir / ".env").write_text("FOO=bar", encoding="utf-8")
    (repo_dir / ".venv").mkdir()
    (repo_dir / ".venv" / "bin").mkdir()

    mgr = PreflightManager(repo_dir)
    res = mgr.run("Payment Gateway", branch="feature/payment-gw", use_worktree=True)

    assert res["status"] == "READY"
    assert res["feature"] == "payment-gateway"
    assert res["baseline"] == "PASS"

    worktree_path = Path(res["worktree_path"])
    assert worktree_path.exists()
    assert (worktree_path / ".spec" / "specs" / "payment-gateway" / "spec.md").exists()
    assert (worktree_path / ".env").exists()
    # Check that .venv symlink was created
    assert (worktree_path / ".venv").is_symlink()


def test_cli_preflight_command(tmp_path: Path, capsys) -> None:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    _init_git_repo(repo_dir)
    ProjectGovernance(repo_dir).initialize()

    v_config = {
        "schema_version": 1,
        "checks": [
            {
                "id": "passing-check",
                "command": ["true"],
                "required": True,
            }
        ],
    }
    (repo_dir / ".spec" / "verification.json").write_text(json.dumps(v_config), encoding="utf-8")

    with pytest.raises(SystemExit) as exc:
        main(["preflight", "CLI Feature", "--no-worktree", "--root", str(repo_dir), "--json"])
    assert exc.value.code == 0

    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["status"] == "READY"
    assert payload["feature"] == "cli-feature"
    assert payload["baseline"] == "PASS"


def test_cli_preflight_has_no_worktree_flag(tmp_path: Path, capsys) -> None:
    """A worktree is the default; only --no-worktree changes it."""
    with pytest.raises(SystemExit) as exc:
        main(["preflight", "Flag Feature", "--worktree", "--root", str(tmp_path)])
    assert exc.value.code == 2
    assert "--worktree" in capsys.readouterr().err


def test_cli_preflight_command_rejects_empty_checks(tmp_path: Path, capsys) -> None:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    _init_git_repo(repo_dir)
    ProjectGovernance(repo_dir).initialize()

    v_config = {
        "schema_version": 1,
        "checks": [],
    }
    (repo_dir / ".spec" / "verification.json").write_text(json.dumps(v_config), encoding="utf-8")

    with pytest.raises(SystemExit) as exc:
        main(["preflight", "Empty Feature", "--no-worktree", "--root", str(repo_dir), "--json"])
    assert exc.value.code == 1

    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["status"] == "FAIL"
    assert payload["baseline"] == "SKIPPED"


def test_cli_preflight_command_plain_text_ready(tmp_path: Path, capsys) -> None:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    _init_git_repo(repo_dir)
    ProjectGovernance(repo_dir).initialize()

    v_config = {
        "schema_version": 1,
        "checks": [{"id": "passing-check", "command": ["true"], "required": True}],
    }
    (repo_dir / ".spec" / "verification.json").write_text(json.dumps(v_config), encoding="utf-8")

    with pytest.raises(SystemExit) as exc:
        main(["preflight", "Plain Feature", "--no-worktree", "--root", str(repo_dir)])
    assert exc.value.code == 0

    out = capsys.readouterr().out
    assert "Preflight READY: feature 'plain-feature' initialized" in out
    assert "Worktree:" in out
    assert "Branch:" in out
    assert "Baseline: PASS" in out


def test_cli_preflight_command_plain_text_fail(tmp_path: Path, capsys) -> None:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    _init_git_repo(repo_dir)
    ProjectGovernance(repo_dir).initialize()

    v_config = {
        "schema_version": 1,
        "checks": [{"id": "failing-check", "command": ["false"], "required": True}],
    }
    (repo_dir / ".spec" / "verification.json").write_text(json.dumps(v_config), encoding="utf-8")

    with pytest.raises(SystemExit) as exc:
        main(["preflight", "Plain Fail Feature", "--no-worktree", "--root", str(repo_dir)])
    assert exc.value.code == 1

    out = capsys.readouterr().out
    assert "Preflight FAIL:" in out
    assert "Evidence:" in out


def test_cli_preflight_command_plain_text_fail_without_evidence(tmp_path: Path, capsys) -> None:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    _init_git_repo(repo_dir)
    ProjectGovernance(repo_dir).initialize()

    v_config = {"schema_version": 1, "checks": []}
    (repo_dir / ".spec" / "verification.json").write_text(json.dumps(v_config), encoding="utf-8")

    with pytest.raises(SystemExit) as exc:
        main(["preflight", "Plain Skip Feature", "--no-worktree", "--root", str(repo_dir)])
    assert exc.value.code == 1

    out = capsys.readouterr().out
    assert "Preflight FAIL:" in out


def test_baseline_gate_records_non_destructive_evidence(tmp_path: Path) -> None:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    _init_git_repo(repo_dir)
    ProjectGovernance(repo_dir).initialize()

    v_config = {
        "schema_version": 1,
        "checks": [
            {
                "id": "passing-check",
                "command": ["true"],
                "required": True,
            }
        ],
    }
    (repo_dir / ".spec" / "verification.json").write_text(json.dumps(v_config), encoding="utf-8")

    mgr = PreflightManager(repo_dir)
    gate_res1 = mgr.run_baseline_gate()
    assert gate_res1.passed is True

    evidence_dir = repo_dir / ".spec" / "evidence" / "preflight"
    assert (evidence_dir / "baseline.json").is_file()
    timestamped_initial = list(evidence_dir.glob("baseline-*.json"))
    assert len(timestamped_initial) == 1

    gate_res2 = mgr.run_baseline_gate()
    assert gate_res2.passed is True
    assert (evidence_dir / "baseline.json").is_file()
    timestamped_subsequent = list(evidence_dir.glob("baseline-*.json"))
    assert len(timestamped_subsequent) == 2


def _git_env() -> dict[str, str]:
    git_env = dict(os.environ)
    git_env["GIT_CONFIG_GLOBAL"] = "/dev/null"
    git_env["GIT_CONFIG_SYSTEM"] = "/dev/null"
    return git_env


def test_baseline_gate_skipped_when_verification_file_is_missing(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)

    mgr = PreflightManager(tmp_path)
    result = mgr.run_baseline_gate()

    assert result.passed is False
    assert result.status == "SKIPPED"
    assert "No verification checks configured in .spec/verification.json" in result.summary


def test_run_git_keeps_preexisting_git_config_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _init_git_repo(tmp_path)
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/existing/global")
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", "/existing/system")

    mgr = PreflightManager(tmp_path)
    code, _out, _err = mgr._run_git("branch", "--show-current")

    assert code == 0


def test_sync_base_branch_fetch_failure_is_non_fatal(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    subprocess.run(
        ["git", "-C", str(tmp_path), "remote", "add", "origin", "/nonexistent/origin"],
        check=True,
        env=_git_env(),
    )

    mgr = PreflightManager(tmp_path)
    # Should not raise even though the fetch and the fast-forward pull both fail.
    mgr.sync_base_branch("main")


def test_sync_base_branch_fetch_success_then_pulls_clean_tree(tmp_path: Path) -> None:
    upstream = tmp_path / "upstream"
    upstream.mkdir()
    _init_git_repo(upstream)

    clone_dir = tmp_path / "clone"
    subprocess.run(
        ["git", "clone", str(upstream), str(clone_dir)],
        check=True,
        env=_git_env(),
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(clone_dir), "config", "user.name", "Test User"],
        check=True,
        env=_git_env(),
    )
    subprocess.run(
        ["git", "-C", str(clone_dir), "config", "user.email", "test@example.com"],
        check=True,
        env=_git_env(),
    )

    mgr = PreflightManager(clone_dir)
    # Fetch succeeds (real origin, real branch); tree is clean, so the fast-forward
    # pull is attempted too.
    mgr.sync_base_branch("main")


def test_provision_worktree_raises_when_target_directory_exists(tmp_path: Path) -> None:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    _init_git_repo(repo_dir)
    (repo_dir.parent / "workspace-feature-taken").mkdir()

    mgr = PreflightManager(repo_dir)
    with pytest.raises(PreflightError, match="already exists"):
        mgr.provision_worktree("feature/taken", "main")


def test_provision_worktree_falls_back_when_branch_already_exists(tmp_path: Path) -> None:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    _init_git_repo(repo_dir)
    subprocess.run(
        ["git", "-C", str(repo_dir), "branch", "feature/exists"], check=True, env=_git_env()
    )

    mgr = PreflightManager(repo_dir)
    worktree_dir = mgr.provision_worktree("feature/exists", "main")

    assert worktree_dir.is_dir()


def test_provision_worktree_raises_when_both_attempts_fail(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    _init_git_repo(repo_dir)

    mgr = PreflightManager(repo_dir)
    monkeypatch.setattr(mgr, "_run_git", lambda *args: (1, "", "boom"))

    with pytest.raises(PreflightError, match="Failed to create Git worktree"):
        mgr.provision_worktree("feature/broken", "main")


def test_provision_worktree_copies_file_config_pattern(tmp_path: Path) -> None:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    _init_git_repo(repo_dir)
    (repo_dir / ".agents").write_text("agent config", encoding="utf-8")

    mgr = PreflightManager(repo_dir)
    worktree_dir = mgr.provision_worktree("feature/file-pattern", "main")

    copied = worktree_dir / ".agents"
    assert copied.is_file()
    assert copied.read_text(encoding="utf-8") == "agent config"


def test_provision_worktree_skips_non_file_env_glob_matches(tmp_path: Path) -> None:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    _init_git_repo(repo_dir)
    (repo_dir / ".envdir").mkdir()

    mgr = PreflightManager(repo_dir)
    worktree_dir = mgr.provision_worktree("feature/env-dir", "main")

    assert not (worktree_dir / ".envdir").exists()


def test_provision_worktree_skips_symlink_when_target_already_present(tmp_path: Path) -> None:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    _init_git_repo(repo_dir)
    (repo_dir / ".venv").mkdir()
    (repo_dir / ".venv" / "bin").mkdir()

    mgr = PreflightManager(repo_dir)
    expected_target = repo_dir.parent / "workspace-feature-collide" / ".venv"
    original_exists = Path.exists

    def fake_exists(self: Path) -> bool:
        if self == expected_target:
            return True
        return original_exists(self)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(Path, "exists", fake_exists)
        worktree_dir = mgr.provision_worktree("feature/collide", "main")

    assert worktree_dir == repo_dir.parent / "workspace-feature-collide"
    assert not (worktree_dir / ".venv" / "bin").exists()


def test_provision_worktree_ignores_symlink_os_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    _init_git_repo(repo_dir)
    (repo_dir / ".venv").mkdir()
    (repo_dir / ".venv" / "bin").mkdir()

    def raising_symlink(*_args: object, **_kwargs: object) -> None:
        raise OSError("symlinks unsupported")

    monkeypatch.setattr(os, "symlink", raising_symlink)

    mgr = PreflightManager(repo_dir)
    worktree_dir = mgr.provision_worktree("feature/no-symlink", "main")

    assert not (worktree_dir / ".venv").exists()


def test_baseline_gate_timestamp_collision_falls_back_to_uuid(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    _init_git_repo(repo_dir)
    ProjectGovernance(repo_dir).initialize()
    v_config = {
        "schema_version": 1,
        "checks": [{"id": "passing-check", "command": ["true"], "required": True}],
    }
    (repo_dir / ".spec" / "verification.json").write_text(json.dumps(v_config), encoding="utf-8")

    fixed_now = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)

    class _FixedDatetime:
        @staticmethod
        def now(tz: object = None) -> datetime:
            return fixed_now

    evidence_dir = repo_dir / ".spec" / "evidence" / "preflight"
    evidence_dir.mkdir(parents=True)
    (evidence_dir / "baseline-20240101-120000.json").write_text("{}", encoding="utf-8")
    (evidence_dir / "baseline-20240101-120000-000000.json").write_text("{}", encoding="utf-8")

    monkeypatch.setattr(preflight_module, "datetime", _FixedDatetime)

    mgr = PreflightManager(repo_dir)
    result = mgr.run_baseline_gate()

    assert result.passed is True
    remaining = sorted(p.name for p in evidence_dir.glob("baseline-20240101-120000*.json"))
    assert len(remaining) == 3


def test_baseline_gate_falls_back_to_copy_when_symlink_unsupported(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    _init_git_repo(repo_dir)
    ProjectGovernance(repo_dir).initialize()
    v_config = {
        "schema_version": 1,
        "checks": [{"id": "passing-check", "command": ["true"], "required": True}],
    }
    (repo_dir / ".spec" / "verification.json").write_text(json.dumps(v_config), encoding="utf-8")

    def raising_symlink_to(self: Path, target: object, target_is_directory: bool = False) -> None:
        raise OSError("symlinks unsupported")

    monkeypatch.setattr(Path, "symlink_to", raising_symlink_to)

    mgr = PreflightManager(repo_dir)
    result = mgr.run_baseline_gate()

    assert result.passed is True
    evidence_dir = repo_dir / ".spec" / "evidence" / "preflight"
    assert (evidence_dir / "baseline.json").is_file()
    assert not (evidence_dir / "baseline.json").is_symlink()
    assert (evidence_dir / "latest_baseline.json").is_file()
    assert not (evidence_dir / "latest_baseline.json").is_symlink()


def test_run_with_different_base_branch_copies_config_into_baseline_worktree(
    tmp_path: Path,
) -> None:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    _init_git_repo(repo_dir)
    subprocess.run(["git", "-C", str(repo_dir), "branch", "other"], check=True, env=_git_env())
    ProjectGovernance(repo_dir).initialize()
    v_config = {
        "schema_version": 1,
        "checks": [{"id": "passing-check", "command": ["true"], "required": True}],
    }
    (repo_dir / ".spec" / "verification.json").write_text(json.dumps(v_config), encoding="utf-8")

    mgr = PreflightManager(repo_dir)
    result = mgr.run("Cross Base Feature", base_branch="other", use_worktree=False)

    assert result["status"] == "READY"
    assert result["base_branch"] == "other"


def test_run_with_different_base_branch_copies_file_config_pattern(tmp_path: Path) -> None:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    _init_git_repo(repo_dir)
    subprocess.run(["git", "-C", str(repo_dir), "branch", "other"], check=True, env=_git_env())
    ProjectGovernance(repo_dir).initialize()
    v_config = {
        "schema_version": 1,
        "checks": [{"id": "passing-check", "command": ["true"], "required": True}],
    }
    (repo_dir / ".spec" / "verification.json").write_text(json.dumps(v_config), encoding="utf-8")
    (repo_dir / ".agents").write_text("agent config", encoding="utf-8")

    mgr = PreflightManager(repo_dir)
    result = mgr.run("File Pattern Feature", base_branch="other", use_worktree=False)

    assert result["status"] == "READY"


def test_run_fails_when_base_branch_cannot_be_checked_out(tmp_path: Path) -> None:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    _init_git_repo(repo_dir)
    ProjectGovernance(repo_dir).initialize()
    v_config = {
        "schema_version": 1,
        "checks": [{"id": "passing-check", "command": ["true"], "required": True}],
    }
    (repo_dir / ".spec" / "verification.json").write_text(json.dumps(v_config), encoding="utf-8")

    mgr = PreflightManager(repo_dir)
    result = mgr.run("Ghost Base Feature", base_branch="ghost-branch", use_worktree=False)

    assert result["status"] == "FAIL"
    assert "Base branch 'ghost-branch' cannot be checked out" in result["error"]
    assert not (repo_dir / ".spec" / "evidence" / "preflight").exists()
    assert not (repo_dir / ".spec" / "specs" / "ghost-base-feature").exists()


def _passing_repo(tmp_path: Path) -> Path:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    _init_git_repo(repo_dir)
    ProjectGovernance(repo_dir).initialize()
    v_config = {
        "schema_version": 1,
        "checks": [{"id": "passing-check", "command": ["true"], "required": True}],
    }
    (repo_dir / ".spec" / "verification.json").write_text(json.dumps(v_config), encoding="utf-8")
    return repo_dir


def _current_branch(repo_dir: Path) -> str:
    return subprocess.run(
        ["git", "-C", str(repo_dir), "branch", "--show-current"],
        check=True,
        capture_output=True,
        text=True,
        env=_git_env(),
    ).stdout.strip()


def test_run_without_worktree_creates_and_switches_to_feature_branch(tmp_path: Path) -> None:
    repo_dir = _passing_repo(tmp_path)

    result = PreflightManager(repo_dir).run("Local Feature", use_worktree=False)

    assert result["status"] == "READY"
    assert result["branch"] == "feature/local-feature"
    assert _current_branch(repo_dir) == "feature/local-feature"


def test_run_without_worktree_creates_branch_from_selected_base(tmp_path: Path) -> None:
    repo_dir = _passing_repo(tmp_path)
    subprocess.run(["git", "-C", str(repo_dir), "branch", "other"], check=True, env=_git_env())
    (repo_dir / "main-only.txt").write_text("main", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo_dir), "add", "."], check=True, env=_git_env())
    subprocess.run(
        ["git", "-C", str(repo_dir), "commit", "-qm", "main only"], check=True, env=_git_env()
    )

    result = PreflightManager(repo_dir).run("Based", base_branch="other", use_worktree=False)

    assert result["status"] == "READY"
    assert _current_branch(repo_dir) == "feature/based"
    assert not (repo_dir / "main-only.txt").exists()


def test_run_without_worktree_switches_to_existing_branch(tmp_path: Path) -> None:
    repo_dir = _passing_repo(tmp_path)
    subprocess.run(
        ["git", "-C", str(repo_dir), "branch", "feature/again"], check=True, env=_git_env()
    )

    result = PreflightManager(repo_dir).run("Again", use_worktree=False)

    assert result["status"] == "READY"
    assert _current_branch(repo_dir) == "feature/again"


def test_run_without_worktree_fails_on_dirty_tree(tmp_path: Path) -> None:
    repo_dir = _passing_repo(tmp_path)
    (repo_dir / "README.md").write_text("uncommitted edit", encoding="utf-8")

    result = PreflightManager(repo_dir).run("Dirty Feature", use_worktree=False)

    assert result["status"] == "FAIL"
    assert "uncommitted changes" in result["error"]
    assert "feature/dirty-feature" in result["error"]
    assert _current_branch(repo_dir) == "main"
    assert not (repo_dir / ".spec" / "specs" / "dirty-feature").exists()
    assert not (repo_dir / ".spec" / "evidence" / "preflight").exists()


def test_run_without_worktree_fails_when_branch_cannot_be_created(tmp_path: Path) -> None:
    repo_dir = _passing_repo(tmp_path)
    subprocess.run(["git", "-C", str(repo_dir), "branch", "feature"], check=True, env=_git_env())

    result = PreflightManager(repo_dir).run("Nested", branch="feature/nested", use_worktree=False)

    assert result["status"] == "FAIL"
    assert "Failed to switch to branch 'feature/nested'" in result["error"]
    assert _current_branch(repo_dir) == "main"


def test_cli_preflight_reports_existing_worktree_directory_as_fail(tmp_path: Path, capsys) -> None:
    repo_dir = _passing_repo(tmp_path)
    (tmp_path / "workspace-feature-taken").mkdir()

    with pytest.raises(SystemExit) as exc:
        main(["preflight", "Taken", "--root", str(repo_dir), "--json"])
    assert exc.value.code == 1

    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "FAIL"
    assert "Target worktree directory already exists" in payload["error"]
