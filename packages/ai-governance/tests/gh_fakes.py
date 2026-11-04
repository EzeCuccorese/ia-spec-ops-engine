"""Hermetic harness for the GitHub reader: a fake ``gh`` (and ``ssh``) replaying real shapes.

* ``gh`` and ``ssh`` are small executables in a private ``bin`` directory, which is the whole
  ``PATH`` (plus a ``git`` shim); the account and runtime environment is cleared before the
  scenario variables are set (``orca_fakes._clear_environment``);
* the fake ``gh`` implements ``auth status [--json hosts]``, ``auth token --hostname github.com
  --user L --no-refresh`` and ``api graphql`` only, answers in the exact envelopes captured in
  ``prs_real_samples`` (a test proves the equality) and exits 3 on anything else;
* it validates tokens by itself (a token it did not issue is a 401), resolves the calling
  account from ``GH_TOKEN`` or the active account, and logs ``{argv, account, gh_env}`` where
  ``gh_env`` holds only the NAMES of credential variables present: never a value;
* ``subprocess.Popen`` is wrapped so any other executable fails the test, and
  ``socket.socket.connect`` fails, so nothing can reach the network.
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import socket
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypedDict, Unpack

import pytest
from ai_governance.taskflow.prs.cache import PrCache
from ai_governance.taskflow.prs.github import Gh, PrReader, check_argv
from orca_fakes import _clear_environment, _script

GH_SCOPES = "admin:public_key, gist, read:org, repo"

_GH_IMPL = r"""
import json, os, sys, time

argv = sys.argv[1:]
scenario = json.load(open(os.environ["FAKE_GH"], encoding="utf-8"))
ENV_NAMES = ("GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN", "GH_HOST")
accounts = scenario.get("accounts", [])
by_token = {a["token"]: a["login"] for a in accounts}
active = next((a["login"] for a in accounts if a.get("active")), None)
token = os.environ.get("GH_TOKEN")
account = by_token.get(token, "invalid") if token else active
with open(os.environ["FAKE_GH_LOG"], "a", encoding="utf-8") as handle:
    handle.write(json.dumps({
        "argv": argv,
        "account": account,
        "gh_env": [name for name in ENV_NAMES if name in os.environ],
    }) + "\n")


def die(code, message, out=""):
    sys.stdout.write(out)
    sys.stderr.write(message + "\n")
    sys.exit(code)


def auth_status(as_json):
    if not accounts:
        die(1, "You are not logged in to any GitHub hosts.")
    if as_json:
        if not scenario.get("status_json", True):
            die(1, "unknown flag: --json")
        hosts = [{"state": "success", "active": bool(a.get("active")), "host": "github.com",
                  "login": a["login"], "tokenSource": "keyring", "scopes": "admin:public_key, gist, read:org, repo",
                  "gitProtocol": "ssh"} for a in accounts]
        print(json.dumps({"hosts": {"github.com": hosts}}))
        return
    print("github.com")
    for a in accounts:
        print("  - Logged in to github.com account %s (keyring)" % a["login"])
        print("  - Active account: %s" % ("true" if a.get("active") else "false"))


def auth_token():
    if len(argv) != 7 or argv[2:5] != ["--hostname", "github.com", "--user"] or argv[6] != "--no-refresh":
        die(3, "unsupported")
    login = argv[5]
    if login in scenario.get("token_fail", {}):
        die(1, scenario["token_fail"][login])
    if login in scenario.get("token_output", {}):
        print(scenario["token_output"][login])
        return
    found = next((a["token"] for a in accounts if a["login"] == login), None)
    if found is None:
        die(1, "no oauth token found for github.com account " + login)
    print(found)


def repo_not_found(name):
    message = "Could not resolve to a Repository with the name '%s'." % name
    body = {"data": {"repository": None}, "errors": [{
        "type": "NOT_FOUND", "path": ["repository"],
        "locations": [{"line": 2, "column": 3}], "message": message}]}
    die(1, "gh: " + message, json.dumps(body))


def thread_page(spec, after):
    threads = spec.get("threads", [])
    offset = int(after.split(":")[1]) if after else 0
    nodes = [{"isResolved": flag} for flag in threads[offset:offset + 100]]
    end = offset + len(nodes)
    return {"totalCount": len(threads),
            "pageInfo": {"hasNextPage": end < len(threads), "endCursor": ("cur:%d" % end) if nodes else None},
            "nodes": nodes}


