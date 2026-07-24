import json
import sys
from pathlib import Path
from agents.claude.hooks.enforce_repo_boundary import (
    find_workspace_root,
    is_path_safe,
    evaluate_bash_command,
    process_hook,
)

def test_find_workspace_root(tmp_path):
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    (claude_dir / "settings.json").write_text("{}")
    
    sub_dir = tmp_path / "repositories" / "myrepo"
    sub_dir.mkdir(parents=True)
    
    root = find_workspace_root(sub_dir)
    assert root == tmp_path


def test_is_path_safe(tmp_path):
    ok, msg = is_path_safe("repositories/myrepo/file.py", tmp_path)
    assert ok is True
    assert msg == ""

    ok, msg = is_path_safe("docs/spec.md", tmp_path)
    assert ok is True

    ok, msg = is_path_safe(".lavish/index.html", tmp_path)
    assert ok is True

    # Path traversal attempt
    ok, msg = is_path_safe("repositories/../outside.py", tmp_path)
    assert ok is False
    assert "path traversal" in msg

    # Forbidden root directory write
    ok, msg = is_path_safe("config/secret.json", tmp_path)
    assert ok is False
    assert "must be inside one of" in msg


def test_evaluate_bash_command():
    # Safe command
    ok, _ = evaluate_bash_command("ls -la repositories/")
    assert ok is True

    # Redirect to .claude/
    ok, msg = evaluate_bash_command("echo 'hack' > .claude/settings.json")
    assert ok is False
    assert ".claude" in msg

    # cp command into .claude/
    ok, msg = evaluate_bash_command("cp myfile.txt .claude/hooks/")
    assert ok is False
    assert ".claude" in msg

    # Invalid shell syntax (unbalanced quote)
    ok, msg = evaluate_bash_command("echo 'broken quote")
    assert ok is False
    assert "ambiguous" in msg


def test_process_hook():
    payload_write = json.dumps({
        "tool_name": "Write",
        "tool_input": {"file_path": "repositories/repo1/main.py"}
    })
    code, msg = process_hook(payload_write)
    assert code == 0

    payload_bad_write = json.dumps({
        "tool_name": "Write",
        "tool_input": {"file_path": "unauthorized.txt"}
    })
    code, msg = process_hook(payload_bad_write)
    assert code == 2

    payload_invalid_json = "NOT_JSON"
    code, msg = process_hook(payload_invalid_json)
    assert code == 0
