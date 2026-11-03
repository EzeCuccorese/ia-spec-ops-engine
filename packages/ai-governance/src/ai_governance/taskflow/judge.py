"""The engine's checks for a judge round, run on an isolated copy of the exact commit.

Each bound repository gets ``git worktree add --detach <tmp> HEAD``: real git metadata (so
diffs and ``ws check`` work), nothing of the builder's checkout. The engine runs the checks
there, by code, and the copy is removed at once. The judge itself is a reader: it is
dispatched through Orca (see ``judge_flow``) to review the real, clean checkout and never
gets a copy. Before anything is recorded or dispatched, every real checkout is verified to
be the very commit and tree the checks ran on.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from .agents import builder_providers, provider
from .config import FlowConfig, check_timeout_seconds
from .control import CheckedBaseline
from .gates import GateContext
from .models import JsonDict, Task
from .stamp import GitError, git, head_sha, merge_base, tree_fingerprint
from .store import TaskStore, atomic_write_text

# Dependency folders are linked from the source checkout so checks can run without a
# fresh install; they are git-ignored, so they never enter the judged diff.
SHARED_DEPENDENCIES = ("node_modules", ".venv", "venv", "vendor")
CHECK_TIMEOUT: float | None = None  # None: the `taskflow.timeout_seconds` setting (tests override)
OUTPUT_TAIL = 6000
TIMEOUT_EXIT = 124  # same code as coreutils `timeout`


class JudgeError(ValueError):
    pass


@dataclass(frozen=True)
class JudgedCopy:
    """A throwaway copy of one repository. ``head`` and ``fingerprint`` describe the REAL
    checkout when the copy was made (clean, committed): they are the baseline of the round."""

    source: Path
    path: Path
    head: str
    base: str
    fingerprint: str
    common: Path | None = None  # git dir that outlives a vanished source


def _base(repo: Path, binding: JsonDict) -> str:
    branch = str(binding.get("integration_branch") or binding.get("base") or "")
    return merge_base(repo, branch) if branch else ""


def make_copy(binding: JsonDict, scratch: Path) -> JudgedCopy:
    source = Path(binding["path"])
    if git(source, "status", "--porcelain").strip():
        raise JudgeError(
            f"{source} has uncommitted changes: commit them, the judge only judges commits"
        )
    head = git(source, "rev-parse", "HEAD").strip()
    target = scratch / f"{source.name}-{head[:8]}"
    common = _common_dir(source)
    try:
        # `worktree add` can register the worktree and still fail (a failing post-checkout hook).
        git(source, "worktree", "add", "--detach", str(target), head)
        for name in SHARED_DEPENDENCIES:
            if (source / name).exists() and not (target / name).exists():
                (target / name).symlink_to(source / name)
        return JudgedCopy(
            source, target, head, _base(source, binding), tree_fingerprint(source), common
        )
    except BaseException:
        _forget_worktree(common, target)
        raise


def _common_dir(source: Path) -> Path:
    """The repository's git dir, kept apart from the source cwd (a linked worktree can vanish)."""
    raw = Path(git(source, "rev-parse", "--git-common-dir").strip())
    return raw if raw.is_absolute() else (source / raw).resolve()


def _forget_worktree(common: Path, target: Path) -> None:
    """Delete a throwaway worktree and unregister it through the surviving git dir."""
    shutil.rmtree(target, ignore_errors=True)
    if not common.is_dir():
        return  # the repository itself is gone: nothing is left to unregister
    try:
        git(common, "worktree", "prune")
    except GitError as exc:  # never hide the original failure, but do not hide this one either
        print(f"warning: could not prune the judge worktree of {common}: {exc}", file=sys.stderr)


def _run_check(command: str, cwd: Path) -> JsonDict:
    timeout = CHECK_TIMEOUT if CHECK_TIMEOUT is not None else check_timeout_seconds()
    try:
        proc = subprocess.run(
            command,
            shell=True,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"cmd": command, "exit": TIMEOUT_EXIT, "tail": f"Timed out after {timeout}s"}
    return {
        "cmd": command,
        "exit": proc.returncode,
        "tail": (proc.stdout + proc.stderr)[-OUTPUT_TAIL:],
    }


def run_checks(copy: JudgedCopy, commands: tuple[str, ...], evidence: Path) -> JsonDict:
    results = []
    for command in commands:
        results.append(_run_check(command, copy.path))
    report = "\n\n".join(f"$ {r['cmd']}\nexit {r['exit']}\n{r['tail']}" for r in results)
    path = evidence / f"checks-{copy.source.name}@{copy.head[:8]}.txt"
    atomic_write_text(path, report)
    return {"path": str(path), "passed": all(r["exit"] == 0 for r in results), "results": results}