def mergeable_of(spec, key, paging):
    value = spec.get("mergeable", "MERGEABLE")
    if not isinstance(value, list):
        return value
    path = os.path.join(os.environ["FAKE_GH_STATE"], "counters.json")
    counters = json.load(open(path)) if os.path.exists(path) else {}
    count = counters.get(key, 0)
    if not paging:
        counters[key] = count + 1
        json.dump(counters, open(path, "w"))
    return value[min(count, len(value) - 1)]


def commits_of(spec):
    if "ci" not in spec:
        spec = dict(spec, ci="SUCCESS")
    if spec["ci"] == "__none__":
        return {"nodes": []}
    rollup = None if spec["ci"] is None else {"state": spec["ci"]}
    return {"nodes": [{"commit": {"statusCheckRollup": rollup}}]}


def pull_request(repo_name, number, spec, after):
    head = spec.get("head_repo", repo_name)
    pr = {
        "state": spec["state"], "isDraft": spec.get("draft", False),
        "baseRefName": spec.get("base", "main"), "headRefName": spec.get("head", "feature"),
        "mergeable": mergeable_of(spec, repo_name.lower() + "#" + number, bool(after)),
        "reviewDecision": spec.get("review"), "title": spec.get("title", "title"),
        "headRepository": None if head is None else {"nameWithOwner": head},
        "commits": commits_of(spec), "reviewThreads": thread_page(spec, after),
    }
    for key in spec.get("omit", []):
        pr.pop(key, None)
    return pr


def answer_pr(repo, repo_name, variables):
    if set(variables) - {"owner", "name", "number", "cursor"} or "number" not in variables:
        die(3, "unsupported")
    number, after = str(variables["number"]), variables.get("cursor")
    spec = repo.get("prs", {}).get(number)
    default = repo.get("default", "main")
    if spec is None:
        message = "Could not resolve to a PullRequest with the number of %s." % number
        body = {"data": {"repository": {"defaultBranchRef": {"name": default}, "pullRequest": None}},
                "errors": [{"type": "NOT_FOUND", "path": ["repository", "pullRequest"],
                            "locations": [{"line": 4, "column": 5}], "message": message}]}
        die(1, "gh: " + message, json.dumps(body))
    if after and int(after.split(":")[1]) in scenario.get("fail_offsets", []):
        die(1, "gh: boom")
    pr = pull_request(repo_name, number, spec, after)
    print(json.dumps({"data": {"repository": {"defaultBranchRef": {"name": default}, "pullRequest": pr}}}))


def answer_parent(repo, variables):
    if set(variables) != {"owner", "name", "base", "qualified"}:
        die(3, "unsupported")
    base = variables["base"]
    if variables["qualified"] != "refs/heads/" + base:
        die(3, "unsupported")
    nodes = [{"number": h["number"], "state": h["state"], "headRepository": {"nameWithOwner": h["head_repo"]}}
             for h in repo.get("heads", []) if h["head"] == base][:10]
    ref = {"name": base} if base in repo.get("branches", []) else None
    print(json.dumps({"data": {"repository": {
        "ref": ref,
        "pullRequests": {"nodes": nodes, "pageInfo": {"hasNextPage": bool(repo.get("heads_more"))}}}}}))


def graphql():
    rest = argv[2:]
    if len(rest) % 2:
        die(3, "unsupported")
    variables, query = {}, ""
    for flag, pair in zip(rest[0::2], rest[1::2]):
        key, _, value = pair.partition("=")
        if flag not in ("-f", "-F"):
            die(3, "unsupported")
        if key == "query":
            query = value
        else:
            variables[key] = int(value) if flag == "-F" and value.isdigit() else value
    time.sleep(scenario.get("hang_api", 0))
    if scenario.get("rate_limited"):
        die(1, "gh: API rate limit exceeded for user ID 1. (HTTP 403)")
    raw = scenario.get("raw_api")
    if raw is not None:
        sys.stdout.write(raw["stdout"])
        sys.exit(raw.get("code", 0))
    if account == "invalid":
        die(1, "gh: Bad credentials (HTTP 401)")
    if account is None:
        die(4, "To get started with GitHub CLI, please run: gh auth login")
    name = "%s/%s" % (variables.get("owner"), variables.get("name"))
    repos = {k.lower(): v for k, v in scenario.get("repos", {}).items()}
    repo = repos.get(name.lower())
    if repo is None or account.lower() not in [v.lower() for v in repo.get("visible_to", [])]:
        repo_not_found(name)
    if "pullRequest(number" in query:
        answer_pr(repo, name, variables)
    elif "pullRequests(headRefName" in query:
        answer_parent(repo, variables)
    else:
        die(3, "unsupported")


if argv[:3] == ["auth", "status", "--json"] and argv[3:] == ["hosts"]:
    auth_status(True)
