"""Privacy checks at the Git and distribution boundaries."""

from __future__ import annotations

import io
import os
import subprocess
import sys
import tarfile
from pathlib import Path
from zipfile import ZipFile

CHECK = Path(__file__).resolve().parents[1] / "scripts" / "check_private_packs.py"
PRIVATE_PATH = "packages/corporate-rules/example/rules/private.md"


def _repo(root: Path) -> None:
    git_env = os.environ.copy()
    git_env["GIT_CONFIG_GLOBAL"] = os.devnull
    git_env["GIT_CONFIG_SYSTEM"] = os.devnull
    subprocess.run(["git", "init", "-q"], cwd=root, env=git_env, check=True)
    _git(root, "config", "user.name", "Test User")
    _git(root, "config", "user.email", "test@example.org")
    _git(root, "config", "core.hooksPath", os.devnull)


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


def _check(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CHECK), *args], cwd=root, capture_output=True, text=True
    )


def test_private_pack_is_rejected_in_the_index_and_in_already_removed_history(
    tmp_path: Path,
) -> None:
    _repo(tmp_path)
    private_file = tmp_path / PRIVATE_PATH
    private_file.parent.mkdir(parents=True)
    private_file.write_text("Synthetic private test policy.", encoding="utf-8")
    _git(tmp_path, "add", "-f", PRIVATE_PATH)
    staged = _check(tmp_path)
    assert staged.returncode == 1
    assert PRIVATE_PATH in staged.stderr
    _git(tmp_path, "commit", "-qm", "Add sample pack")
    _git(tmp_path, "rm", "-q", PRIVATE_PATH)
    _git(tmp_path, "commit", "-qm", "Remove sample pack")
    history = _check(tmp_path, "HEAD")
    assert history.returncode == 1
    assert PRIVATE_PATH in history.stderr
    assert "Synthetic private test policy" not in history.stderr


def test_private_pack_is_rejected_in_wheel_and_sdist_without_printing_contents(
    tmp_path: Path,
) -> None:
    _repo(tmp_path)
    artifacts = tmp_path / "dist"
    artifacts.mkdir()
    with ZipFile(artifacts / "pkg.whl", "w") as wheel:
        wheel.writestr(PRIVATE_PATH, "Synthetic private wheel policy.")
    with tarfile.open(artifacts / "pkg.tar.gz", "w:gz") as source:
        payload = b"Synthetic private source policy."
        entry = tarfile.TarInfo(f"pkg-1/{PRIVATE_PATH}")
        entry.size = len(payload)
        source.addfile(entry, io.BytesIO(payload))
    result = _check(tmp_path, "--dist", str(artifacts))
    assert result.returncode == 1
    assert f"pkg.whl: {PRIVATE_PATH}" in result.stderr
    assert f"pkg.tar.gz: pkg-1/{PRIVATE_PATH}" in result.stderr
    assert "Synthetic private" not in result.stderr


def test_local_in_repo_config_dirs_are_rejected_in_git_and_archives(tmp_path: Path) -> None:
    _repo(tmp_path)
    gov_file = tmp_path / "config" / "ai-governance" / "personal" / "rules" / "local.md"
    ws_file = tmp_path / "config" / "workspace" / "config.toml"
    gov_file.parent.mkdir(parents=True)
    ws_file.parent.mkdir(parents=True)
    gov_file.write_text("# Private local rule\n", encoding="utf-8")
    ws_file.write_text("[design]\nmode = 'block'\n", encoding="utf-8")
    _git(tmp_path, "add", "-f", "config/ai-governance/personal/rules/local.md")
    _git(tmp_path, "add", "-f", "config/workspace/config.toml")

    staged = _check(tmp_path)
    assert staged.returncode == 1
    assert "config/ai-governance/personal/rules/local.md" in staged.stderr
    assert "config/workspace/config.toml" in staged.stderr

    artifacts = tmp_path / "dist"
    artifacts.mkdir()
    with ZipFile(artifacts / "pkg.whl", "w") as wheel:
        wheel.writestr("config/workspace/config.toml", "[design]\n")
    result = _check(tmp_path, "--dist", str(artifacts))
    assert result.returncode == 1
    assert "pkg.whl: config/workspace/config.toml" in result.stderr
