from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from workspace_engine.run_local.constants import (
    find_project_root,
    load_project_config,
)


def test_find_project_root_with_specops(tmp_path: Path) -> None:
    root = tmp_path / "my_project"
    root.mkdir()
    (root / ".specops").mkdir()

    nested = root / "src" / "deep" / "nested"
    nested.mkdir(parents=True)

    assert find_project_root(nested) == root


def test_find_project_root_with_git(tmp_path: Path) -> None:
    root = tmp_path / "git_project"
    root.mkdir()
    (root / ".git").mkdir()

    nested = root / "a" / "b" / "c"
    nested.mkdir(parents=True)

    assert find_project_root(nested) == root


def test_find_project_root_fallback(tmp_path: Path) -> None:
    nested = tmp_path / "standalone" / "dir"
    nested.mkdir(parents=True)

    # When no .specops or .git exists in ancestors, return the resolved path
    assert find_project_root(nested) == nested.resolve()


def test_find_project_root_with_boundary(tmp_path: Path) -> None:
    outer_git = tmp_path / "outer"
    outer_git.mkdir()
    (outer_git / ".git").mkdir()

    boundary_dir = outer_git / "boundary"
    boundary_dir.mkdir()

    nested = boundary_dir / "sub" / "deep"
    nested.mkdir(parents=True)

    # Without boundary, it would find outer_git
    assert find_project_root(nested) == outer_git

    # With boundary, it must not escape past boundary_dir
    assert find_project_root(nested, boundary=boundary_dir) == nested.resolve()


def test_find_project_root_stops_at_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_home = tmp_path / "fake_home"
    fake_home.mkdir()
    (fake_home / ".git").mkdir()  # Dotfiles in home

    nested = fake_home / "projects" / "untracked_dir"
    nested.mkdir(parents=True)

    monkeypatch.setattr(Path, "home", lambda: fake_home)

    # Walking upwards from nested must stop before treating fake_home as project root
    assert find_project_root(nested) == nested.resolve()


def test_load_project_config_deep_subdirectory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "my_repo"
    specops_dir = root / ".specops"
    specops_dir.mkdir(parents=True)
    cfg_file = specops_dir / "config.json"
    cfg_file.write_text(
        json.dumps(
            {
                "project_name": "custom-specops-project",
                "domain": "specops.local",
            }
        ),
        encoding="utf-8",
    )

    deep_dir = root / "apps" / "service_a" / "src"
    deep_dir.mkdir(parents=True)

    # 1. Test passing start_dir explicitly
    cfg = load_project_config(start_dir=deep_dir)
    assert cfg["project_name"] == "custom-specops-project"
    assert cfg["domain"] == "specops.local"

    # 2. Test using cwd
    monkeypatch.chdir(deep_dir)
    cfg_cwd = load_project_config()
    assert cfg_cwd["project_name"] == "custom-specops-project"
    assert cfg_cwd["domain"] == "specops.local"


def test_load_project_config_malformed_json(tmp_path: Path) -> None:
    root = tmp_path / "broken_repo"
    specops_dir = root / ".specops"
    specops_dir.mkdir(parents=True)
    cfg_file = specops_dir / "config.json"
    cfg_file.write_text("{ this is malformed json !!! }", encoding="utf-8")

    deep_dir = root / "sub"
    deep_dir.mkdir()

    with pytest.raises(ValueError, match=r"Invalid JSON in config file.*line \d+, column \d+"):
        load_project_config(start_dir=deep_dir)


def test_find_project_root_start_dir_is_a_file(tmp_path: Path) -> None:
    root = tmp_path / "file_project"
    root.mkdir()
    (root / ".git").mkdir()
    a_file = root / "notes.txt"
    a_file.write_text("hi")

    assert find_project_root(a_file) == root


