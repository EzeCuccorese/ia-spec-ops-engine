from pathlib import Path

from rules.cli import main


def test_cli_list_action(capsys) -> None:
    main(["list"])
    captured = capsys.readouterr().out
    assert "Engineering Rules Catalog" in captured
    assert "java-spring" in captured


def test_cli_local_install_and_uninstall(tmp_path: Path) -> None:
    main(["install", "--local", "--all", "--root", str(tmp_path)])

    manifest_path = tmp_path / ".specops" / "rules" / "manifest.json"
    assert manifest_path.exists()
    assert (tmp_path / "AGENTS.md").exists()
    assert (tmp_path / "CLAUDE.md").exists()
    assert (tmp_path / ".cursorrules").exists()

    main(["uninstall", "--local", "--root", str(tmp_path)])
    assert not manifest_path.exists()
    assert not (tmp_path / "AGENTS.md").exists()
