from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path

import pytest
from ai_governance import completion
from ai_governance.completion import walker
from ai_governance.completion.zsh import render
from ai_governance.install.installer import (
    install_user,
    sync_completions,
    uninstall_user,
)

RAN: list[str] = []


def _fake_cli() -> None:
    """A dispatcher like ai-governance/ws: stubs forward to modules owning their parser."""
    import sys

    argv = sys.argv[1:]
    if argv[:1] == ["deploy"]:  # hand-parsed like jira/confluence: honours --help
        if "--help" not in argv:
            RAN.append("deploy")
        return
    if argv[:1] == ["telemetry"]:
        parser = argparse.ArgumentParser(prog="tool telemetry")
        sub = parser.add_subparsers()
        report = sub.add_parser("report", help="Today and month")
        report.add_argument("--scope", choices=["user", "project"], help="Where")
        report.add_argument("--json", action="store_true")
        parser.parse_args(argv[1:])
        return
    parser = argparse.ArgumentParser(prog="tool")
    sub = parser.add_subparsers()
    sub.add_parser("telemetry", help="Spend: it's 'quoted'", add_help=False)
    sub.add_parser("deploy", help="Ship it", add_help=False)
    kube = sub.add_parser("kube", help="Pods")
    kube.add_argument("action", choices=["env", "logs"])
    parser.parse_args(argv)


@pytest.fixture
def tree(monkeypatch: pytest.MonkeyPatch) -> dict:
    for name in walker.STOPPED:
        monkeypatch.setattr(argparse.ArgumentParser, name, walker._stop)
    walked = walker.Walker(_fake_cli, "tool").tree()
    monkeypatch.undo()
    return walked


def test_walker_follows_stubs_without_running_commands(tree: dict) -> None:
    subs = {s["name"]: s for s in tree["subcommands"]}
    report = subs["telemetry"]["subcommands"][0]
    assert report["name"] == "report" and report["help"] == "Today and month"
    scope = next(o for o in report["options"] if o["flags"] == ["--scope"])
    assert scope["choices"] == ["user", "project"] and scope["value"] is True
    assert subs["kube"]["positionals"][0]["choices"] == ["env", "logs"]
    assert subs["deploy"]["subcommands"] == [] and RAN == []


@pytest.mark.skipif(shutil.which("zsh") is None, reason="zsh not installed")
@pytest.mark.parametrize(
    ("words", "expected"),
    [
        (["tool", ""], "telemetry:Spend: it's 'quoted'"),
        (["tool", "telemetry", ""], "report:Today and month"),
        (["tool", "telemetry", "report", "--scope", ""], "user project"),
        (["tool", "telemetry", "report", "--"], "--json"),
        (["tool", "kube", ""], "env logs"),
    ],
)
def test_zsh_script_completes_the_typed_path(
    tree: dict, tmp_path: Path, words: list[str], expected: str
) -> None:
    script = tmp_path / "_tool"
    script.write_text(render(tree))
    harness = (
        '_describe() { print -r -- "${(@P)${@[-1]}}"; }\n'
        'compadd() { print -r -- "${(@P)${@[-1]}}"; }\n'
        "_files() { print FILES; }\n"
        'eval "$(sed \'$d\' "$1")"\n'
        'shift; words=("$@"); CURRENT=${#words}; _tool\n'
    )
    out = subprocess.run(
        ["zsh", "-f", "-c", harness, "zsh", str(script), *words],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert expected in out


def test_install_writes_completions_and_uninstall_removes_them(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, tree: dict
) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    monkeypatch.setenv("AI_GOVERNANCE_STATE_DIR", str(tmp_path / "state"))
    rc = tmp_path / "home/.zshrc"
    rc.parent.mkdir(parents=True)
    rc.write_text("source $ZSH/oh-my-zsh.sh\n")
    ws = {**tree, "name": "ws"}
    monkeypatch.setattr(completion, "walk", lambda prog: ws if prog == "ws" else None)

    install_user(["claude"])
    script = completion.zsh_dir() / "_ws"
    assert script.read_text().startswith("#compdef ws")
    lines = rc.read_text().splitlines()
    assert lines[2] == f'fpath=("{completion.zsh_dir()}" $fpath)' and "oh-my-zsh" in lines[-1]

    changed = {**ws, "subcommands": ws["subcommands"][:1]}
    monkeypatch.setattr(completion, "walk", lambda prog: changed if prog == "ws" else None)
    assert sync_completions().changed and "deploy" not in script.read_text()

    uninstall_user(["claude"])
    assert not script.exists() and rc.read_text() == "source $ZSH/oh-my-zsh.sh\n"
    assert sync_completions() is None


def test_no_completions_without_a_zshrc(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(completion, "walk", lambda prog: pytest.fail("must not walk"))
    assert completion.artifacts() == []
