from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

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
    check_results: tuple[Any, ...] | list[Any] | None = None,
) -> TraceabilityReport:
    report = TraceabilityReport(feature=feature_dir.name if feature_dir else "active")
    report.scenarios = list(scenarios)

    if not scenarios:
        return report

    # 1. Collect test files across root test dirs and monorepo packages
    test_files: list[Path] = []

    # Common test directories at root
    for dname in ("tests", "tests_acceptance", "test"):
        d = root / dname
        if d.is_dir():
            test_files.extend(d.rglob("*.py"))
            test_files.extend(d.rglob("*.ts"))
            test_files.extend(d.rglob("*.js"))

    # Monorepo packages: packages/*/tests*
    packages_dir = root / "packages"
    if packages_dir.is_dir():
        for pkg in packages_dir.iterdir():
            if pkg.is_dir() and not pkg.name.startswith("."):
                for dname in ("tests", "tests_acceptance", "tests_integration", "test"):
                    d = pkg / dname
                    if d.is_dir():
                        test_files.extend(d.rglob("*.py"))
                        test_files.extend(d.rglob("*.ts"))
                        test_files.extend(d.rglob("*.js"))

    # Exclude files in volatile or non-source directories
    excluded_parts = {
        ".git",
        ".venv",
        ".spec",
        ".specops",
        "node_modules",
        ".pytest_cache",
        ".ruff_cache",
    }
    test_files = [f for f in test_files if not any(part in excluded_parts for part in f.parts)]
    test_files = sorted(set(test_files))

    # Read contents of all test files
    test_contents: list[tuple[Path, str]] = []
    for f in test_files:
        try:
            test_contents.append((f, f.read_text(encoding="utf-8", errors="replace")))
        except OSError:
            continue

    # Inspect work.md / tasks.md to resolve scenario-to-test references if documented
    work_mappings: dict[str, list[str]] = {}
    if feature_dir and feature_dir.is_dir():
        work_md = feature_dir / "work.md"
        if work_md.is_file():
            try:
                work_text = work_md.read_text(encoding="utf-8", errors="replace")
                # Parse lines like: - @s1 -> test_foo or @s1: test_bar
                for line in work_text.splitlines():
                    for s in scenarios:
                        tag_bare = s.tag.lstrip("@")
                        if f"@{tag_bare}" in line or f" {tag_bare} " in line:
                            words = re.findall(r"\btest_[a-zA-Z0-9_]+\b", line)
                            if words:
                                work_mappings.setdefault(s.tag, []).extend(words)
            except OSError:
                pass

    for scenario in scenarios:
        tag = scenario.tag  # e.g. "@s1"
        tag_bare = tag.lstrip("@")  # e.g. "s1"
        # Match pattern in test files: @s1, test_s1, test_<name>_s1, or explicit referenced test function
        pattern = re.compile(
            rf"(?:@?{re.escape(tag_bare)}\b|test_[a-zA-Z0-9_]*{re.escape(tag_bare)}\b)",
            re.IGNORECASE,
        )
        referenced_names = work_mappings.get(tag, [])

        matching_files: list[str] = []
        for path, text in test_contents:
            matched = bool(pattern.search(text))
            if not matched and referenced_names:
                matched = any(ref in text for ref in referenced_names)
            if matched:
                rel = str(path.relative_to(root) if path.is_relative_to(root) else path)
                matching_files.append(rel)

        # STRICT CONTRACT: A scenario MUST be implemented by an actual test file.
        # References in tasks.md or work.md alone NEVER credit a scenario.
        if matching_files:
            report.covered[tag] = matching_files
        else:
            report.uncovered.append(tag)

    if check_results is not None:
        execution_text = "\n".join(
            f"{c.evidence.get('stdout', '') if isinstance(getattr(c, 'evidence', None), dict) else ''}\n"
            f"{c.evidence.get('stderr', '') if isinstance(getattr(c, 'evidence', None), dict) else ''}"
            for c in check_results
        )
        if not execution_text.strip():
            # If verification checks produced no output or execution evidence,
            # no tests are proven executed: all scenarios are uncovered.
            for tag in list(report.covered.keys()):
                del report.covered[tag]
                if tag not in report.uncovered:
                    report.uncovered.append(tag)
        else:
            is_zero_collected = bool(
                re.search(
                    r"\bcollected\s+0\s+items\b|\b0\s+passed\b", execution_text, re.IGNORECASE
                )
            )
            for scenario in scenarios:
                tag = scenario.tag
                if tag in report.covered:
                    tag_bare = tag.lstrip("@")
                    has_executed_tag = bool(
                        re.search(
                            rf"(?:@|\b){re.escape(tag_bare)}\b|test_[a-zA-Z0-9_]*{re.escape(tag_bare)}\b",
                            execution_text,
                            re.IGNORECASE,
                        )
                    )
                    if not has_executed_tag and tag in work_mappings:
                        has_executed_tag = any(
                            bool(re.search(rf"\b{re.escape(ref)}\b", execution_text))
                            for ref in work_mappings[tag]
                        )

                    is_skipped = bool(
                        re.search(
                            rf"{re.escape(tag_bare)}[^\n]*\bSKIPPED\b|\bSKIPPED\b[^\n]*{re.escape(tag_bare)}",
                            execution_text,
                            re.IGNORECASE,
                        )
                    )
                    if is_zero_collected or is_skipped or not has_executed_tag:
                        del report.covered[tag]
                        if tag not in report.uncovered:
                            report.uncovered.append(tag)

    return report
