"""
Unit tests for workspace_engine.cli.init_env.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from workspace_engine.cli import init_env


def test_parse_example_file_missing_returns_empty(tmp_path: Path) -> None:
    assert init_env.parse_example_file(tmp_path / "missing.example") == []


def test_parse_example_file_parses_comments_and_vars(tmp_path: Path) -> None:
    example = tmp_path / ".env.example"
    example.write_text(
        "# A comment\n# continued\nFOO=bar\n\nBAZ=\n# orphan comment with no var after\n",
        encoding="utf-8",
    )
    items = init_env.parse_example_file(example)
    assert items == [
        ("A comment — continued", "FOO", "bar"),
        ("", "BAZ", ""),
    ]


def test_parse_example_file_ignores_bare_hash_line(tmp_path: Path) -> None:
    example = tmp_path / ".env.example"
    example.write_text("#\nFOO=bar\n", encoding="utf-8")
    items = init_env.parse_example_file(example)
    assert items == [("", "FOO", "bar")]


def test_parse_example_file_strips_quotes(tmp_path: Path) -> None:
    example = tmp_path / ".env.example"
    example.write_text("FOO=\"bar\"\nBAZ='qux'\n", encoding="utf-8")
    items = init_env.parse_example_file(example)
    assert ("", "FOO", "bar") in items
    assert ("", "BAZ", "qux") in items


def test_sync_env_file_missing_template_returns_error(tmp_path: Path) -> None:
    result = init_env.sync_env_file(tmp_path / "missing.example", tmp_path / ".env")
    assert result == 1


def test_sync_env_file_check_only_reports_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    example = tmp_path / ".env.example"
    example.write_text("FOO=bar\n", encoding="utf-8")
    target = tmp_path / ".env"

    result = init_env.sync_env_file(example, target, check_only=True)

    assert result == 1
    assert "FOO" in capsys.readouterr().out


def test_sync_env_file_check_only_fully_configured(tmp_path: Path) -> None:
    example = tmp_path / ".env.example"
    example.write_text("FOO=bar\n", encoding="utf-8")
    target = tmp_path / ".env"
    target.write_text("FOO=configured\n", encoding="utf-8")

    result = init_env.sync_env_file(example, target, check_only=True)

    assert result == 0


def test_sync_env_file_creates_target_from_template(tmp_path: Path) -> None:
    example = tmp_path / ".env.example"
    example.write_text("FOO=bar\n", encoding="utf-8")
    target = tmp_path / "nested" / ".env"
    target.parent.mkdir()

    with patch("builtins.input", return_value=""):
        result = init_env.sync_env_file(example, target)

    assert result == 0
    assert target.is_file()
    assert "FOO=bar" in target.read_text(encoding="utf-8")


def test_sync_env_file_skips_already_set_vars_unless_forced(tmp_path: Path) -> None:
    example = tmp_path / ".env.example"
    example.write_text("FOO=bar\n", encoding="utf-8")
    target = tmp_path / ".env"
    target.write_text("FOO=already\n", encoding="utf-8")

    with patch("builtins.input") as mock_input:
        result = init_env.sync_env_file(example, target)

    mock_input.assert_not_called()
    assert result == 0
    assert "FOO=already" in target.read_text(encoding="utf-8")


def test_sync_env_file_force_prompts_for_all(tmp_path: Path) -> None:
    example = tmp_path / ".env.example"
    example.write_text("# desc\nFOO=bar\n", encoding="utf-8")
    target = tmp_path / ".env"
    target.write_text("FOO=already\n", encoding="utf-8")

    with patch("builtins.input", return_value="new-value"):
        result = init_env.sync_env_file(example, target, force=True)

    assert result == 0
    assert "FOO=new-value" in target.read_text(encoding="utf-8")


def test_sync_env_file_prompts_with_no_default_or_current(tmp_path: Path) -> None:
    example = tmp_path / ".env.example"
    example.write_text("BAZ=\n", encoding="utf-8")
    target = tmp_path / ".env"

    with patch("builtins.input", return_value="typed") as mock_input:
        result = init_env.sync_env_file(example, target)

    mock_input.assert_called_once()
    assert result == 0
    assert "BAZ=typed" in target.read_text(encoding="utf-8")


def test_sync_env_file_user_input_overrides_default(tmp_path: Path) -> None:
    example = tmp_path / ".env.example"
    example.write_text("FOO=default\n", encoding="utf-8")
    target = tmp_path / ".env"

    with patch("builtins.input", return_value="typed-value"):
        init_env.sync_env_file(example, target)

    assert "FOO=typed-value" in target.read_text(encoding="utf-8")


def test_sync_env_file_multiline_value_is_quoted(tmp_path: Path) -> None:
    example = tmp_path / ".env.example"
    example.write_text("FOO=bar\n", encoding="utf-8")
    target = tmp_path / ".env"
    target.write_text("FOO=line1\\nline2\n", encoding="utf-8")

    with patch.object(init_env, "parse_dotenv", return_value={"FOO": "line1\nline2"}):
        init_env.sync_env_file(example, target, force=False)

    content = target.read_text(encoding="utf-8")
    assert 'FOO="line1\nline2"' in content


def test_main_uses_config_env_example(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path
    (root / "config").mkdir()
    (root / "config" / ".env.example").write_text("FOO=bar\n", encoding="utf-8")
    monkeypatch.setattr(init_env, "find_project_root", lambda: root)
    monkeypatch.setattr("sys.argv", ["init-env"])

    with patch("builtins.input", return_value=""), pytest.raises(SystemExit) as exc:
        init_env.main()

    assert exc.value.code == 0
    assert (root / "config" / ".env").is_file()


def test_main_falls_back_to_templates_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path
    (root / "templates" / "config").mkdir(parents=True)
    (root / "templates" / "config" / ".env.example").write_text("FOO=bar\n", encoding="utf-8")
    monkeypatch.setattr(init_env, "find_project_root", lambda: root)
    monkeypatch.setattr("sys.argv", ["init-env", "--force", "--check-only"])

    with pytest.raises(SystemExit) as exc:
        init_env.main()

    # No .env exists yet, so the template var is reported as missing (exit 1).
    assert exc.value.code == 1
