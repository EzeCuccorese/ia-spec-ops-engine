"""Claude worktree hook acceptance coverage for @s6."""

from __future__ import annotations

import io
import json
from pathlib import Path
from unittest.mock import patch

from workspace_engine.integrations.claude.worktree_hook import main, suggest_worktree_path


def test_suggests_confined_sanitized_path(tmp_path: Path) -> None:
    result = suggest_worktree_path(
        {"root_path": "/projects/My Repo", "worktree_base": "feat/ONB-42"}, tmp_path
    )
    assert result is not None
    assert result.parent == tmp_path.resolve()
    assert result.name == "my-repo-onb-42"


def test_collision_uses_deterministic_suffix_and_never_escapes(tmp_path: Path) -> None:
    first = tmp_path / "repo-branch"
    first.mkdir()
    payload = {"root_path": "/src/repo", "worktree_base": "branch"}
    result = suggest_worktree_path(payload, tmp_path)
    assert result is not None and result != first
    assert result.resolve().is_relative_to(tmp_path.resolve())
    assert suggest_worktree_path({"root_path": "", "worktree_base": "../../x"}, tmp_path) is None


def test_hook_is_fail_open_for_invalid_payload(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("WORKSPACE_WORKTREES_DIR", str(tmp_path))
    monkeypatch.setattr("sys.stdin", io.StringIO("not-json"))
    assert main([]) == 0
    assert capsys.readouterr().out == ""

    monkeypatch.setattr(
        "sys.stdin",
        io.StringIO(json.dumps({"root_path": "/src/repo", "worktree_base": "branch"})),
    )
    assert main([]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["hookSpecificOutput"]["hookEventName"] == "WorktreeCreate"
    assert Path(data["hookSpecificOutput"]["workTreePath"]).is_relative_to(tmp_path)


def test_suggest_worktree_path_rejects_non_string_values(tmp_path: Path) -> None:
    assert suggest_worktree_path({"root_path": 42, "worktree_base": "branch"}, tmp_path) is None
    assert suggest_worktree_path({"root_path": "/src/repo"}, tmp_path) is None


def test_suggest_worktree_path_rejects_empty_slug(tmp_path: Path) -> None:
    # A root whose basename slugifies to empty (only punctuation).
    assert suggest_worktree_path({"root_path": "///", "worktree_base": "branch"}, tmp_path) is None
    assert (
        suggest_worktree_path({"root_path": "/src/repo", "worktree_base": "!!!"}, tmp_path) is None
    )


def test_suggest_worktree_path_rejects_escape_via_is_relative_to(tmp_path: Path) -> None:
    payload = {"root_path": "/src/repo", "worktree_base": "branch"}
    with patch("pathlib.Path.is_relative_to", return_value=False):
        assert suggest_worktree_path(payload, tmp_path) is None


def test_suggest_worktree_path_rejects_second_escape_after_collision(tmp_path: Path) -> None:
    payload = {"root_path": "/src/repo", "worktree_base": "branch"}
    first = tmp_path / "repo-branch"
    first.mkdir()
    with patch("pathlib.Path.is_relative_to", side_effect=[True, False]):
        assert suggest_worktree_path(payload, tmp_path) is None


def test_hook_main_ignores_non_dict_payload(monkeypatch, capsys) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps([1, 2, 3])))
    assert main([]) == 0
    assert capsys.readouterr().out == ""


def test_hook_main_no_destination_returns_zero(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("WORKSPACE_WORKTREES_DIR", str(tmp_path))
    monkeypatch.setattr(
        "sys.stdin", io.StringIO(json.dumps({"root_path": "", "worktree_base": "branch"}))
    )
    assert main([]) == 0
    assert capsys.readouterr().out == ""
