"""Independent judgment on an isolated copy of the exact commit.

Each bound repository gets ``git worktree add --detach <tmp> HEAD``: real git metadata
(so diffs and ``ws check`` work), nothing of the builder's checkout. The checks run there
first and their output is saved as evidence; then every required judge focus runs on that
copy. A copy a judge modified is kept and reported; untouched copies are removed.
"""

from __future__ import annotations

import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .config import FlowConfig
from .gates import GateContext
from .models import JsonDict, Task
from .rounds import RoundRequest, run_round
from .stamp import git, merge_base, tree_fingerprint
from .store import TaskStore, atomic_write_text

# Dependency folders are linked from the source checkout so checks can run without a
# fresh install; they are git-ignored, so they never enter the judged diff.
SHARED_DEPENDENCIES = ("node_modules", ".venv", "venv", "vendor")
CHECK_TIMEOUT = 1800
OUTPUT_TAIL = 6000


class JudgeError(ValueError):
    pass


@dataclass(frozen=True)
class JudgedCopy:
    source: Path
    path: Path
    head: str
    base: str
    fingerprint: str


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
    git(source, "worktree", "add", "--detach", str(target), head)
    for name in SHARED_DEPENDENCIES:
        if (source / name).exists() and not (target / name).exists():
            (target / name).symlink_to(source / name)
    return JudgedCopy(source, target, head, _base(source, binding), tree_fingerprint(target))


def run_checks(copy: JudgedCopy, commands: tuple[str, ...], evidence: Path) -> JsonDict:
    results = []
    for command in commands:
        proc = subprocess.run(
            command,
            shell=True,
            cwd=copy.path,
            capture_output=True,
            text=True,
            timeout=CHECK_TIMEOUT,
            check=False,
        )
        results.append(
            {
                "cmd": command,
                "exit": proc.returncode,
                "tail": (proc.stdout + proc.stderr)[-OUTPUT_TAIL:],
            }
        )
    report = "\n\n".join(f"$ {r['cmd']}\nexit {r['exit']}\n{r['tail']}" for r in results)
    path = evidence / f"checks-{copy.source.name}@{copy.head[:8]}.txt"
    atomic_write_text(path, report)
    return {"path": str(path), "passed": all(r["exit"] == 0 for r in results), "results": results}


def judge_prompt(task: Task, focus: str, copies: list[JudgedCopy], checks: list[JsonDict]) -> str:
    # Role, goal and references come from the round header that run_round prepends.
    lines = [f"Focus: '{focus}'."]
    lines += [f"- step: {str(s['text'])[:300]}" for s in task.steps[-10:]]
    for copy, check in zip(copies, checks, strict=True):
        diff = f"git diff {copy.base}..{copy.head}" if copy.base else f"git show {copy.head}"
        lines.append(
            f"Repository {copy.source.name}: isolated copy at {copy.path} (commit {copy.head}). "
            f"Review `{diff}`. Checks {'passed' if check['passed'] else 'FAILED'}: {check['path']}."
        )
    lines.append(
        "Run any test or check you need yourself in the copy; do not trust declared evidence. "
        "Judge against the goal and the references: correctness, scope, tests, risks. "
        "Report findings as file:line with the concrete fix."
    )
    return "\n".join(lines)


def builders(task: Task, config: FlowConfig) -> set[str]:
    """Every agent that wrote code for the task: the configured builder and any override."""
    used = {str(r.get("agent")) for r in task.rounds if r.get("role") == "builder"}
    return {str(config.roles.get("builder", {}).get("agent", "")), *used} - {""}


def _independent_judges(
    task: Task, config: FlowConfig, focus: str, focuses: list[str]
) -> list[JsonDict]:
    writers = builders(task, config)
    judges = [config.judge_for(name) for name in ([focus] if focus else focuses)]
    for judge in judges:
        if judge.get("agent") in ("", *writers):
            raise JudgeError(
                f"Judge '{judge.get('focus')}' is not independent of the builder ({', '.join(writers)})"
            )
    return judges


def _check_evidence(
    copies: list[JudgedCopy], checks: list[JsonDict], stamp_key: str
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


def _discard_untouched(copies: list[JudgedCopy]) -> list[str]:
    kept = []
    for copy in copies:
        if tree_fingerprint(copy.path) == copy.fingerprint:
            git(copy.source, "worktree", "remove", "--force", str(copy.path))
        else:
            kept.append(str(copy.path))
    return kept


def judge_task(
    store: TaskStore, task: Task, ctx: GateContext, focus: str = ""
) -> tuple[list[JsonDict], list[str]]:
    """Run the checks and the judges; returns the rounds and the copies kept because a
    judge modified them. Check results are stored as evidence that gates read directly,
    so a failing check blocks whatever a judge answers."""
    config, risk = ctx.config, ctx.risk
    judges = _independent_judges(task, config, focus, list(risk.judges))
    scratch = Path(tempfile.mkdtemp(prefix=f"taskflow-judge-{task.id}-"))
    copies = [make_copy(binding, scratch) for binding in task.repos]
    checks = [run_checks(copy, risk.checks, store.evidence_dir(task.id)) for copy in copies]
    evidence = _check_evidence(copies, checks, ctx.stamp_key)
    store.mutate(task.id, lambda t: t.evidence.extend(evidence))
    records = []
    for judge in judges:
        if judge.get("agent") == "human":
            continue  # the user judges in the chat: approve --action review --target <focus>
        request = RoundRequest(
            task_id=task.id,
            phase=task.phase,
            role="judge",
            focus=str(judge["focus"]),
            prompt=judge_prompt(task, str(judge["focus"]), copies, checks),
            repo=copies[0].path,
            agent=judge,
            timeout=config.timeout_seconds,
            watch=tuple(c.path for c in copies[1:]),
        )
        records.append(run_round(store, request, ctx.stamp_key))
    return records, _discard_untouched(copies)
