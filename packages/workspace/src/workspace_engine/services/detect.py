"""
workspace_engine.services.detect — Deterministic technology-stack detection.

Scans a repository (bounded depth, skipping dependency/build folders) for marker
files and returns stable stack identifiers. Consumed by ``ws detect --json`` and,
through that CLI contract, by ai-governance to pick the rules a project needs.
"""

from __future__ import annotations

import fnmatch
import json
import os
from dataclasses import dataclass, field
from pathlib import Path

SCHEMA_VERSION = 1
MAX_DEPTH = 8  # deep enough for Maven/Gradle layouts (src/main/resources/db/migration)
SKIP_DIRS = frozenset(
    {
        ".git",
        "node_modules",
        ".venv",
        "venv",
        "__pycache__",
        "build",
        "dist",
        "target",
        ".gradle",
        ".idea",
        ".next",
        "vendor",
        ".dart_tool",
        "bin",
        "obj",
    }
)

# stack id -> file-name glob patterns (matched against the file name only)
FILE_MARKERS: dict[str, tuple[str, ...]] = {
    "java": ("pom.xml", "*.java"),
    "kotlin": ("*.kt", "build.gradle.kts"),
    "node": ("package.json",),
    "typescript": ("tsconfig.json", "*.ts"),
    "python": ("pyproject.toml", "requirements*.txt", "setup.py", "*.py"),
    "go": ("go.mod",),
    "rust": ("Cargo.toml",),
    "php": ("composer.json", "*.php"),
    "flutter": ("pubspec.yaml",),
    "dotnet": ("*.csproj", "*.sln"),
    "docker": ("Dockerfile", "Dockerfile.*", "docker-compose*.yml", "compose*.yaml"),
    "kubernetes": ("Chart.yaml", "kustomization.yaml"),
    "sql": ("*.sql",),
    "gitlab-ci": (".gitlab-ci.yml",),
    "jenkins": ("Jenkinsfile",),
}

# stack id -> directory names (any depth)
DIR_MARKERS: dict[str, tuple[str, ...]] = {
    "kubernetes": ("k8s", "helm"),
    "migrations": ("migrations", "migration", "flyway", "liquibase"),
}


@dataclass
class Detection:
    root: Path
    markers: dict[str, list[str]] = field(default_factory=dict)

    @property
    def stacks(self) -> list[str]:
        return sorted(self.markers)

    def add(self, stack: str, relative: str) -> None:
        found = self.markers.setdefault(stack, [])
        if len(found) < 3 and relative not in found:
            found.append(relative)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": SCHEMA_VERSION,
            "root": str(self.root),
            "stacks": self.stacks,
            "markers": {key: self.markers[key] for key in self.stacks},
        }


def _react_dependency(package_json: Path) -> bool:
    try:
        data = json.loads(package_json.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if not isinstance(data, dict):
        return False
    deps: dict[str, object] = {}
    for key in ("dependencies", "devDependencies", "peerDependencies"):
        section = data.get(key)
        if isinstance(section, dict):
            deps.update(section)
    return "react" in deps


def detect_stacks(root: str | Path) -> Detection:
    """Detects stacks under ``root`` (depth-limited, deterministic order)."""
    base = Path(root).resolve()
    result = Detection(root=base)
    if (base / ".github" / "workflows").is_dir():
        result.add("github-actions", ".github/workflows")
    for current, dirs, file_names in os.walk(base):
        current_path = Path(current)
        depth = len(current_path.relative_to(base).parts)
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not d.startswith("."))
        if depth >= MAX_DEPTH:
            dirs[:] = []
        for directory in dirs:
            for stack, names in DIR_MARKERS.items():
                if directory in names:
                    result.add(stack, str((current_path / directory).relative_to(base)))
        for name in sorted(file_names):
            relative = str((current_path / name).relative_to(base))
            for stack, patterns in FILE_MARKERS.items():
                if any(fnmatch.fnmatch(name, pattern) for pattern in patterns):
                    result.add(stack, relative)
            if name == "package.json" and _react_dependency(current_path / name):
                result.add("react", relative)
    return result
