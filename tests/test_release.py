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
    assert release.main(["next", "--version-file", str(version), "--log", str(log)]) == 0


def test_main_reports_no_release(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    version = tmp_path / "VERSION"
    version.write_text("1.0.0\n", encoding="utf-8")
    log = tmp_path / "log.txt"
    log.write_text("docs: only docs\x00", encoding="utf-8")
    assert release.main(["next", "--version-file", str(version), "--log", str(log)]) == 0
    assert capsys.readouterr().out.strip() == "no release needed"


def _seed_repo(root: Path) -> None:
    """Create the minimal files the version writer touches."""
    (root / "packages/ai-governance/src/ai_governance").mkdir(parents=True)
    (root / "packages/workspace/src/workspace_engine").mkdir(parents=True)
    for package in ("ai-governance", "spec", "workspace"):
        (root / "packages" / package).mkdir(parents=True, exist_ok=True)
        (root / "packages" / package / "pyproject.toml").write_text(
            '[project]\nname = "x"\nversion = "0.1.0"\n', encoding="utf-8"
        )
    (root / "pyproject.toml").write_text(
        '[project]\nname = "root"\nversion = "0.0.0"\n', encoding="utf-8"
    )
    (root / "packages/ai-governance/src/ai_governance/__init__.py").write_text(
        '__version__ = "0.1.0"\n', encoding="utf-8"
    )
    (root / "packages/workspace/src/workspace_engine/__init__.py").write_text(
        '__version__ = "0.2.0"\n', encoding="utf-8"
    )


def test_write_version_files_updates_every_target(tmp_path: Path) -> None:
    _seed_repo(tmp_path)
    changed = release.write_version_files(tmp_path, "1.0.0")
    assert len(changed) == 6
    assert 'version = "1.0.0"' in (tmp_path / "pyproject.toml").read_text(encoding="utf-8")
    init = tmp_path / "packages/workspace/src/workspace_engine/__init__.py"
    assert '__version__ = "1.0.0"' in init.read_text(encoding="utf-8")


def test_write_version_files_is_idempotent(tmp_path: Path) -> None:
    _seed_repo(tmp_path)
    release.write_version_files(tmp_path, "1.0.0")
    assert release.write_version_files(tmp_path, "1.0.0") == []


def test_write_version_files_rejects_missing_version_line(tmp_path: Path) -> None:
    _seed_repo(tmp_path)
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "root"\n', encoding="utf-8")
    with pytest.raises(ValueError, match="no version line"):
        release.write_version_files(tmp_path, "1.0.0")


def test_write_version_files_rejects_bad_version(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        release.write_version_files(tmp_path, "1.0")


def test_prepend_changelog_keeps_newest_first(tmp_path: Path) -> None:
    changelog = tmp_path / "CHANGELOG.md"
    release.prepend_changelog(changelog, "## 1.0.0 - 2026-10-16\n\n- first\n")
    release.prepend_changelog(changelog, "## 1.0.1 - 2026-10-20\n\n- fix\n")
    text = changelog.read_text(encoding="utf-8")
    assert text.startswith("# Changelog\n\n## 1.0.1")
    assert text.index("## 1.0.1") < text.index("## 1.0.0")


def test_extract_section_returns_one_release_body(tmp_path: Path) -> None:
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(
        "# Changelog\n\n## 1.0.1 - 2026-10-20\n\n- fix\n\n## 1.0.0 - 2026-10-16\n\n- first\n",
        encoding="utf-8",
    )
    assert release.extract_section(changelog, "1.0.1") == "- fix\n"


def test_apply_with_notes_writes_everything(tmp_path: Path) -> None:
    _seed_repo(tmp_path)
    (tmp_path / "VERSION").write_text("0.0.0\n", encoding="utf-8")
    notes = tmp_path / "notes.md"
    notes.write_text("### Features\n- New thing\n", encoding="utf-8")
    code = release.main(
        ["apply", "1.0.0", "--root", str(tmp_path), "--date", "2026-10-16", "--notes", str(notes)]
    )
    assert code == 0
    assert (tmp_path / "VERSION").read_text(encoding="utf-8") == "1.0.0\n"
    changelog = (tmp_path / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "## 1.0.0 - 2026-10-16" in changelog
    assert "- New thing" in changelog


def test_apply_without_notes_falls_back_to_commits(tmp_path: Path) -> None:
    _seed_repo(tmp_path)
    log = tmp_path / "log.txt"
    log.write_text("fix: typo\x00", encoding="utf-8")
    release.main(
        ["apply", "1.0.1", "--root", str(tmp_path), "--date", "2026-10-20", "--log", str(log)]
    )
    assert "### Fixes\n- typo" in (tmp_path / "CHANGELOG.md").read_text(encoding="utf-8")


def test_apply_needs_notes_or_log(tmp_path: Path) -> None:
    _seed_repo(tmp_path)
    with pytest.raises(ValueError, match="needs --notes or --log"):
        release.main(["apply", "1.0.0", "--root", str(tmp_path), "--date", "2026-10-16"])


def test_notes_subcommand_prints_one_section(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(
        "# Changelog\n\n## 1.0.1 - 2026-10-20\n\n- fix\n\n## 1.0.0 - 2026-10-16\n\n- first\n",
        encoding="utf-8",
    )
    assert release.main(["notes", "1.0.0", "--changelog", str(changelog)]) == 0
    assert capsys.readouterr().out == "- first\n"
