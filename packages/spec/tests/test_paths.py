from pathlib import Path

import pytest

from spec.core.paths import PathBoundary, PathOutsideRootError, UnsafeRootError


def test_resolves_normal_child_inside_root(tmp_path: Path) -> None:
    boundary = PathBoundary(tmp_path)

    assert boundary.resolve(".spec/state.json") == tmp_path / ".spec/state.json"


def test_rejects_parent_escape(tmp_path: Path) -> None:
    boundary = PathBoundary(tmp_path / "project")

    with pytest.raises(PathOutsideRootError):
        boundary.resolve("../other-project/secrets.env")


def test_rejects_absolute_path_outside_root(tmp_path: Path) -> None:
    boundary = PathBoundary(tmp_path / "project")

    with pytest.raises(PathOutsideRootError):
        boundary.resolve(tmp_path / "other" / "file.txt")


def test_rejects_symlink_escape(tmp_path: Path) -> None:
    project = tmp_path / "project"
    outside = tmp_path / "outside"
    project.mkdir()
    outside.mkdir()
    (project / "escape").symlink_to(outside, target_is_directory=True)
    boundary = PathBoundary(project)

    with pytest.raises(PathOutsideRootError):
        boundary.resolve("escape/file.txt")


@pytest.mark.parametrize("candidate", [Path("/"), Path.home()])
def test_rejects_broad_dangerous_roots(candidate: Path) -> None:
    with pytest.raises(UnsafeRootError):
        PathBoundary(candidate)
