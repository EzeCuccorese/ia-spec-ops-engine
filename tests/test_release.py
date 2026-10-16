"""Version calculation and changelog fallback for the single project release."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from scripts.release import Commit

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_release() -> ModuleType:
    spec = importlib.util.spec_from_file_location("release", REPO_ROOT / "scripts" / "release.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


release = _load_release()


def c(subject: str, body: str = "") -> Commit:
    return release.Commit(subject=subject, body=body)


@pytest.mark.parametrize(
    ("commits", "expected"),
    [
        ([c("fix(ws): handle empty log")], "1.0.1"),
        ([c("perf: cache lookups"), c("fix: typo")], "1.0.1"),
        ([c("feat(spec): new command"), c("fix: typo")], "1.1.0"),
        ([c("feat!: drop old flag")], "2.0.0"),
        ([c("fix: x", body="BREAKING CHANGE: config moved")], "2.0.0"),
        ([c("chore: bump deps"), c("docs: readme"), c("test: more")], None),
        ([], None),
    ],
)
def test_next_version_follows_strongest_change(commits: list[Commit], expected: str | None) -> None:
    assert release.next_version("1.0.0", commits) == expected


def test_release_commits_never_trigger_another_release() -> None:
    assert release.next_version("1.0.0", [c("chore(release): v1.0.1")]) is None


def test_non_conventional_subjects_are_ignored() -> None:
    assert release.next_version("1.0.0", [c("Update stuff")]) is None


def test_minor_resets_patch_and_major_resets_both() -> None:
    assert release.next_version("1.4.9", [c("feat: x")]) == "1.5.0"
    assert release.next_version("1.4.9", [c("feat!: x")]) == "2.0.0"


def test_invalid_current_version_is_rejected() -> None:
    with pytest.raises(ValueError):
        release.next_version("1.0", [c("fix: x")])


def test_changelog_fallback_groups_releasable_commits() -> None:
    section = release.changelog_section(
        "1.1.0",
        "2026-10-16",
        [
            c("feat(spec): new command"),
            c("fix: typo"),
            c("chore: bump deps"),
            c("feat!: drop flag"),
        ],
    )
    assert section.startswith("## 1.1.0 - 2026-10-16\n")
    assert "### Breaking changes\n- drop flag" in section
    assert "### Features\n- new command" in section
    assert "### Fixes\n- typo" in section
    assert "bump deps" not in section
    assert "### Performance" not in section


def test_read_commits_splits_records_on_nul() -> None:
    raw = "feat: one\nbody one\x00fix: two\n\x00"
    commits = release.read_commits(raw)
    assert [commit.subject for commit in commits] == ["feat: one", "fix: two"]
    assert commits[0].body == "body one"


def test_main_prints_next_version(tmp_path: Path) -> None:
    version = tmp_path / "VERSION"
    version.write_text("1.0.0\n", encoding="utf-8")
    log = tmp_path / "log.txt"
    log.write_text("feat: new thing\x00", encoding="utf-8")
    assert release.main(["--version-file", str(version), "--log", str(log)]) == 0


def test_main_reports_no_release(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    version = tmp_path / "VERSION"
    version.write_text("1.0.0\n", encoding="utf-8")
    log = tmp_path / "log.txt"
    log.write_text("docs: only docs\x00", encoding="utf-8")
    assert release.main(["--version-file", str(version), "--log", str(log)]) == 0
    assert capsys.readouterr().out.strip() == "no release needed"