elif argv == ["auth", "status"]:
    auth_status(False)
elif argv[:2] == ["auth", "token"]:
    auth_token()
elif argv[:2] == ["api", "graphql"]:
    graphql()
else:
    die(3, "unsupported")
"""

_SSH_IMPL = r"""
import json, os, sys

argv = sys.argv[1:]
with open(os.environ["FAKE_SSH_LOG"], "a", encoding="utf-8") as handle:
    handle.write(json.dumps(argv) + "\n")
if len(argv) == 2 and argv[0] == "-G":
    hosts = json.load(open(os.environ["FAKE_SSH_HOSTS"], encoding="utf-8"))
    print("user git")
    print("hostname " + hosts.get(argv[1], argv[1]))
else:
    sys.exit(3)
"""

_ALLOWED_PROGRAMS = {"gh", "ssh", "git"}


@dataclass
class GhWorld:
    """A fake GitHub (scenario JSON), a store cache and the logs a test asserts on."""

    base: Path
    cache: PrCache
    capsys: pytest.CaptureFixture[str]
    scenario: dict[str, Any] = field(default_factory=lambda: {"accounts": [], "repos": {}})
    calls: list[list[str]] = field(default_factory=list)
    sleeps: list[float] = field(default_factory=list)
    ssh_hosts: dict[str, str] = field(default_factory=dict)

    # -- scenario ---------------------------------------------------------------------------
    def save(self) -> None:
        (self.base / "scenario.json").write_text(json.dumps(self.scenario), encoding="utf-8")
        (self.base / "ssh-hosts.json").write_text(json.dumps(self.ssh_hosts), encoding="utf-8")

    def account(self, login: str, active: bool = False) -> str:
        """Log ``login`` in; returns the (fake) token the fake ``gh`` issues for it."""
        token = f"gho_FAKE{login.replace('-', '')}0000000000"
        self.scenario["accounts"].append({"login": login, "active": active, "token": token})
        self.save()
        return token

    def repo(self, name: str, visible_to: list[str], **extra: Any) -> dict[str, Any]:
        repo = {
            "visible_to": visible_to,
            "default": "main",
            "prs": {},
            "branches": ["main"],
            **extra,
        }
        self.scenario["repos"][name] = repo
        self.save()
        return repo

    def pr(self, name: str, number: int, **spec: Any) -> None:
        spec = {"state": "OPEN", **spec}
        self.scenario["repos"][name]["prs"][str(number)] = spec
        self.save()

    def set(self, **values: Any) -> None:
        self.scenario.update(values)
        self.save()

    @property
    def tokens(self) -> list[str]:
        return [a["token"] for a in self.scenario["accounts"]]

    # -- using it ---------------------------------------------------------------------------
    def reader(self, timeout: float = 60) -> PrReader:
        return PrReader(Gh(timeout), self.cache, sleep=self.sleeps.append)

    def run_gh(self, *argv: str, token: str | None = None) -> subprocess.CompletedProcess[str]:
        """The fake ``gh`` run directly (to compare its answers with the real samples)."""
        env = {**os.environ, **({"GH_TOKEN": token} if token else {})}
        return subprocess.run(
            ["gh", *argv], env=env, capture_output=True, text=True, check=False, timeout=30
        )

    # -- reading what happened --------------------------------------------------------------
    def log(self) -> list[dict[str, Any]]:
        path = self.base / "gh.log"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text().splitlines() if line]

    def api_calls(self) -> list[dict[str, Any]]:
        return [c for c in self.log() if c["argv"][:2] == ["api", "graphql"]]

    def verbs(self, *prefix: str) -> list[dict[str, Any]]:
        return [c for c in self.log() if c["argv"][: len(prefix)] == list(prefix)]

    def ssh_log(self) -> list[list[str]]:
        path = self.base / "ssh.log"
        return [json.loads(x) for x in path.read_text().splitlines()] if path.exists() else []

    def stored_text(self) -> str:
        """Everything the engine wrote (the cache directory) plus the call log."""
        parts = [
            p.read_text(errors="replace") for p in sorted(self.cache.root.rglob("*")) if p.is_file()
        ]
        log = self.base / "gh.log"
        return "\n".join([*parts, log.read_text() if log.exists() else ""])

    def assert_no_secret(self, *texts: object) -> None:
        """No fake token in the store, the logs, the captured output or any given text."""
        captured = self.capsys.readouterr()
        haystack = "\n".join([self.stored_text(), captured.out, captured.err, *map(str, texts)])
        for token in self.tokens:
            assert token not in haystack

    def assert_read_only(self) -> None:
        for call in self.log():
            check_argv(call["argv"])  # the same allow-list the reader enforces
            if call["argv"][0] == "api":
                assert "mutation" not in " ".join(call["argv"]).lower()
            assert call["argv"][:2] != ["auth", "switch"]

    def assert_hermetic(self) -> None:
        assert {Path(c[0]).name for c in self.calls} <= _ALLOWED_PROGRAMS, self.calls


def _install(bin_dir: Path, real_git: str, with_gh: bool, with_ssh: bool) -> None:
    bin_dir.mkdir(parents=True)
    python = shlex.quote(sys.executable)
    for name, impl, wanted in (("gh", _GH_IMPL, with_gh), ("ssh", _SSH_IMPL, with_ssh)):
        if wanted:
            (bin_dir / f"{name}_impl.py").write_text(impl, encoding="utf-8")
            _script(
                bin_dir / name,
                f'exec {python} {shlex.quote(str(bin_dir / (name + "_impl.py")))} "$@"\n',
            )
    _script(
        bin_dir / "git",
        f'case "$1" in config|init|remote) PATH=/usr/bin:/bin exec {shlex.quote(real_git)} "$@";; esac\n'
        "exit 97\n",
    )


def _guard(monkeypatch: pytest.MonkeyPatch, world: GhWorld) -> None:
    real_init = subprocess.Popen.__init__

    def guarded(self, args, *rest, **kwargs):  # type: ignore[no-untyped-def]
        argv = [str(part) for part in args] if isinstance(args, list | tuple) else [str(args)]
        world.calls.append(argv)
        assert not kwargs.get("shell"), f"shell commands are not allowed: {argv}"
        assert Path(argv[0]).name in _ALLOWED_PROGRAMS, f"unexpected subprocess: {argv}"
        real_init(self, args, *rest, **kwargs)

    def no_network(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        raise OSError("network is disabled in these tests")

    monkeypatch.setattr(subprocess.Popen, "__init__", guarded)
    monkeypatch.setattr(socket.socket, "connect", no_network)


class GhWorldOpts(TypedDict, total=False):
    with_gh: bool
    with_ssh: bool


def make_gh_world(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    **opts: Unpack[GhWorldOpts],
) -> GhWorld:
    with_gh, with_ssh = opts.get("with_gh", True), opts.get("with_ssh", True)
    _clear_environment(monkeypatch)
    real_git = shutil.which("git")
    assert real_git, "git is required"
    base = tmp_path / "ghworld"
    base.mkdir()
    _install(base / "bin", real_git, with_gh, with_ssh)
    (base / "state").mkdir()
    monkeypatch.setenv("PATH", str(base / "bin"))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for key, value in {
        "FAKE_GH": str(base / "scenario.json"),
        "FAKE_GH_LOG": str(base / "gh.log"),
        "FAKE_GH_STATE": str(base / "state"),
        "FAKE_SSH_LOG": str(base / "ssh.log"),
        "FAKE_SSH_HOSTS": str(base / "ssh-hosts.json"),
    }.items():
        monkeypatch.setenv(key, value)
    world = GhWorld(base, PrCache(tmp_path / "store"), capsys)
    world.save()
    _guard(monkeypatch, world)
    return world


def spec_of(sample: dict[str, Any]) -> dict[str, Any]:
    """The fake-scenario spec that makes the fake answer exactly like a real ``sample``."""
    pr = sample["data"]["repository"]["pullRequest"]
    rollup = pr["commits"]["nodes"][0]["commit"]["statusCheckRollup"]
    return {
        "state": pr["state"],
        "draft": pr["isDraft"],
        "base": pr["baseRefName"],
        "head": pr["headRefName"],
        "mergeable": pr["mergeable"],
        "review": pr["reviewDecision"],
        "title": pr["title"],
        "head_repo": pr["headRepository"]["nameWithOwner"],
        "ci": rollup["state"],
        "threads": [n["isResolved"] for n in pr["reviewThreads"]["nodes"]],
    }


def normalized(response: Any) -> Any:
    """A response with opaque cursor strings and source locations replaced by placeholders."""
    if isinstance(response, dict):
        return {
            k: ("<cursor>" if k == "endCursor" and isinstance(v, str) else normalized(v))
            for k, v in response.items()
            if k not in ("locations", "message")
        }
    if isinstance(response, list):
        return [normalized(v) for v in response]
    return response


@pytest.fixture
def gh_world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]):
    made = make_gh_world(tmp_path, monkeypatch, capsys)
    yield made
    made.assert_hermetic()
