"""Hermetic harness for the Orca-run rounds: one fake Orca CLI, a git wrapper, a clean env.

Isolation is layered, because patching ``socket.connect`` alone does not stop a spawned
executable:

* the account and runtime environment (``GH_TOKEN``, ``GITHUB_TOKEN``, ``ORCA_*``,
  ``AI_GOVERNANCE_*``, ``FAKE_*``) is cleared first, and only then are the scenario
  variables set;
* ``PATH`` holds only ``bin_dir``, which has exactly two executables: ``orca-fake`` and a
  ``git`` wrapper that logs every argv and runs the real git for an explicit allow-list of
  subcommands (anything else exits 97 and shows up as ``DENIED`` in the git log);
* ``subprocess.Popen`` is wrapped so any other executable fails the test at the call site,
  and ``socket.socket.connect`` fails too;
* ``orca-fake`` implements only ``orchestration worker-show --dispatch ID --json`` and
  ``orchestration worker-list --json [--limit N] [--cursor C]``, replays the scenario JSON in
  the field names seen live (``dispatchId``, ``state``, ``liveness``, ``agent`` such as
  ``codex/gpt-6.1-sol``; rows may have no ``agent``) and exits 3 on anything else.
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import socket
import stat
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict, Unpack

import ai_governance
import pytest
from ai_governance.taskflow.cli import main
from ai_governance.taskflow.models import Task
from ai_governance.taskflow.store import TaskStore

GIT_ALLOWED = (
    "init config add commit rev-parse branch status diff submodule checkout log show "
    "merge-base symbolic-ref ls-files worktree"
)
TASK = "ONB-1"

_ORCA_IMPL = r"""
import json, os, sys

argv = sys.argv[1:]
with open(os.environ["FAKE_ORCA_LOG"], "a", encoding="utf-8") as log:
    log.write(json.dumps(argv) + "\n")
scenario = json.load(open(os.environ["FAKE_ORCA"], encoding="utf-8"))


def die(code, message):
    sys.stderr.write(message + "\n")
    sys.exit(code)


if argv[:2] == ["orchestration", "worker-show"] and len(argv) == 5:
    if argv[2] != "--dispatch" or argv[4] != "--json":
        die(3, "unsupported")
    entry = scenario.get("show", {}).get(argv[3])
    if entry is None or "exit" in entry:
        die((entry or {}).get("exit", 1), "no such dispatch")
    print(entry["raw"] if "raw" in entry else json.dumps(entry))
elif argv[:2] == ["orchestration", "worker-list"]:
    flags, rest = {}, argv[2:]
    while rest:
        if rest[0] == "--json":
            flags["json"] = True
            rest = rest[1:]
        elif rest[0] in ("--limit", "--cursor") and len(rest) > 1:
            flags[rest[0]] = rest[1]
            rest = rest[2:]
        else:
            die(3, "unsupported")
    if "json" not in flags:
        die(3, "unsupported")
    pages = scenario.get("pages", [])
    index = int(flags.get("--cursor", "p0")[1:])
    rows = pages[index] if index < len(pages) else []
    following = "p%d" % (index + 1) if index + 1 < len(pages) else None
    print(json.dumps({"workers": rows, "nextCursor": following}))
else:
    die(3, "unsupported")
