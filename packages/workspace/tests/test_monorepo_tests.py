"""Tests for monorepo test scoping in the quality-gate pre-push hook and monorepo service."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from workspace_engine.services.monorepo import (
    PackageTestRun,
    build_runner_command,
    detect_package_runner,
    detect_repo_package_manager,
    find_workspace_packages,
    get_workspace_globs,
    is_monorepo_test_script,
    matches_glob,
    plan_monorepo_test_runs,
    resolve_owning_package,
)


@pytest.mark.parametrize(
    ("script", "expected"),
    [
        ("yarn workspaces run test", True),
        ("yarn workspace run test", True),
        ("yarn workspaces foreach -A run test", True),
        ("yarn workspaces foreach --all run test", True),
        ("pnpm -r test", True),
        ("pnpm -r run test", True),
        ("pnpm --recursive test", True),
        ("pnpm --recursive run test", True),
        ("npm run test --workspaces", True),
        ("npm run test --workspace", True),
        ("npm run test -ws", True),
        ("npm --workspaces run test", True),
        ("npm -ws run test", True),
        ("jest", False),
        ("vitest run", False),
        ("npm test", False),
    ],
)
def test_is_monorepo_test_script(script: str, expected: bool) -> None:
    assert is_monorepo_test_script(script) is expected


def test_get_workspace_globs_yarn_classic_array(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text(
        json.dumps({"workspaces": ["packages/*", "apps/*"]}), encoding="utf-8"
    )
    assert get_workspace_globs(tmp_path) == ["packages/*", "apps/*"]


def test_get_workspace_globs_packages_object_form(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text(
        json.dumps({"workspaces": {"packages": ["modules/*", "libs/*"]}}), encoding="utf-8"
    )
    assert get_workspace_globs(tmp_path) == ["modules/*", "libs/*"]


def test_get_workspace_globs_pnpm_workspace_yaml(tmp_path: Path) -> None:
    (tmp_path / "pnpm-workspace.yaml").write_text(
        "packages:\n  - 'packages/*'\n  - 'services/*'\n  - '!packages/ignored'\n",
        encoding="utf-8",
    )
    assert get_workspace_globs(tmp_path) == ["packages/*", "services/*", "!packages/ignored"]


def test_find_workspace_packages_filters_negatives(tmp_path: Path) -> None:
    (tmp_path / "packages" / "pkg-a").mkdir(parents=True)
    (tmp_path / "packages" / "pkg-a" / "package.json").write_text("{}", encoding="utf-8")
    (tmp_path / "packages" / "pkg-ignored").mkdir(parents=True)
    (tmp_path / "packages" / "pkg-ignored" / "package.json").write_text("{}", encoding="utf-8")

    globs = ["packages/*", "!packages/pkg-ignored"]
    found = find_workspace_packages(tmp_path, globs)
    assert found == {"packages/pkg-a"}


def test_resolve_owning_package_nested() -> None:
    pkg_dirs = {"packages/pkg-a", "packages/pkg-a/nested/pkg-b"}
    assert resolve_owning_package("packages/pkg-a/src/index.ts", pkg_dirs) == "packages/pkg-a"
    assert (
        resolve_owning_package("packages/pkg-a/nested/pkg-b/src/lib.ts", pkg_dirs)
        == "packages/pkg-a/nested/pkg-b"
    )
    assert resolve_owning_package("outside/file.ts", pkg_dirs) is None


@pytest.mark.parametrize(
    ("pkg_json_content", "expected"),
    [
        ({"scripts": {"test": "vitest run"}}, "vitest"),
        ({"devDependencies": {"vitest": "^1.0.0"}}, "vitest"),
        ({"scripts": {"test": "jest --coverage"}}, "jest"),
        ({"dependencies": {"jest": "^29.0.0"}}, "jest"),
        ({"scripts": {"test": "custom-runner"}}, None),
    ],
)
def test_detect_package_runner(
    tmp_path: Path, pkg_json_content: dict[str, Any], expected: str | None
) -> None:
    pkg_dir = tmp_path / "pkg"
    pkg_dir.mkdir(parents=True, exist_ok=True)
    (pkg_dir / "package.json").write_text(json.dumps(pkg_json_content), encoding="utf-8")
    assert detect_package_runner(pkg_dir) == expected


def test_detect_repo_package_manager(tmp_path: Path) -> None:
    assert detect_repo_package_manager(tmp_path) == "npm"
    (tmp_path / "yarn.lock").write_text("", encoding="utf-8")
    assert detect_repo_package_manager(tmp_path) == "yarn"
    (tmp_path / "pnpm-lock.yaml").write_text("", encoding="utf-8")
    assert detect_repo_package_manager(tmp_path) == "pnpm"


def test_build_runner_command() -> None:
    # vitest with pnpm
    cmd = build_runner_command("pnpm", "vitest", ["src/a.ts"])
    assert cmd == ["pnpm", "exec", "vitest", "related", "--run", "--passWithNoTests", "src/a.ts"]

    # jest with yarn
    cmd = build_runner_command("yarn", "jest", ["src/a.ts"])
    assert cmd == [
        "yarn",
        "run",
        "jest",
        "--ci",
        "--watchAll=false",
        "--passWithNoTests",
        "--findRelatedTests",
        "src/a.ts",
    ]


def _setup_mixed_monorepo(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text(
        json.dumps({"scripts": {"test": "yarn workspaces run test"}, "workspaces": ["packages/*"]}),
        encoding="utf-8",
    )
    (tmp_path / "yarn.lock").write_text("", encoding="utf-8")
    for name, script_or_dep in [
        ("pkg-a", {"scripts": {"test": "vitest run"}}),
        ("pkg-b", {"devDependencies": {"jest": "^29.0.0"}}),
        ("pkg-c", {"scripts": {"test": "echo no-tests"}}),
    ]:
        p = tmp_path / "packages" / name
        p.mkdir(parents=True)
        (p / "package.json").write_text(json.dumps(script_or_dep), encoding="utf-8")


def _verify_scoped_runs(runs: list[PackageTestRun]) -> None:
    assert len(runs) == 2
    run_a = next(r for r in runs if r.package == "packages/pkg-a")
    assert run_a.runner == "vitest"
    assert run_a.files == ["src/index.ts"]
    assert run_a.command == [
        "yarn",
        "run",
        "vitest",
        "related",
        "--run",
        "--passWithNoTests",
        "src/index.ts",
    ]

    run_b = next(r for r in runs if r.package == "packages/pkg-b")
    assert run_b.runner == "jest"
    assert run_b.files == ["src/lib.ts"]
    assert "--findRelatedTests" in run_b.command

    for run in runs:
        assert run.command != ["yarn", "test"]
        assert "workspaces" not in " ".join(run.command)


def test_plan_monorepo_test_runs_mixed_packages_and_unresolvable(tmp_path: Path) -> None:
    _setup_mixed_monorepo(tmp_path)
    changed = [
        "packages/pkg-a/src/index.ts",
        "packages/pkg-b/src/lib.ts",
        "packages/pkg-c/src/other.ts",
        "packages/unknown-pkg/file.ts",
        "root-config.json",
    ]
    plan = plan_monorepo_test_runs(tmp_path, changed)
    assert plan.is_monorepo is True
    assert plan.skipped_outside_package == ["root-config.json"]
    assert plan.unresolved_files == ["packages/unknown-pkg/file.ts"]
    assert plan.unknown_runner_packages == ["packages/pkg-c"]
    _verify_scoped_runs(plan.runs)


def test_plan_monorepo_test_runs_no_full_suite_fallback_on_unresolvable(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text(
        json.dumps({"scripts": {"test": "pnpm -r test"}, "workspaces": ["packages/*"]}),
        encoding="utf-8",
    )
    (tmp_path / "pnpm-lock.yaml").write_text("", encoding="utf-8")

    changed = ["unknown/file.ts", "package.json"]
    plan = plan_monorepo_test_runs(tmp_path, changed)

    assert plan.is_monorepo is True
    assert len(plan.runs) == 0
    assert plan.unresolved_files == ["unknown/file.ts"]
    assert plan.skipped_outside_package == ["package.json"]


def test_get_workspace_globs_invalid_files(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text("{bad", encoding="utf-8")
    assert get_workspace_globs(tmp_path) == []

    (tmp_path / "package.json").write_text(
        json.dumps({"workspaces": [123, None]}), encoding="utf-8"
    )
    assert get_workspace_globs(tmp_path) == []

    (tmp_path / "package.json").write_text(
        json.dumps({"workspaces": {"packages": [456]}}), encoding="utf-8"
    )
    assert get_workspace_globs(tmp_path) == []

    (tmp_path / "pnpm-workspace.yaml").write_text(":\tbad", encoding="utf-8")
    assert get_workspace_globs(tmp_path) == []


def test_detect_package_runner_invalid_json(tmp_path: Path) -> None:
    pkg_dir = tmp_path / "pkg"
    pkg_dir.mkdir()
    assert detect_package_runner(tmp_path / "nonexistent") is None
    (pkg_dir / "package.json").write_text("{bad", encoding="utf-8")
    assert detect_package_runner(pkg_dir) is None


def test_detect_repo_package_manager_bun(tmp_path: Path) -> None:
    (tmp_path / "bun.lockb").write_text("", encoding="utf-8")
    assert detect_repo_package_manager(tmp_path) == "bun"
    cmd = build_runner_command("bun", "vitest", ["src/a.ts"])
    assert cmd == ["bun", "x", "vitest", "related", "--run", "--passWithNoTests", "src/a.ts"]


def test_plan_monorepo_test_runs_not_monorepo(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text(
        json.dumps({"scripts": {"test": "jest"}}), encoding="utf-8"
    )
    plan = plan_monorepo_test_runs(tmp_path, ["src/a.ts"])
    assert plan.is_monorepo is False


def test_plan_monorepo_test_runs_invalid_root_package_json(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text("{bad", encoding="utf-8")
    plan = plan_monorepo_test_runs(tmp_path, ["src/a.ts"])
    assert plan.is_monorepo is False


def test_matches_glob_direct() -> None:
    assert matches_glob("packages/foo", "packages/*")
    assert not matches_glob("packages/foo/bar", "packages/*")
