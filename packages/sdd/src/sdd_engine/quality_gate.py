"""
Quality Gate Harness for Devscripts Refactor.

Provides baseline snapshot capture, test regression detection, entry point verification,
public contract auditing, and gate check orchestration.
"""

from dataclasses import dataclass, field, asdict
import datetime
import importlib
import json
import os
from pathlib import Path
import sys
import tomllib
from typing import Dict, List, Any, Optional, Tuple, Union

from sdd_engine.utils import run_command_safe



@dataclass(frozen=True)
class BaselineSnapshot:
    timestamp: str
    total_tests: int
    passed_tests: int
    failed_tests: int
    skipped_tests: int
    entry_points: Dict[str, str]
    public_contracts: Dict[str, List[str]]
    test_names: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BaselineSnapshot":
        return cls(
            timestamp=str(data.get("timestamp", "")),
            total_tests=int(data.get("total_tests", 0)),
            passed_tests=int(data.get("passed_tests", 0)),
            failed_tests=int(data.get("failed_tests", 0)),
            skipped_tests=int(data.get("skipped_tests", 0)),
            entry_points=dict(data.get("entry_points", {})),
            public_contracts={k: list(v) for k, v in data.get("public_contracts", {}).items()},
            test_names=list(data.get("test_names", [])),
        )

    @classmethod
    def from_json(cls, json_str: str) -> "BaselineSnapshot":
        return cls.from_dict(json.loads(json_str))


@dataclass(frozen=True)
class TestDelta:
    __test__ = False

    status: str  # "PASS", "REGRESSION", "NEW_FAILING"
    baseline_passed: int
    current_passed: int
    regressions: List[str]
    new_failures: List[str]
    new_skipped: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TestDelta":
        return cls(
            status=str(data.get("status", "PASS")),
            baseline_passed=int(data.get("baseline_passed", 0)),
            current_passed=int(data.get("current_passed", 0)),
            regressions=list(data.get("regressions", [])),
            new_failures=list(data.get("new_failures", [])),
            new_skipped=list(data.get("new_skipped", [])),
        )