"""


@dataclass
class Result:
    code: int
    out: str
    err: str

    @property
    def text(self) -> str:
        return self.out + self.err


@dataclass
class Dispatched:
    n: int
    argv: list[str]
    result: Result


def flag(argv: list[str], name: str) -> str:
    return argv[argv.index(name) + 1]


def _script(path: Path, body: str) -> None:
    path.write_text("#!/bin/sh\n" + body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


class OrcaWorld:
    """A task bound to a repository, a scenario for the fake Orca and the logs to assert on."""

    def __init__(
        self, base: Path, repo: Path, store: TaskStore, capsys: pytest.CaptureFixture[str]
    ):
        self.base, self.repo, self.store, self.capsys = base, repo, store, capsys
        self.bin_dir = base / "bin"
        self.scenario_path = base / "scenario.json"
        self.orca_log = base / "orca.log"
        self.git_log = base / "git.log"
        self.calls: list[list[str]] = []
        self.scenario: dict[str, object] = {"show": {}, "pages": []}
        self.save()

    # -- scenario ---------------------------------------------------------------------------
    def save(self) -> None:
        self.scenario_path.write_text(json.dumps(self.scenario), encoding="utf-8")

    def worker(
        self,
        dispatch_id: str,
        state: str = "succeeded",
        agent: str | None = "claude",
        liveness: str = "released",
    ) -> None:
        """Make ``worker-show`` answer for ``dispatch_id``; ``agent=None`` is a released worker."""
        row: dict[str, str] = {"dispatchId": dispatch_id, "state": state, "liveness": liveness}
        if agent is not None:
            row["agent"] = agent
        self.scenario["show"][dispatch_id] = row  # type: ignore[index]
        self.save()

    def raw_show(self, dispatch_id: str, entry: dict[str, object]) -> None:
        self.scenario["show"][dispatch_id] = entry  # type: ignore[index]
        self.save()

    def pages(self, *pages: list[dict[str, str]]) -> None:
        self.scenario["pages"] = [list(page) for page in pages]
        self.save()

    # -- running the CLI --------------------------------------------------------------------
    def run(self, *argv: str) -> Result:
        self.capsys.readouterr()
        try:
            code = main(list(argv))
        except SystemExit as exc:  # argparse usage errors
            code = int(exc.code or 0) if not isinstance(exc.code, str) else 2
        captured = self.capsys.readouterr()
        return Result(code, captured.out, captured.err)

    def dispatch(
        self, role: str = "planner", agent: str = "claude", focus: str = "", *extra: str
    ) -> Dispatched:
        argv = ["round", TASK, "dispatch", "--role", role, "--agent", agent, "--prompt", "do it"]
        result = self.run(*argv, *(["--focus", focus] if focus else []), *extra)
        assert result.code == 0, result.text
        line = [] if "--json" in extra else shlex.split(result.out.strip())
        parsed = json.loads(result.out) if "--json" in extra else line
        return Dispatched(int(flag(parsed, "--task-title").split()[2]), parsed, result)

    def finish(self, n: int, dispatch_id: str, **opts: Unpack[FinishOpts]) -> None:
        """Play the worker: its receipt, its answer, and Orca's view of it.

        ``receipt=""`` writes a correct receipt, ``None`` writes none, any other text is
        written verbatim; ``answer=None`` writes no answer. Options default to a worker that
        succeeded as claude: ``answer``, ``receipt``, ``state``, ``agent``, ``register``."""
        answer = opts.get("answer", "the review\n")
        receipt = opts.get("receipt", "")
        found = self.dispatch_json(n)
        if receipt == "":
            receipt = f"ROUND {found['nonce']} DISPATCH {dispatch_id}\n"
        if receipt is not None:
            Path(found["receipt"]).write_text(receipt, encoding="utf-8")
        if answer is not None:
            Path(found["answer"]).write_text(answer, encoding="utf-8")
        if opts.get("register", True):
            self.worker(dispatch_id, opts.get("state", "succeeded"), opts.get("agent", "claude"))

    def collect(self, n: int, dispatch_id: str, *extra: str) -> Result:
        return self.run(
            "round", TASK, "collect", "--round", str(n), "--dispatch-id", dispatch_id, *extra
        )

    def abort(self, n: int, *tail: str) -> Result:
        return self.run("round", TASK, "abort", "--round", str(n), *tail)

    def cycle(
        self, role: str = "planner", agent: str = "claude", focus: str = "", **opts
    ) -> Result:
        """dispatch, play the worker, collect (dispatch id ``D<n>``)."""
        made = self.dispatch(role, agent, focus)
        self.finish(made.n, f"D{made.n}", agent=opts.pop("worker", agent), **opts)
        return self.collect(made.n, f"D{made.n}")

    # -- reading state ----------------------------------------------------------------------
    def task(self) -> Task:
        return self.store.get(TASK)

    def run_dir(self, n: int) -> Path:
        return self.store.task_dir(TASK) / "runs" / f"{n:03d}"

    def dispatch_json(self, n: int) -> dict[str, str]:
        return json.loads((self.run_dir(n) / "dispatch.json").read_text(encoding="utf-8"))

    def record(self, n: int) -> dict[str, object]:
        return next(r for r in self.task().rounds if r["n"] == n)

    def snapshot(self) -> dict[str, bytes]:
        root = self.store.root
        return {
            str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()
        }

    def orca_calls(self) -> list[list[str]]:
        if not self.orca_log.exists():
            return []
        return [json.loads(line) for line in self.orca_log.read_text().splitlines() if line]

    def edit_state(self, change) -> None:  # noqa: ANN001
        """Rewrite state.json behind the engine's back (what a misbehaving reader could do)."""
        path = self.store.task_dir(TASK) / "state.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        change(data)
        path.write_text(json.dumps(data), encoding="utf-8")

    # -- processes --------------------------------------------------------------------------
    def spawn(self, go: Path, *argv: str) -> subprocess.Popen[str]:
        """The taskflow CLI in another process; it waits for the ``go`` file, then runs."""
        code = (
            "import sys, time, pathlib\n"
            "flag = pathlib.Path(sys.argv[1])\n"
            "while not flag.exists():\n    time.sleep(0.002)\n"
            "from ai_governance.taskflow.cli import main\n"
            "sys.exit(main(sys.argv[2:]))\n"
        )
        src = str(Path(ai_governance.__file__).resolve().parents[1])
        env = {**os.environ, "PYTHONPATH": src}
        return subprocess.Popen(
            [sys.executable, "-c", code, str(go), *argv],
            cwd=self.repo, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )  # fmt: skip

    def race(self, *commands: list[str]) -> list[tuple[int, str]]:
        """Run the commands in separate processes released together; (exit code, output)."""
        go = self.base / f"go-{time.monotonic_ns()}"
        procs = [self.spawn(go, *command) for command in commands]
        go.write_text("go")
        done = [proc.communicate(timeout=120) for proc in procs]
        return [(proc.returncode, out + err) for proc, (out, err) in zip(procs, done, strict=True)]

    # -- judge rounds -----------------------------------------------------------------------
    def ready_for_judge(self) -> None:
        """Phase judge on committed code with the TDD skip a user would have approved."""

        def change(task: Task) -> None:
            task.phase = "judge"
            task.tdd = {"skip": {"reason": "user"}}
            task.approvals.append({"action": "plan", "target": TASK, "stamp": ""})

        self.store.mutate(TASK, change)

    def judge(self, *extra: str) -> Result:
        return self.run("judge", TASK, *extra)

    @staticmethod
    def worker_lines(result: Result) -> list[list[str]]:
        """The printed worker-start lines, one argv each."""
        return [shlex.split(line) for line in result.out.splitlines() if "worker-start" in line]

    def settle_judge(self, line: list[str], verdict: str = "pass", agent: str = "codex") -> Result:
        """Play the worker of a printed judge line and collect it (dispatch id ``J<n>``)."""
        number = int(flag(line, "--task-title").split()[2])
        answer = f"review done\nVERDICT: {verdict}\n"
        self.finish(number, f"J{number}", answer=answer, agent=agent)
        return self.collect(number, f"J{number}")

    # -- hermeticity ------------------------------------------------------------------------
    def assert_hermetic(self) -> None:
        names = {Path(call[0]).name for call in self.calls}
        assert names <= {"git", "orca-fake", Path(sys.executable).name}, names
        if self.git_log.exists():
            assert "DENIED" not in self.git_log.read_text(), self.git_log.read_text()
        for call in self.orca_calls():
            assert call[:2] in (
                ["orchestration", "worker-show"],
                ["orchestration", "worker-list"],
            ), call


