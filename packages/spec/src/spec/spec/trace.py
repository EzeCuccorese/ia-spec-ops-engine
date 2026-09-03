from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

SCENARIO_PATTERN = re.compile(
    r"@(?P<tag>s[0-9]+)\s*\n\s*(?:Scenario|Escenario):\s*(?P<title>[^\n]+)",
    re.MULTILINE | re.IGNORECASE,
)


@dataclass(frozen=True)
class Scenario:
    tag: str
    title: str


@dataclass
class TraceabilityReport:
    feature: str
    scenarios: list[Scenario] = field(default_factory=list)
    covered: dict[str, list[str]] = field(default_factory=dict)
    uncovered: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.scenarios)

    @property
    def covered_count(self) -> int:
        return len(self.covered)

    @property
    def is_complete(self) -> bool:
        return len(self.uncovered) == 0

    @property
    def coverage_percent(self) -> float:
        if not self.scenarios:
            return 100.0
        return (self.covered_count / self.total) * 100.0


def extract_scenarios(content: str) -> list[Scenario]:
    scenarios: list[Scenario] = []
    seen: set[str] = set()
    for match in SCENARIO_PATTERN.finditer(content):
        tag = match.group("tag").lower()
        title = match.group("title").strip()
        if tag not in seen:
            seen.add(tag)
            scenarios.append(Scenario(tag=f"@{tag}", title=title))
    return scenarios


def find_test_mappings(
    scenarios: list[Scenario],
    root: Path,
    feature_dir: Path | None = None,
) -> TraceabilityReport:
    report = TraceabilityReport(feature=feature_dir.name if feature_dir else "active")
    report.scenarios = list(scenarios)

    if not scenarios:
        return report

    # Collect search locations: tests directory and feature work/tasks files
    search_files: list[Path] = []
    tests_dir = root / "tests"
    if tests_dir.is_dir():
        search_files.extend(tests_dir.rglob("*.py"))
        search_files.extend(tests_dir.rglob("*.ts"))
        search_files.extend(tests_dir.rglob("*.js"))

    if feature_dir and feature_dir.is_dir():
        work_md = feature_dir / "work.md"
        tasks_md = feature_dir / "tasks.md"
        if work_md.is_file():
            search_files.append(work_md)
        if tasks_md.is_file():
            search_files.append(tasks_md)

    # Read contents of all potential test and mapping files
    file_contents: list[tuple[Path, str]] = []
    for f in search_files:
        try:
            file_contents.append((f, f.read_text(encoding="utf-8", errors="replace")))
        except OSError:
            continue

    for scenario in scenarios:
        tag = scenario.tag  # e.g. "@s1"
        tag_bare = tag.lstrip("@")  # e.g. "s1"
        # Match pattern: @s1, test_s1, test_<name>_s1, or mention of @s1 in work.md/tasks.md
        pattern = re.compile(
            rf"(?:@?{re.escape(tag_bare)}\b|test_[a-zA-Z0-9_]*{re.escape(tag_bare)}\b)",
            re.IGNORECASE,
        )

        matching_files: list[str] = []
        for path, text in file_contents:
            if pattern.search(text):
                matching_files.append(str(path.relative_to(root) if path.is_relative_to(root) else path))

        if matching_files:
            report.covered[tag] = matching_files
        else:
            report.uncovered.append(tag)

    return report
