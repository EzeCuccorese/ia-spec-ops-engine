"""workspace_engine.services.monorepo — Detection and test planning for JS/TS monorepos."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from ruamel.yaml import YAML

logger = logging.getLogger(__name__)

MONOREPO_TEST_SCRIPT_RE = re.compile(
    r"(?:yarn\s+workspaces?\s+(?:run|foreach)|\bpnpm\s+(?:-r|--recursive)|\bnpm\s+(?:run\s+\S+\s+(?:--(?:workspaces?|ws)|-ws)|(?:--(?:workspaces?|ws)|-ws)\s+run))\b"
)

TESTABLE_JS_EXTENSIONS = {
    ".js",
    ".jsx",
    ".mjs",
    ".cjs",
    ".ts",
    ".tsx",
    ".vue",
    ".svelte",
}


@dataclass
class PackageTestRun:
    package: str
    package_dir: str
    runner: str  # "jest" | "vitest"
    command: list[str]
    files: list[str]


@dataclass
class MonorepoTestPlan:
    is_monorepo: bool
    runs: list[PackageTestRun] = field(default_factory=list)
    unresolved_files: list[str] = field(default_factory=list)
    unknown_runner_packages: list[str] = field(default_factory=list)
    skipped_outside_package: list[str] = field(default_factory=list)


def is_monorepo_test_script(script: str) -> bool:
    """True when the script runs tests across workspaces (yarn, pnpm, npm)."""
    return bool(MONOREPO_TEST_SCRIPT_RE.search(script))


def _extract_string_items(items: Any) -> list[str]:
    if not isinstance(items, list):
        return []
    return [item.strip() for item in items if isinstance(item, str) and item.strip()]


def _globs_from_package_json(pkg_json_path: Path) -> list[str]:
    if not pkg_json_path.is_file():
        return []
    try:
        data = json.loads(pkg_json_path.read_text(encoding="utf-8"))
        ws = data.get("workspaces")
        if isinstance(ws, list):
            return _extract_string_items(ws)
        if isinstance(ws, dict):
            return _extract_string_items(ws.get("packages"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.debug("Failed reading package.json workspaces from %s: %s", pkg_json_path, exc)
    return []


def _globs_from_pnpm_workspace(pnpm_ws_path: Path) -> list[str]:
    if not pnpm_ws_path.is_file():
        return []
    try:
        yaml = YAML(typ="safe")
        content = yaml.load(pnpm_ws_path.read_text(encoding="utf-8"))
        if isinstance(content, dict):
            return _extract_string_items(content.get("packages"))
    except Exception as exc:
        logger.debug("Failed reading pnpm-workspace.yaml from %s: %s", pnpm_ws_path, exc)
    return []


def get_workspace_globs(root: Path) -> list[str]:
    """Reads workspace globs from package.json or pnpm-workspace.yaml."""
    globs = _globs_from_package_json(root / "package.json")
    globs.extend(_globs_from_pnpm_workspace(root / "pnpm-workspace.yaml"))
    return globs


def _clean_glob(pat: str) -> str:
    pat = pat.strip()
    if pat.startswith("./"):
        pat = pat[2:]
    return pat.rstrip("/")


def matches_glob(rel_path: str, glob_pattern: str) -> bool:
    """Matches a relative POSIX path against a glob pattern."""
    clean_pat = _clean_glob(glob_pattern)
    return PurePosixPath(rel_path).match(clean_pat)


def _scan_glob_candidates(root: Path, pos_globs: list[str]) -> set[str]:
    candidates: set[str] = set()
    for pat in pos_globs:
        try:
            matched_dirs = [
                d for d in root.glob(pat) if d.is_dir() and (d / "package.json").is_file()
            ]
            for d in matched_dirs:
                candidates.add(d.relative_to(root).as_posix())
        except (OSError, ValueError) as exc:
            logger.debug("Error globbing %s under %s: %s", pat, root, exc)
    return candidates


def find_workspace_packages(root: Path, globs: list[str]) -> set[str]:
    """Finds all relative package directory paths matching positive globs and not matching negative globs."""
    pos_globs = [_clean_glob(g) for g in globs if not g.startswith("!")]
    neg_globs = [_clean_glob(g[1:]) for g in globs if g.startswith("!")]
    candidates = _scan_glob_candidates(root, pos_globs)
    return {
        cand for cand in candidates if not any(PurePosixPath(cand).match(neg) for neg in neg_globs)
    }


def resolve_owning_package(rel_file: str, package_dirs: set[str]) -> str | None:
    """Resolves the nearest owning package directory for a relative file path."""
    p = PurePosixPath(rel_file)
    for parent in p.parents:
        parent_str = parent.as_posix()
        if parent_str in package_dirs:
            return parent_str
    return None


def _runner_from_scripts(scripts: Any) -> str | None:
    if not isinstance(scripts, dict):
        return None
    test_script = str(scripts.get("test", ""))
    if "vitest" in test_script:
        return "vitest"
    if "jest" in test_script:
        return "jest"
    return None


def _runner_from_deps(data: dict[str, Any]) -> str | None:
    all_deps: dict[str, Any] = {}
    for key in ("devDependencies", "dependencies"):
        val = data.get(key)
        if isinstance(val, dict):
            all_deps.update(val)
    if "vitest" in all_deps:
        return "vitest"
    if "jest" in all_deps:
        return "jest"
    return None


def detect_package_runner(pkg_dir: Path) -> str | None:
    """Detects jest or vitest from package.json scripts or (dev)dependencies."""
    pkg_json = pkg_dir / "package.json"
    if not pkg_json.is_file():
        return None
    try:
        data: dict[str, Any] = json.loads(pkg_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.debug("Failed reading %s: %s", pkg_json, exc)
        return None

    return _runner_from_scripts(data.get("scripts")) or _runner_from_deps(data)


def detect_repo_package_manager(root: Path) -> str:
    """Detects the package manager used by the monorepo root."""
    if (root / "pnpm-lock.yaml").is_file():
        return "pnpm"
    if (root / "yarn.lock").is_file():
        return "yarn"
    if (root / "bun.lock").is_file() or (root / "bun.lockb").is_file():
        return "bun"
    return "npm"


def build_runner_command(pm: str, runner: str, files: list[str]) -> list[str]:
    """Constructs the command to execute the scoped test runner inside the package directory."""
    if runner == "jest":
        runner_args = [
            "jest",
            "--ci",
            "--watchAll=false",
            "--passWithNoTests",
            "--findRelatedTests",
            *files,
        ]
    else:  # vitest
        runner_args = ["vitest", "related", "--run", "--passWithNoTests", *files]

    exec_prefixes = {
        "pnpm": ["pnpm", "exec"],
        "yarn": ["yarn", "run"],
        "bun": ["bun", "x"],
        "npm": ["npx"],
    }
    prefix = exec_prefixes.get(pm, ["npx"])
    return [*prefix, *runner_args]


def _read_root_test_script(root: Path) -> str:
    root_pkg_json = root / "package.json"
    if not root_pkg_json.is_file():
        return ""
    try:
        data = json.loads(root_pkg_json.read_text(encoding="utf-8"))
        scripts = data.get("scripts", {})
        if isinstance(scripts, dict):
            return str(scripts.get("test", ""))
    except (OSError, json.JSONDecodeError) as exc:
        logger.debug("Failed reading root package.json: %s", exc)
    return ""


def _rel_path_to_pkg(p: PurePosixPath, owner: str, rel_file: str) -> str:
    try:
        return p.relative_to(PurePosixPath(owner)).as_posix()
    except ValueError:
        return rel_file


def _partition_changed_files(
    changed_files: list[str], package_dirs: set[str]
) -> tuple[dict[str, list[str]], list[str], list[str]]:
    pkg_files: dict[str, list[str]] = {}
    unresolved: list[str] = []
    skipped_outside: list[str] = []

    for rel_file in changed_files:
        p = PurePosixPath(rel_file)
        if len(p.parts) <= 1:
            skipped_outside.append(rel_file)
            continue
        owner = resolve_owning_package(rel_file, package_dirs)
        if owner is None:
            unresolved.append(rel_file)
            continue
        if p.suffix in TESTABLE_JS_EXTENSIONS:
            pkg_files.setdefault(owner, []).append(_rel_path_to_pkg(p, owner, rel_file))

    return pkg_files, unresolved, skipped_outside


def _build_package_runs(
    root: Path, pm: str, pkg_files: dict[str, list[str]]
) -> tuple[list[PackageTestRun], list[str]]:
    runs: list[PackageTestRun] = []
    unknown_runner_pkgs: list[str] = []

    for owner in sorted(pkg_files.keys()):
        owner_dir = root / owner
        runner = detect_package_runner(owner_dir)
        files = pkg_files[owner]
        if runner is None:
            unknown_runner_pkgs.append(owner)
            continue
        cmd = build_runner_command(pm, runner, files)
        runs.append(
            PackageTestRun(
                package=owner,
                package_dir=str(owner_dir.resolve()),
                runner=runner,
                command=cmd,
                files=files,
            )
        )
    return runs, unknown_runner_pkgs


def plan_monorepo_test_runs(root: Path, changed_files: list[str]) -> MonorepoTestPlan:
    """Plans scoped test runs for changed files in a monorepo."""
    root_test_script = _read_root_test_script(root)
    globs = get_workspace_globs(root)
    if not (is_monorepo_test_script(root_test_script) or bool(globs)):
        return MonorepoTestPlan(is_monorepo=False)

    package_dirs = find_workspace_packages(root, globs)
    pm = detect_repo_package_manager(root)
    pkg_files, unresolved, skipped_outside = _partition_changed_files(changed_files, package_dirs)
    runs, unknown_runners = _build_package_runs(root, pm, pkg_files)

    return MonorepoTestPlan(
        is_monorepo=True,
        runs=runs,
        unresolved_files=unresolved,
        unknown_runner_packages=unknown_runners,
        skipped_outside_package=skipped_outside,
    )
