from __future__ import annotations

import json
import os
import shutil
import subprocess
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

    def run_baseline_gate(self) -> BaselineGateResult:
        """Runs verification checks configured in .spec/verification.json on the base repository."""
        config_path = self.root / ".spec" / "verification.json"
        if not config_path.is_file():
            return BaselineGateResult(
                passed=False,
                status="SKIPPED",
                summary="No verification checks configured in .spec/verification.json",
                evidence_path=None,
                checks_total=0,
                checks_passed=0,
            )

        checks = load_checks(self.root)
        if not checks:
            return BaselineGateResult(
                passed=False,
                status="SKIPPED",
                summary="No verification checks configured",
                evidence_path=None,
                checks_total=0,
                checks_passed=0,
            )

        engine = VerificationEngine(self.root)
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

        evidence_file = evidence_dir / "baseline.json"
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
            evidence_path=str(evidence_file),
            checks_total=total_count,
            checks_passed=passed_count,
        )

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

        # 2. Copy configuration files (.spec/, .specops/, .agents/, .env*)
        config_patterns = [".spec", ".specops", ".agents"]
        for pattern in config_patterns:
            src = self.root / pattern
            if src.exists():
                dest = worktree_dir / pattern
                if src.is_dir():
                    shutil.copytree(src, dest, dirs_exist_ok=True)
                else:
                    shutil.copy2(src, dest)

        # Copy env files if present
        for env_file in self.root.glob(".env*"):
            if env_file.is_file():
                shutil.copy2(env_file, worktree_dir / env_file.name)

        # 3. Create relative symlinks for heavy gitignored dependencies if they exist (.venv, node_modules)
        dep_folders = [
            Path(".venv"),
            Path("node_modules"),
            Path("backend/.venv"),
            Path("frontend/node_modules"),
            Path(".gradle"),
        ]
        for dep in dep_folders:
            src = self.root / dep
            if src.exists() and src.is_dir():
                target = worktree_dir / dep
                target.parent.mkdir(parents=True, exist_ok=True)
                if not target.exists():
                    try:
                        # Compute relative path from target back to src
                        rel_link = os.path.relpath(src, target.parent)
                        os.symlink(rel_link, target)
                    except OSError:
                        pass

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

        # 2. Sync base branch
        self.sync_base_branch(base)

        # 3. Baseline verification gate
        baseline = self.run_baseline_gate()
        if not baseline.passed:
            return {
                "status": "FAIL",
                "error": f"Baseline verification checks failed on base branch '{base}': {baseline.summary}",
                "evidence_path": baseline.evidence_path,
                "checks_passed": baseline.checks_passed,
                "checks_total": baseline.checks_total,
                "baseline": baseline.status,
            }

        # 4. Provision worktree or use current directory
        target_root = self.provision_worktree(target_branch, base) if use_worktree else self.root

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
