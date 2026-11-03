"""workspace_engine.design.testquality — junk-test checks, applied to test files only.

Deterministic scanners (no external tools) enforcing the testing rule from the
ai-governance catalog: a test must assert observable behavior.

- ``test-no-assert``: a test function without any assertion.
- ``test-trivial-assert``: an assertion that can never fail (constant or self-comparison).
- ``test-mock-only``: every assertion of a test targets a mock; no result or state is checked.
- ``test-sleep``: a real sleep inside a test file.
- ``test-duplicate``: a test whose body repeats an earlier test of the same file.

Priority languages are Java/Kotlin (JUnit, AssertJ, Mockito), JS/TS (Jest/Vitest), Python
(``ast``) and Go (``testing``/testify). C#, PHP, Rust and Dart get the sleep check only.
Each finding is a ``Violation`` with ``value=1`` and ``limit=0``."""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

from .metrics import Violation
from .testquality_clike import _sleep_hits
from .testquality_parse import _CLIKE_EXT, _JAVA_EXT, _JS_EXT, _SLEEP_ONLY_EXT, _parse
from .testquality_parse import Changed as Changed
from .testquality_python import _python_violations
from .testquality_results import _clike_violations, _Job

TEST_CHECKS = (
    "test-no-assert",
    "test-trivial-assert",
    "test-mock-only",
    "test-sleep",
    "test-duplicate",
)


def _in_segments(parts: list[str], *wanted: str) -> bool:
    size = len(wanted)
    return any(parts[i : i + size] == list(wanted) for i in range(len(parts) - size + 1))


def _java_test_path(name: str, directories: list[str], source: str) -> bool:
    return _in_segments(directories, "src", "test") or bool(
        re.search(r"(?:Tests?|IT)\.(?:java|kt)$", name)
    )


def _js_test_path(name: str, directories: list[str], source: str) -> bool:
    return bool(re.search(r"\.(?:test|spec)\.", name)) or "__tests__" in directories


def _py_test_path(name: str, directories: list[str], source: str) -> bool:
    return name.startswith("test_") or name.endswith("_test.py") or "tests" in directories


def _rust_test_path(name: str, directories: list[str], source: str) -> bool:
    return "#[test]" in source or "::test]" in source


def _suffix_rule(suffix: str) -> Callable[[str, list[str], str], bool]:
    return lambda name, directories, source: name.endswith(suffix)


_TEST_PATH_RULES: dict[str, Callable[[str, list[str], str], bool]] = {
    **dict.fromkeys(_JAVA_EXT, _java_test_path),
    **dict.fromkeys(_JS_EXT, _js_test_path),
    "py": _py_test_path,
    "go": _suffix_rule("_test.go"),
    "cs": _suffix_rule("Tests.cs"),
    "php": _suffix_rule("Test.php"),
    "dart": _suffix_rule("_test.dart"),
    "rs": _rust_test_path,
}


def is_test_file(relative: str, extension: str, source: str) -> bool:
    """Whether ``relative`` is a test file according to its language's conventions."""
    rule = _TEST_PATH_RULES.get(extension)
    parts = relative.split("/")
    return rule is not None and rule(parts[-1], parts[:-1], source)


def _file_violations(job: _Job, ext: str, source: str) -> list[Violation]:
    if ext == "py":
        return _python_violations(job, source)
    if ext in _CLIKE_EXT:
        return _clike_violations(job, ext, source)
    if ext in _SLEEP_ONLY_EXT and "test-sleep" in job.active:
        return job.line_hits(_sleep_hits(_parse(job.relative, ext, source)), "test-sleep")
    return []


def junk_test_violations(
    root: Path, paths: list[Path], checks: tuple[str, ...], changed: Changed = None
) -> list[Violation]:
    """Runs the enabled ``test-*`` checks over the test files among ``paths``."""
    active = {name for name in TEST_CHECKS if name in checks}
    if not active:
        return []
    violations: list[Violation] = []
    for path in paths:
        if not path.is_file():
            continue
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        relative = path.resolve().relative_to(root).as_posix()
        ext = path.suffix.lstrip(".")
        if is_test_file(relative, ext, source):
            violations.extend(_file_violations(_Job(relative, active, changed), ext, source))
    violations.sort(key=lambda v: (v.path, v.start_line, v.metric))
    return violations
