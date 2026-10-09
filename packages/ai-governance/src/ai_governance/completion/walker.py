"""Dump a console script's argparse tree as JSON (stdlib only).

Runs inside the target tool's own interpreter (``python -I walker.py <prog>``), so it
can describe ``ws`` or ``spec`` without ai-governance importing them. The entry point
is called with ``sys.argv = [prog, *path]`` and every ArgumentParser is stopped the
moment it would parse or print help, so no command body ever runs. Subcommands
registered as bare stubs (dispatchers that forward to another module's parser) are
walked by calling the entry point again as ``prog <path> --help``: an argparse command
is stopped before parsing, and a hand-parsed one only prints its help. A command that
ignores ``--help`` would run, so every command must honour it.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import sys
from collections.abc import Callable
from dataclasses import dataclass
from importlib.metadata import entry_points
from typing import Any

MAX_DEPTH = 4
STOPPED = ("parse_args", "parse_known_args", "parse_intermixed_args", "print_help")


class _Captured(BaseException):  # BaseException: survives `except Exception` in mains
    def __init__(self, parser: argparse.ArgumentParser) -> None:
        self.parser = parser


def _stop(self: argparse.ArgumentParser, *_args: Any, **_kwargs: Any) -> Any:
    raise _Captured(self)


def _subparsers(parser: argparse.ArgumentParser) -> dict[str, tuple[Any, str]]:
    found: dict[str, tuple[Any, str]] = {}
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            helps = {choice.dest: choice.help or "" for choice in action._choices_actions}
            for name, sub in action.choices.items():
                found[name] = (sub, helps.get(name, ""))
    return found


def _arguments(parser: argparse.ArgumentParser) -> tuple[list[dict], list[dict]]:
    options, positionals = [], []
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction) or action.help == argparse.SUPPRESS:
            continue
        item = {
            "help": (action.help or "").replace("%(default)s", str(action.default)),
            "choices": [str(c) for c in action.choices] if action.choices else [],
        }
        if action.option_strings:
            options.append({**item, "flags": action.option_strings, "value": action.nargs != 0})
        else:
            positionals.append({**item, "name": action.dest})
    return options, positionals


def _is_stub(parser: argparse.ArgumentParser) -> bool:
    return not any(not isinstance(a, argparse._HelpAction) for a in parser._actions)


@dataclass(frozen=True)
class Walker:
    """Walks one console script: ``entry`` is its loaded entry point."""

    entry: Callable[[], Any]
    prog: str

    def capture(self, path: list[str]) -> Any:
        """The first parser the entry point reaches for ``prog *path``, or None."""
        sys.argv = [self.prog, *path]
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            try:
                self.entry()
            except _Captured as captured:
                return captured.parser
            except BaseException:  # noqa: BLE001 - a command without argparse: leaf
                return None
        return None

    def node(self, path: list[str], parser: Any, seen: frozenset[int]) -> dict:
        seen = seen | {id(parser)}
        options, positionals = _arguments(parser)
        subcommands = []
        for name, (sub, help_text) in _subparsers(parser).items():
            target = sub
            if _is_stub(sub) and len(path) < MAX_DEPTH:
                target = self.resolve([*path, name], seen) or sub
            child = self.node([*path, name], target, seen) if id(target) not in seen else {}
            subcommands.append({"help": help_text, **child, "name": name})
        return {"options": options, "positionals": positionals, "subcommands": subcommands}

    def resolve(self, path: list[str], seen: frozenset[int]) -> Any:
        """The real parser behind a stub; a dispatcher's parser that names the stub again
        (``ai-governance install`` -> the shared install parser) resolves to that entry."""
        parser = self.capture([*path, "--help"])
        if parser is None or id(parser) in seen:
            return None
        nested = _subparsers(parser).get(path[-1])
        return nested[0] if nested else parser

    def tree(self) -> dict:
        root = self.capture([])
        if root is None:
            return {"name": self.prog, "options": [], "positionals": [], "subcommands": []}
        return {"name": self.prog, **self.node([], root, frozenset())}


def stop_parsers() -> None:
    for name in STOPPED:
        setattr(argparse.ArgumentParser, name, _stop)


def tree(prog: str) -> dict:
    (script,) = entry_points(group="console_scripts", name=prog)
    stop_parsers()
    return Walker(script.load(), prog).tree()


if __name__ == "__main__":
    sys.stdout.write(json.dumps(tree(sys.argv[1])))
