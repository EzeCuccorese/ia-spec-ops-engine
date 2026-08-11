"""
Unit tests for devscripts.sdd.verify module.
"""

import json
import pytest
from pathlib import Path

from devscripts.sdd.verify import (
    detect_stack,
    run_linter_check,
    run_test_check,
    run_get_check,
    run_security_pii_audit,
    run_verification,
)
from devscripts.sdd.invariants import VerificationPayload


def test_detect_stack_python(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n")
    assert detect_stack(tmp_path) == "python"


def test_detect_stack_node(tmp_path: Path):
    (tmp_path / "package.json").write_text('{"name": "demo"}')
    assert detect_stack(tmp_path) == "node"


def test_detect_stack_java(tmp_path: Path):
    (tmp_path / "pom.xml").write_text("<project></project>")
    assert detect_stack(tmp_path) == "java"

    gradle_dir = tmp_path / "gradle_proj"
    gradle_dir.mkdir()
    (gradle_dir / "build.gradle").write_text("// gradle")
    assert detect_stack(gradle_dir) == "java"


def test_detect_stack_go(tmp_path: Path):
    (tmp_path / "go.mod").write_text("module example.com/demo")
    assert detect_stack(tmp_path) == "go"


def test_detect_stack_unknown(tmp_path: Path):
    assert detect_stack(tmp_path) == "unknown"


def test_run_linter_check_python_ast(tmp_path: Path):
    # Valid python code
    valid_file = tmp_path / "valid.py"
    valid_file.write_text("def hello():\n    return 'world'\n")

    res = run_linter_check(tmp_path, stack="python")
    assert res["status"] in ("PASS", "FAIL")  # Might run ruff/flake8 if installed, else AST

    # Invalid python code
    invalid_dir = tmp_path / "invalid_proj"
    invalid_dir.mkdir()
    (invalid_dir / "bad.py").write_text("def hello(:\n")
    res_bad = run_linter_check(invalid_dir, stack="python")
    assert res_bad["status"] == "FAIL"


def test_run_get_check_file_read(tmp_path: Path):
    json_file = tmp_path / "data.json"
    json_file.write_text('{"status": "ok"}')

    res = run_get_check(tmp_path, modified_files=[json_file])
    assert res["status"] == "PASS"
    assert len(res["details"]) == 1

    # Missing file
    res_missing = run_get_check(tmp_path, modified_files=[tmp_path / "missing.json"])
    assert res_missing["status"] == "FAIL"
    assert len(res_missing["errors"]) == 1


def test_run_security_pii_audit_clean(tmp_path: Path):
    clean_file = tmp_path / "clean.py"
    clean_file.write_text("# Test file\nemail = 'user@example.com'\n")

    res = run_security_pii_audit(tmp_path, files_to_scan=[clean_file])
    assert res["status"] == "PASS"
    assert len(res["violations"]) == 0


def test_run_security_pii_audit_secrets(tmp_path: Path):
    secret_file = tmp_path / "secrets.py"
    secret_file.write_text(
        "AWS_KEY = 'AKIAXXXXXXXXXXXXXXXX'\n"
        "GITHUB_TOKEN = 'ghp_REDACTEDREDACTEDREDACTEDREDACTEDRE'\n"
        "PII_EMAIL = 'john.doe@sensitivecompany.org'\n"
    )

    res = run_security_pii_audit(tmp_path, files_to_scan=[secret_file])
    assert res["status"] == "FAIL"
    assert len(res["violations"]) >= 3


def test_run_verification_full(tmp_path: Path):
    py_file = tmp_path / "main.py"
    py_file.write_text("print('Hello SDD Verification')\n")

    payload = run_verification(
        target_dir=str(tmp_path),
        modified_files=[py_file],
        run_tests=False,  # Skip running full pytest on dummy dir
    )

    assert isinstance(payload, VerificationPayload)
    assert payload.linter_status in ("PASS", "SKIPPED")
    assert payload.test_status == "SKIPPED"
    assert payload.confirmation_read_status == "PASS"
    assert payload.security_status == "PASS"
    assert payload.passed is True

    # Verification of payload serialization
    p_dict = payload.to_dict()
    restored = VerificationPayload.from_dict(p_dict)
    assert restored.passed == payload.passed
    assert restored.details["stack"] == "python"