@dataclass(frozen=True)
class EntryPointCheck:
    passed: bool
    total: int
    successful: List[str]
    failed: Dict[str, str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EntryPointCheck":
        return cls(
            passed=bool(data.get("passed", False)),
            total=int(data.get("total", 0)),
            successful=list(data.get("successful", [])),
            failed=dict(data.get("failed", {})),
        )


@dataclass(frozen=True)
class ContractCheck:
    passed: bool
    missing_symbols: Dict[str, List[str]]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ContractCheck":
        return cls(
            passed=bool(data.get("passed", False)),
            missing_symbols={k: list(v) for k, v in data.get("missing_symbols", {}).items()},
        )


@dataclass(frozen=True)
class GateResult:
    passed: bool
    timestamp: str
    phase: str  # "pre-task", "post-task", "convergence"
    test_result: TestDelta
    entry_point_result: EntryPointCheck
    contract_result: ContractCheck
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GateResult":
        return cls(
            passed=bool(data.get("passed", False)),
            timestamp=str(data.get("timestamp", "")),
            phase=str(data.get("phase", "pre-task")),
            test_result=TestDelta.from_dict(data.get("test_result", {})),
            entry_point_result=EntryPointCheck.from_dict(data.get("entry_point_result", {})),
            contract_result=ContractCheck.from_dict(data.get("contract_result", {})),
            details=dict(data.get("details", {})),
        )


def parse_pyproject_entry_points(pyproject_path: Optional[Path] = None) -> Dict[str, str]:
    if pyproject_path is None:
        pyproject_path = Path.cwd() / "pyproject.toml"

    if not pyproject_path.exists():
        return {}

    with open(pyproject_path, "rb") as f:
        data = tomllib.load(f)

    scripts = data.get("project", {}).get("scripts", {})
    return {str(k): str(v) for k, v in scripts.items()}


def verify_entry_points(entry_points: Dict[str, str]) -> EntryPointCheck:
    successful: List[str] = []
    failed: Dict[str, str] = {}

    for name, target in entry_points.items():
        if ":" not in target:
            failed[name] = f"Invalid target format '{target}' (missing ':')"
            continue

        module_path, func_name = target.rsplit(":", 1)
        try:
            mod = importlib.import_module(module_path)
            if not hasattr(mod, func_name):
                failed[name] = f"Module '{module_path}' has no attribute '{func_name}'"
            elif not callable(getattr(mod, func_name)):
                failed[name] = f"Attribute '{func_name}' in '{module_path}' is not callable"
            else:
                successful.append(name)
        except Exception as err:
            failed[name] = f"Failed to import '{module_path}': {err}"

    passed = len(failed) == 0
    return EntryPointCheck(
        passed=passed,
        total=len(entry_points),
        successful=successful,
        failed=failed,
    )


def extract_public_contracts(root_dir: Optional[Path] = None) -> Dict[str, List[str]]:
    if root_dir is None:
        root_dir = Path.cwd()

    package_dirs = []
    if (root_dir / "packages").is_dir():
        package_dirs.extend((root_dir / "packages").glob("*/src/*"))
    if (root_dir / "src").is_dir():
        package_dirs.append(root_dir / "src")
    if not package_dirs and (root_dir / "devscripts").exists():
        package_dirs.append(root_dir / "devscripts")

    contracts: Dict[str, List[str]] = {}
    for p_dir in package_dirs:
        for py_file in p_dir.glob("**/*.py"):
            if py_file.name.startswith("_") and py_file.name != "__init__.py":
                continue
            rel = py_file.relative_to(root_dir)

        mod_parts = list(rel.parts)
        if mod_parts[-1] == "__init__.py":
            mod_parts = mod_parts[:-1]
        else:
            mod_parts[-1] = mod_parts[-1][:-3]

        mod_path = ".".join(mod_parts)
        if not mod_path:
            continue

        try:
            mod = importlib.import_module(mod_path)
            if hasattr(mod, "__all__"):
                symbols = list(getattr(mod, "__all__"))
            else:
                symbols = [n for n in dir(mod) if not n.startswith("_")]
            if symbols:
                contracts[mod_path] = sorted(symbols)
        except Exception:
            continue

    return contracts


def verify_public_contracts(contracts: Dict[str, List[str]]) -> ContractCheck:
    missing_symbols: Dict[str, List[str]] = {}

    for mod_path, expected_symbols in contracts.items():
        try:
            mod = importlib.import_module(mod_path)
            if hasattr(mod, "__all__"):
                current_symbols = set(getattr(mod, "__all__"))
            else:
                current_symbols = {n for n in dir(mod) if not n.startswith("_")}

            missing = set(expected_symbols) - current_symbols
            if missing:
                missing_symbols[mod_path] = sorted(list(missing))
        except Exception as err:
            missing_symbols[mod_path] = [f"MODULE_IMPORT_ERROR: {err}"]

    passed = len(missing_symbols) == 0
    return ContractCheck(
        passed=passed,
        missing_symbols=missing_symbols,
    )


def compare_test_results(
    baseline_passed_names: List[str],
    current_passed_names: List[str],
    current_failed_names: List[str],
    current_skipped_names: List[str],
) -> TestDelta:
    baseline_set = set(baseline_passed_names)
    current_failed_set = set(current_failed_names)
    current_skipped_set = set(current_skipped_names)

    regressions = sorted(list(baseline_set & current_failed_set))
    new_failures = sorted(list(current_failed_set - baseline_set))
    new_skipped = sorted(list(baseline_set & current_skipped_set))

    if regressions:
        status = "REGRESSION"
    elif new_failures:
        status = "NEW_FAILING"
    else:
        status = "PASS"

    return TestDelta(
        status=status,
        baseline_passed=len(baseline_passed_names),
        current_passed=len(current_passed_names),
        regressions=regressions,
        new_failures=new_failures,
        new_skipped=new_skipped,
    )


def _run_pytest_suite(root_dir: Optional[Path] = None) -> Tuple[List[str], List[str], List[str]]:
    """Runs pytest -v to collect node IDs of passed, failed, and skipped tests."""
    if root_dir is None:
        root_dir = Path.cwd()

    tmp_cache = root_dir / ".specify" / ".pytest_cache_gate"
    returncode, stdout, stderr = run_command_safe(["python3", "-m", "pytest", "tests/", "-v", "-o", f"cache_dir={tmp_cache}"], cwd=root_dir)
    output = stdout + "\n" + stderr

    passed: List[str] = []
    failed: List[str] = []
    skipped: List[str] = []

    for line in output.splitlines():
        line = line.strip()
        if " PASSED " in line or line.endswith(" PASSED"):
            node = line.split()[0]
            passed.append(node)
        elif " FAILED " in line or line.endswith(" FAILED"):
            node = line.split()[0]
            failed.append(node)
        elif " SKIPPED " in line or line.endswith(" SKIPPED"):
            node = line.split()[0]
            skipped.append(node)

    return passed, failed, skipped


def capture_baseline(output_path: Optional[Path] = None, root_dir: Optional[Path] = None) -> BaselineSnapshot:
    if root_dir is None:
        root_dir = Path.cwd()

    if output_path is None:
        output_path = root_dir / ".specify/specs/quality-harness-refactor/baseline.json"

    passed, failed, skipped = _run_pytest_suite(root_dir=root_dir)
    entry_points = parse_pyproject_entry_points(pyproject_path=root_dir / "pyproject.toml")
    contracts = extract_public_contracts(root_dir=root_dir)

    timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
    snapshot = BaselineSnapshot(
        timestamp=timestamp,
        total_tests=len(passed) + len(failed) + len(skipped),
        passed_tests=len(passed),
        failed_tests=len(failed),
        skipped_tests=len(skipped),
        entry_points=entry_points,
        public_contracts=contracts,
        test_names=passed,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(snapshot.to_json(), encoding="utf-8")

    return snapshot


def run_gate_check(
    baseline_path: Optional[Path] = None,
    phase: str = "pre-task",
    root_dir: Optional[Path] = None,
) -> GateResult:
    if root_dir is None:
        root_dir = Path.cwd()

    if baseline_path is None:
        baseline_path = root_dir / ".specify/specs/quality-harness-refactor/baseline.json"

    if not baseline_path.exists():
        raise FileNotFoundError(f"Baseline snapshot file not found at '{baseline_path}'. Run `sdd gate snapshot` first.")

    baseline = BaselineSnapshot.from_json(baseline_path.read_text(encoding="utf-8"))

    # 1. Verify Entry Points
    ep_check = verify_entry_points(baseline.entry_points)

    # 2. Verify Contracts
    contract_check = verify_public_contracts(baseline.public_contracts)

    # 3. Run Pytest and Compare
    passed, failed, skipped = _run_pytest_suite(root_dir=root_dir)
    test_delta = compare_test_results(
        baseline_passed_names=baseline.test_names,
        current_passed_names=passed,
        current_failed_names=failed,
        current_skipped_names=skipped,
    )

    overall_pass = ep_check.passed and contract_check.passed and (test_delta.status == "PASS")
    timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()

    return GateResult(
        passed=overall_pass,
        timestamp=timestamp,
        phase=phase,
        test_result=test_delta,
        entry_point_result=ep_check,
        contract_result=contract_check,
        details={
            "baseline_timestamp": baseline.timestamp,
            "total_baseline_tests": baseline.total_tests,
        },
    )