def judge_prompt(task: Task, focus: str, run: CheckRun) -> str:
    # Role, goal and references come from the round header that dispatch prepends.
    lines = [f"Focus: '{focus}'."]
    lines += [f"- step: {str(s['text'])[:300]}" for s in task.steps[-10:]]
    for copy, check in zip(run.copies, run.checks, strict=True):
        diff = f"git diff {copy.base}..{copy.head}" if copy.base else f"git show {copy.head}"
        lines.append(
            f"Repository {copy.source.name} at {copy.source} (commit {copy.head}, clean tree). "
            f"Review `{diff}`. Engine-run checks {'passed' if check['passed'] else 'FAILED'}: "
            f"{check['path']}."
        )
    lines.append(
        "You are a reader: do not run builds, tests or any command that writes, and do not "
        "modify any file. Judge against the goal and the references: correctness, scope, "
        "tests, risks. Report findings as file:line with the concrete fix."
    )
    return "\n".join(lines)


def builders(task: Task, config: FlowConfig) -> set[str]:
    """Every provider that wrote code for the task: the configured builder and any override."""
    return builder_providers(task, str(config.roles.get("builder", {}).get("agent", "")))


def independent_judges(
    task: Task, config: FlowConfig, focus: str, focuses: list[str]
) -> list[JsonDict]:
    writers = builders(task, config)
    judges = [config.judge_for(name) for name in ([focus] if focus else focuses)]
    for judge in judges:
        if not judge.get("agent") or provider(str(judge.get("agent"))) in writers:
            raise JudgeError(
                f"Judge '{judge.get('focus')}' is not independent of the builder ({', '.join(writers)})"
            )
    return judges


def _check_evidence(
    copies: Sequence[JudgedCopy], checks: Sequence[JsonDict], stamp_key: str
) -> list[JsonDict]:
    return [
        {
            "kind": "checks",
            "repo": str(c.source),
            "sha": c.head,
            "stamp": stamp_key,
            "passed": r["passed"],
            "path": r["path"],
        }
        for c, r in zip(copies, checks, strict=True)
    ]


def _git_if_present(source: Path | None, *args: str) -> None:
    """Cleanup of a source that vanished has nothing to undo and must not mask the real error."""
    if source is None:
        return
    try:
        git(source, *args)
    except GitError:
        if source.is_dir():
            raise


def _cleanup(copies: list[JudgedCopy], scratch: Path) -> None:
    """Runs also after an exception: no worktree registration or scratch dir is left behind."""
    for copy in copies:
        if copy.source.is_dir() and copy.path.exists():
            _git_if_present(copy.source, "worktree", "remove", "--force", str(copy.path))
        elif copy.common is not None:
            _forget_worktree(copy.common, copy.path)
    shutil.rmtree(scratch, ignore_errors=True)
    for copy in copies:
        _git_if_present(copy.source if copy.source.is_dir() else copy.common, "worktree", "prune")


@dataclass(frozen=True)
class JudgeScope:
    """What to judge: one focus (empty for all) and the repos, None meaning the live bindings."""

    focus: str = ""
    repos: Sequence[JsonDict] | None = None


@dataclass(frozen=True)
class CheckRun:
    """The engine's checks of one ``taskflow judge``: the (already removed) copies, their
    results and the evidence entries, which are recorded only once the baseline holds."""

    copies: tuple[JudgedCopy, ...]
    checks: tuple[JsonDict, ...]
    evidence: tuple[JsonDict, ...]

    def baseline(self, stamp: str) -> CheckedBaseline:
        repos = tuple(
            {"path": str(c.source), "head": c.head, "fingerprint": c.fingerprint}
            for c in self.copies
        )
        return CheckedBaseline(stamp, repos)


def verify_unchanged(copies: Sequence[JudgedCopy]) -> None:
    """Every real checkout is still the clean commit the checks ran on (HEAD and tree)."""
    moved = [
        str(c.source)
        for c in copies
        if (head_sha(c.source), tree_fingerprint(c.source)) != (c.head, c.fingerprint)
    ]
    if moved:
        raise JudgeError(
            f"{', '.join(moved)} changed while the checks ran: nothing was recorded or "
            "dispatched; run `taskflow judge` again on the committed code"
        )


def run_engine_checks(
    store: TaskStore, task: Task, ctx: GateContext, bound: Sequence[JsonDict]
) -> CheckRun:
    """Run the checks of every bound repo in a throwaway copy, then verify the real checkouts
    did not move. Nothing is recorded here: the caller does that after its own stamp check."""
    scratch = Path(tempfile.mkdtemp(prefix=f"taskflow-judge-{task.id}-"))
    copies: list[JudgedCopy] = []
    try:
        copies.extend(make_copy(binding, scratch) for binding in bound)
        evidence_dir = store.evidence_dir(task.id)
        checks = [run_checks(copy, ctx.risk.checks, evidence_dir) for copy in copies]
        verify_unchanged(copies)
    finally:
        _cleanup(copies, scratch)
    evidence = _check_evidence(copies, checks, ctx.stamp_key)
    return CheckRun(tuple(copies), tuple(checks), tuple(evidence))
