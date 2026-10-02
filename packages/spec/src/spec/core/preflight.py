from __future__ import annotations

import contextlib
import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from spec.core.paths import PathBoundary
from spec.core.result import CheckStatus
from spec.spec.workflow import Workflow
from spec.verify.engine import VerificationEngine, load_checks


@dataclass(frozen=True)
class BranchInfo:
    current_branch: str
    local_branches: list[str]
    remote_branches: list[str]


@dataclass(frozen=True)
class BaselineGateResult:
    passed: bool
    status: str
    summary: str
    evidence_path: str | None
    checks_total: int
    checks_passed: int


class PreflightError(Exception):
    """Raised when pre-flight validation, sync, or baseline checks fail."""


class PreflightManager:
    """Agnostic pre-flight manager: branch sync, baseline gate check, and Git worktree provisioning."""

    def __init__(self, root: str | Path) -> None:
        self.boundary = PathBoundary(root)
        self.root = self.boundary.root

    def _run_git(self, *args: str) -> tuple[int, str, str]:
        cmd = ["git", "-C", str(self.root), *args]
        git_env = dict(os.environ)
        if "GIT_CONFIG_GLOBAL" not in git_env:
            git_env["GIT_CONFIG_GLOBAL"] = "/dev/null"
        if "GIT_CONFIG_SYSTEM" not in git_env:
            git_env["GIT_CONFIG_SYSTEM"] = "/dev/null"
        res = subprocess.run(cmd, capture_output=True, text=True, env=git_env)
        return res.returncode, res.stdout.strip(), res.stderr.strip()

    def resolve_branches(self) -> BranchInfo:
        """Dynamically inspects local and remote branches in the repository."""
        code, current, _ = self._run_git("branch", "--show-current")
        curr = current if code == 0 and current else "HEAD"

        code, local_out, _ = self._run_git("branch", "--format=%(refname:short)")
        local_branches = (
            [b.strip() for b in local_out.splitlines() if b.strip()] if code == 0 else []
        )

        code, remote_out, _ = self._run_git("branch", "-r", "--format=%(refname:short)")
        remote_branches = (
            [
                b.strip().removeprefix("origin/")
                for b in remote_out.splitlines()
                if b.strip() and not b.strip().endswith("/HEAD")
            ]
            if code == 0
            else []
        )

        return BranchInfo(
            current_branch=curr,
            local_branches=sorted(set(local_branches)),
            remote_branches=sorted(set(remote_branches)),
        )

    def sync_base_branch(self, base_branch: str) -> None:
        """Fetches and fast-forwards the base branch safely."""
        # 1. Fetch remote tracking for base branch if remote exists
        code, remotes, _ = self._run_git("remote")
        if code == 0 and "origin" in remotes.split():
            fetch_code, _, fetch_err = self._run_git("fetch", "origin", base_branch)
            if fetch_code != 0:
                # Non-fatal if branch is strictly local
                pass

        # 2. If current branch is base branch, try fast-forward pull
        code, current, _ = self._run_git("branch", "--show-current")
        if code == 0 and current == base_branch:
            # Verify working tree is clean before pull
            code_diff, diff_out, _ = self._run_git("status", "--porcelain")
            if code_diff == 0 and not diff_out:
                self._run_git("pull", "--ff-only", "origin", base_branch)

    def run_baseline_gate(self, target_root: Path | None = None) -> BaselineGateResult:
        """Runs verification checks configured in .spec/verification.json on the base repository."""
        check_root = target_root or self.root
        config_path = check_root / ".spec" / "verification.json"
        if not config_path.is_file():
            return BaselineGateResult(
                passed=False,
                status="SKIPPED",
                summary="No verification checks configured in .spec/verification.json",
                evidence_path=None,
                checks_total=0,
                checks_passed=0,
            )

        checks = load_checks(check_root)
        if not checks:
            return BaselineGateResult(
                passed=False,
                status="SKIPPED",
                summary="No verification checks configured",
                evidence_path=None,
                checks_total=0,
                checks_passed=0,
            )

        engine = VerificationEngine(check_root)
        report = engine.run(checks)

        # Save structured baseline evidence on disk non-destructively
        evidence_dir = self.root / ".spec" / "evidence" / "preflight"
        evidence_dir.mkdir(parents=True, exist_ok=True)
        content = json.dumps(report.to_dict(), indent=2) + "\n"

        now = datetime.now(UTC)
        timestamp = now.strftime("%Y%m%d-%H%M%S")
        timestamped_file = evidence_dir / f"baseline-{timestamp}.json"
        if timestamped_file.exists():
            timestamp = f"{timestamp}-{now.strftime('%f')}"
            timestamped_file = evidence_dir / f"baseline-{timestamp}.json"
        if timestamped_file.exists():
            timestamp = f"{timestamp}-{uuid4().hex[:6]}"
            timestamped_file = evidence_dir / f"baseline-{timestamp}.json"

        timestamped_file.write_text(content, encoding="utf-8")

        latest_baseline = evidence_dir / "latest_baseline.json"
        latest_baseline.unlink(missing_ok=True)
        try:
            latest_baseline.symlink_to(timestamped_file.name)
        except OSError:
            latest_baseline.write_text(content, encoding="utf-8")

        evidence_file = evidence_dir / "baseline.json"
        evidence_file.unlink(missing_ok=True)
        try:
            evidence_file.symlink_to(timestamped_file.name)
        except OSError:
            evidence_file.write_text(content, encoding="utf-8")

        passed_count = sum(1 for c in report.checks if c.status is CheckStatus.PASS)
        total_count = len(report.checks)
        passed = report.status is CheckStatus.PASS

        summary = (
            f"{passed_count}/{total_count} checks passed"
            if passed
            else f"FAIL: {total_count - passed_count} checks failed"
        )

        return BaselineGateResult(
            passed=passed,
            status=report.status.value,
            summary=summary,
            evidence_path=str(timestamped_file),
            checks_total=total_count,
            checks_passed=passed_count,
        )

    def has_tracked_changes(self) -> bool:
        """Reports staged or unstaged edits to tracked files; untracked files do not count."""
        code, status_out, _ = self._run_git("status", "--porcelain", "--untracked-files=no")
        return code == 0 and bool(status_out)

    def switch_branch(self, branch: str, base_branch: str) -> None:
        """Switches the current checkout to the branch, creating it from the base if missing."""
        code, _, _ = self._run_git("rev-parse", "--verify", "--quiet", f"refs/heads/{branch}")
        switch_args = ("switch", branch) if code == 0 else ("switch", "-c", branch, base_branch)
        code, stdout, stderr = self._run_git(*switch_args)
        if code != 0:
            raise PreflightError(f"Failed to switch to branch '{branch}': {stderr or stdout}")

    def run_base_branch_baseline(self, base_branch: str) -> BaselineGateResult:
        """Runs the baseline gate on a temporary detached checkout of another base branch."""
        base_dir = Path(tempfile.mkdtemp(prefix="spec-baseline-"))
        try:
            code, stdout, stderr = self._run_git(
                "worktree", "add", "--detach", str(base_dir), base_branch
            )
            if code != 0:
                raise PreflightError(
                    f"Base branch '{base_branch}' cannot be checked out: {stderr or stdout}"
                )
            try:
                self._copy_missing_config(base_dir)
                self._link_local_environment(base_dir)
                return self.run_baseline_gate(target_root=base_dir)
            finally:
                self._run_git("worktree", "remove", "--force", str(base_dir))
        finally:
            shutil.rmtree(base_dir, ignore_errors=True)

    def _copy_missing_config(self, dest_root: Path) -> None:
        """Copies local configuration the checkout at dest_root does not already track."""
        for pattern in [".spec", ".agents"]:
            src = self.root / pattern
            dest = dest_root / pattern
            if not src.exists() or dest.exists():
                continue
            if src.is_dir():
                shutil.copytree(src, dest)
            else:
                shutil.copy2(src, dest)

    def _link_local_environment(self, dest_root: Path) -> None:
        """Copies .env* files and symlinks dependency folders so checks run as in the main checkout."""
        # Copy env files if present
        for env_file in self.root.glob(".env*"):
            if env_file.is_file():
                shutil.copy2(env_file, dest_root / env_file.name)

        # Create relative symlinks for heavy gitignored dependencies if they exist (.venv, node_modules)
        dep_folders = [
            Path(".venv"),
            Path("node_modules"),
            Path("backend/.venv"),
            Path("frontend/node_modules"),
            Path(".gradle"),
        ]
        for dep in dep_folders:
            src = self.root / dep
            target = dest_root / dep
            if not src.is_dir() or target.exists():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            # Relative link from target back to src; without symlink support the checks
            # simply run without the cached dependencies.
            with contextlib.suppress(OSError):
                os.symlink(os.path.relpath(src, target.parent), target)

    def prepare_target(self, branch: str, base_branch: str, *, use_worktree: bool) -> Path:
        """Returns the directory to work in: a new worktree, or the current checkout on the branch."""
        if use_worktree:
            return self.provision_worktree(branch, base_branch)
        self.switch_branch(branch, base_branch)
        return self.root

    def provision_worktree(self, branch: str, base_branch: str) -> Path:
        """Provisions an isolated Git Worktree and links local dependency/config caches."""
        sanitized = branch.replace("/", "-")
        worktree_dir = self.root.parent / f"workspace-{sanitized}"

        if worktree_dir.exists():
            raise PreflightError(f"Target worktree directory already exists: {worktree_dir}")

        # 1. Create worktree
        code, stdout, stderr = self._run_git(
            "worktree", "add", "-b", branch, str(worktree_dir), base_branch
        )
        if code != 0:
            # Fallback if local branch already exists
            code, stdout, stderr = self._run_git("worktree", "add", str(worktree_dir), branch)
            if code != 0:
                raise PreflightError(f"Failed to create Git worktree: {stderr or stdout}")

        # 2. Copy configuration files (.spec/, .agents/, .env*)
        config_patterns = [".spec", ".agents"]
        for pattern in config_patterns:
            src = self.root / pattern
            if src.exists():
                dest = worktree_dir / pattern
                if src.is_dir():
                    shutil.copytree(src, dest, dirs_exist_ok=True)
                else:
                    shutil.copy2(src, dest)

        # 3. Copy env files and link heavy gitignored dependencies
        self._link_local_environment(worktree_dir)

        return worktree_dir

    def run(
        self,
        name: str,
        *,
        base_branch: str | None = None,
        branch: str | None = None,
        use_worktree: bool = True,
        description: str = "",
    ) -> dict[str, Any]:
        """Executes the full agnostic preflight lifecycle."""
        # 1. Resolve base branch
        branch_info = self.resolve_branches()
        base = base_branch or branch_info.current_branch
        target_branch = branch or f"feature/{name.lower().replace(' ', '-')}"
        if not use_worktree and self.has_tracked_changes():
            return {
                "status": "FAIL",
                "error": f"Working tree has uncommitted changes; commit or stash them before preflight switches to '{target_branch}'",
            }

        # 2. Sync base branch
        self.sync_base_branch(base)

        # 3. Baseline verification gate on selected base
        try:
            baseline = (
                self.run_baseline_gate()
                if base == branch_info.current_branch
                else self.run_base_branch_baseline(base)
            )
        except PreflightError as exc:
            return {"status": "FAIL", "error": str(exc)}

        if not baseline.passed:
            return {
                "status": "FAIL",
                "error": f"Baseline verification checks failed on base branch '{base}': {baseline.summary}",
                "evidence_path": baseline.evidence_path,
                "checks_passed": baseline.checks_passed,
                "checks_total": baseline.checks_total,
                "baseline": baseline.status,
            }

        # 4. Provision worktree or switch the current checkout to the feature branch
        try:
            target_root = self.prepare_target(target_branch, base, use_worktree=use_worktree)
        except PreflightError as exc:
            return {"status": "FAIL", "error": str(exc), "baseline": baseline.status}

        # 5. Initialize spec inside target root
        workflow = Workflow(target_root)
        snapshot = workflow.create_spec(name, description)

        return {
            "status": "READY",
            "feature": snapshot.feature,
            "stage": snapshot.stage.value,
            "base_branch": base,
            "branch": target_branch,
            "worktree_path": str(target_root),
            "baseline": "PASS",
        }