class FinishOpts(TypedDict, total=False):
    answer: str | None
    receipt: str | None
    state: str
    agent: str | None
    register: bool


class WorldOpts(TypedDict, total=False):
    repo_name: str
    state_in_repo: bool


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


def _install_orca(bin_dir: Path) -> None:
    bin_dir.mkdir(parents=True, exist_ok=True)
    (bin_dir / "orca_fake_impl.py").write_text(_ORCA_IMPL, encoding="utf-8")
    _script(
        bin_dir / "orca-fake",
        f'exec {shlex.quote(sys.executable)} {shlex.quote(str(bin_dir / "orca_fake_impl.py"))} "$@"\n',
    )


def _install_bin(base: Path, real_git: str) -> Path:
    bin_dir = base / "bin"
    bin_dir.mkdir(parents=True)
    _install_orca(bin_dir)
    for agent in ("agy", "claude", "codex"):  # `judge` still checks the configured agents exist
        _script(bin_dir / agent, "exit 0\n")
    _script(
        bin_dir / "git",
        'printf \'%s\\n\' "$*" >> "$FAKE_GIT_LOG"\n'
        f'case "$1" in {"|".join(GIT_ALLOWED.split())}) exec "$FAKE_REAL_GIT" "$@";; esac\n'
        'printf \'DENIED %s\\n\' "$*" >> "$FAKE_GIT_LOG"\nexit 97\n',
    )
    return bin_dir


