"""Execute every documented progress command against disposable task state."""

import shlex
from importlib.resources import files

from ai_governance.session.cli import main


def test_documented_progress_commands(monkeypatch, tmp_path):
    monkeypatch.setenv("SPECOPS_PROGRESS_DIR", str(tmp_path / "progress"))
    monkeypatch.chdir(tmp_path)
    document = files("ai_governance").joinpath("resources", "workflows", "progress.md").read_text()
    for line in document.splitlines():
        if not line.startswith("progress "):
            continue
        args = shlex.split(line)[1:]
        args = ["doc-task" if value == "<task-id>" else value for value in args]
        result = main(args)
        # An empty workspace has no active task until the documented new command.
        assert result == (1 if args[0] == "here" else 0), line
