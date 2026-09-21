"""Guards the source layout that coverage measurement depends on."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOTS = (
    REPO_ROOT / "packages" / "ai-governance" / "src" / "ai_governance",
    REPO_ROOT / "packages" / "spec" / "src" / "spec",
    REPO_ROOT / "packages" / "workspace" / "src" / "workspace_engine",
)


def test_every_directory_with_python_modules_is_a_package() -> None:
    """A .py file in a directory without __init__.py is invisible to coverage until imported.

    That is how six ws subcommands went unmeasured for months; keep every module
    directory a regular package so unexecuted files show up as 0%, not as nothing.
    """
    offenders: list[str] = []
    for root in PACKAGE_ROOTS:
        for module in root.rglob("*.py"):
            directory = module.parent
            if "__pycache__" in directory.parts:
                continue
            if not (directory / "__init__.py").exists():
                offenders.append(str(directory.relative_to(REPO_ROOT)))
    assert not sorted(set(offenders)), f"directories with .py files but no __init__.py: {offenders}"