def _make_repo(path: Path, ignore: str = "") -> None:
    path.mkdir(parents=True)
    _git(path, "init", "-q", "-b", "feat/ONB-1-x")
    _git(path, "config", "user.email", "t@example.com")
    _git(path, "config", "user.name", "T")
    (path / "app.py").write_text("x = 1\n")
    if ignore:
        (path / ".gitignore").write_text(ignore + "\n")
    _git(path, "add", ".")
    _git(path, "commit", "-qm", "init")


def _clear_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Clear the real account/runtime environment BEFORE any scenario variable is set."""
    for name in list(os.environ):
        if name.startswith(("ORCA_", "AI_GOVERNANCE_", "FAKE_")) or name in (
            "GH_TOKEN",
            "GITHUB_TOKEN",
        ):
            monkeypatch.delenv(name)
    for name in ("CLAUDECODE", "CLAUDE_CODE_SESSION_ID"):
        monkeypatch.delenv(name, raising=False)


def make_world(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    **opts: Unpack[WorldOpts],
) -> OrcaWorld:
    _clear_environment(monkeypatch)
    repo_name, state_in_repo = opts.get("repo_name", "repo"), opts.get("state_in_repo", False)
    real_git = shutil.which("git")
    assert real_git, "git is required"
    base = tmp_path / "world"
    base.mkdir()
    bin_dir = _install_bin(base, real_git)
    # 2. scenario variables
    repo = tmp_path / repo_name
    state = repo / ".state" if state_in_repo else tmp_path / "state"
    monkeypatch.setenv("PATH", str(bin_dir))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for key, value in {
        "FAKE_REAL_GIT": real_git, "FAKE_GIT_LOG": str(base / "git.log"),
        "FAKE_ORCA": str(base / "scenario.json"), "FAKE_ORCA_LOG": str(base / "orca.log"),
        "ORCA_CLI_COMMAND": "orca-fake", "AI_GOVERNANCE_STATE_DIR": str(state),
        "XDG_CONFIG_HOME": str(tmp_path / "config"), "AI_GOVERNANCE_AGENT": "1",
    }.items():  # fmt: skip
        monkeypatch.setenv(key, value)
    _make_repo(repo, ".state/" if state_in_repo else "")
    world = OrcaWorld(base, repo, TaskStore(), capsys)
    _guard_processes(monkeypatch, world)
    monkeypatch.chdir(repo)
    assert world.run("new", TASK, "--title", "Fix status", "--summary", "goal").code == 0
    assert world.run("bind", TASK, "--repo", str(repo)).code == 0
    return world


def _guard_processes(monkeypatch: pytest.MonkeyPatch, world: OrcaWorld) -> None:
    real_init = subprocess.Popen.__init__
    allowed = {"git", "orca-fake", Path(sys.executable).name}

    def guarded(self, args, *rest, **kwargs):  # type: ignore[no-untyped-def]
        argv = [str(part) for part in args] if isinstance(args, list | tuple) else [str(args)]
        world.calls.append(argv)
        assert not kwargs.get("shell"), f"shell commands are not allowed: {argv}"
        assert Path(argv[0]).name in allowed, f"unexpected subprocess: {argv}"
        real_init(self, args, *rest, **kwargs)

    def no_network(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        raise OSError("network is disabled in these tests")

    monkeypatch.setattr(subprocess.Popen, "__init__", guarded)
    monkeypatch.setattr(socket.socket, "connect", no_network)


def attach_orca(base: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The fake Orca CLI in front of the real PATH, for tests that keep their own fixtures."""
    base.mkdir()
    _install_orca(base / "bin")
    monkeypatch.setenv("PATH", f"{base / 'bin'}{os.pathsep}{os.environ['PATH']}")
    for key, value in {
        "FAKE_ORCA": str(base / "scenario.json"), "FAKE_ORCA_LOG": str(base / "orca.log"),
        "ORCA_CLI_COMMAND": "orca-fake",
    }.items():  # fmt: skip
        monkeypatch.setenv(key, value)


@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]):
    made = make_world(tmp_path, monkeypatch, capsys)
    yield made
    made.assert_hermetic()