def test_find_project_root_home_lookup_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Path.home() and pwd.getpwuid() both fail: home detection degrades gracefully
    and the walk simply continues to the filesystem root."""
    import pwd

    nested = tmp_path / "no_home_project" / "deep"
    nested.mkdir(parents=True)

    def _raise_home():
        raise RuntimeError("no home")

    def _raise_pwd(uid):
        raise KeyError("no such user")

    monkeypatch.setattr(Path, "home", _raise_home)
    monkeypatch.setattr(pwd, "getpwuid", _raise_pwd)

    # No .git/.specops anywhere up to "/" -> eventually stops at filesystem root.
    result = find_project_root(nested)
    assert result in (nested.resolve(), Path("/"))


def test_find_project_root_real_home_matches_via_pwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Path.home() fails but pwd.getpwuid() succeeds and matches an ancestor:
    the walk stops there instead of escaping into it."""
    import pwd

    fake_home = tmp_path / "real_home"
    fake_home.mkdir()
    (fake_home / ".git").mkdir()
    nested = fake_home / "projects" / "x"
    nested.mkdir(parents=True)

    def _raise_home():
        raise RuntimeError("no home")

    real_pwent = pwd.getpwuid(os.getuid())
    fake_pwent = type("FakePwent", (), {"pw_dir": str(fake_home)})()

    monkeypatch.setattr(Path, "home", _raise_home)
    monkeypatch.setattr(pwd, "getpwuid", lambda uid: fake_pwent)

    assert find_project_root(nested) == nested.resolve()
    assert real_pwent  # sanity: the real pwent was fetchable in this environment


def test_find_project_root_boundary_without_marker_falls_through(tmp_path: Path) -> None:
    """The walk reaches the boundary directory without finding a marker: it
    breaks at the boundary check rather than escaping further up."""
    boundary_dir = tmp_path / "boundary"
    nested = boundary_dir / "sub" / "deep"
    nested.mkdir(parents=True)

    assert find_project_root(nested, boundary=boundary_dir) == nested.resolve()


def test_find_project_root_boundary_mismatch_breaks_immediately(tmp_path: Path) -> None:
    """boundary points somewhere unrelated to the walk: the very first parent is
    neither equal to nor relative to it, so the loop breaks right away."""
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)
    unrelated_boundary = tmp_path / "elsewhere"
    unrelated_boundary.mkdir()

    assert find_project_root(nested, boundary=unrelated_boundary) == nested.resolve()


def test_find_project_root_at_filesystem_root_exhausts_loop() -> None:
    """Starting exactly at "/" makes the walk a single iteration with no more
    parents to visit, so the for loop completes naturally (no break, no return)."""
    result = find_project_root(Path("/"))
    assert result == Path("/")


def test_load_project_config_explicit_path_missing(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist.json"
    with pytest.raises(FileNotFoundError, match="Config file not found"):
        load_project_config(config_path=missing)


def test_load_project_config_os_error_on_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "os_error_repo"
    specops_dir = root / ".specops"
    specops_dir.mkdir(parents=True)
    cfg_file = specops_dir / "config.json"
    cfg_file.write_text("{}", encoding="utf-8")

    import builtins

    real_open = builtins.open

    def _raising_open(path, *a, **kw):
        if str(path) == str(cfg_file):
            raise OSError("boom")
        return real_open(path, *a, **kw)

    monkeypatch.setattr(builtins, "open", _raising_open)
    cfg = load_project_config(start_dir=root)
    # Falls back to defaults since the OSError is swallowed.
    assert cfg["project_name"] == "generic"


def test_load_project_config_explicit_path_existing(tmp_path: Path) -> None:
    cfg_file = tmp_path / "custom-config.json"
    cfg_file.write_text(json.dumps({"project_name": "explicit-project"}), encoding="utf-8")
    cfg = load_project_config(config_path=cfg_file)
    assert cfg["project_name"] == "explicit-project"


def test_load_project_config_xdg_config_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "xdg_repo"
    root.mkdir()
    xdg_dir = tmp_path / "xdg" / "specops"
    xdg_dir.mkdir(parents=True)
    (xdg_dir / "config.json").write_text(
        json.dumps({"project_name": "xdg-project"}), encoding="utf-8"
    )

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    cfg = load_project_config(start_dir=root)
    assert cfg["project_name"] == "xdg-project"


def test_load_project_config_non_dict_json_keeps_defaults(tmp_path: Path) -> None:
    root = tmp_path / "list_repo"
    specops_dir = root / ".specops"
    specops_dir.mkdir(parents=True)
    (specops_dir / "config.json").write_text("[1, 2, 3]", encoding="utf-8")

    cfg = load_project_config(start_dir=root)
    assert cfg["project_name"] == "generic"


def test_load_project_config_default_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()

    monkeypatch.chdir(empty_dir)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)

    # Ensure ~/.config/specops/config.json is not picked up by setting HOME to empty_dir
    monkeypatch.setenv("HOME", str(empty_dir))

    cfg = load_project_config(start_dir=empty_dir)
    assert cfg["project_name"] == "generic"
    assert cfg["domain"] == "generic.com"
