"""
Unit tests for sdd_engine.verify module.
"""

import json
import pytest
from pathlib import Path

from sdd_engine.verify import (
    detect_stack,
    run_linter_check,
    run_test_check,
    run_get_check,
    run_security_pii_audit,
    run_verification,
)
from sdd_engine.invariants import VerificationPayload


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


def test_detect_stack_secondary_heuristics(tmp_path: Path):
    py_dir = tmp_path / "py_proj"
    py_dir.mkdir()
    (py_dir / "app.py").write_text("print(1)")
    assert detect_stack(py_dir) == "python"

    node_dir = tmp_path / "node_proj"
    node_dir.mkdir()
    (node_dir / "index.js").write_text("console.log(1)")
    assert detect_stack(node_dir) == "node"

    go_dir = tmp_path / "go_proj"
    go_dir.mkdir()
    (go_dir / "main.go").write_text("package main")
    assert detect_stack(go_dir) == "go"

    java_dir = tmp_path / "java_proj"
    java_dir.mkdir()
    (java_dir / "Main.java").write_text("class Main {}")
    assert detect_stack(java_dir) == "java"


def test_run_linter_check_node(tmp_path: Path):
    # Node without package.json or eslint
    res = run_linter_check(tmp_path, stack="node")
    assert res["status"] in ("PASS", "FAIL", "SKIPPED")

    # Node with package.json lint script
    pkg_json = tmp_path / "package.json"
    pkg_json.write_text('{"scripts": {"lint": "echo ok"}}')
    res_script = run_linter_check(tmp_path, stack="node")
    assert res_script["status"] == "PASS"
    assert res_script["command"] == "npm run lint"


def test_run_linter_check_java_and_go(tmp_path: Path):
    # Java empty
    res_java = run_linter_check(tmp_path, stack="java")
    assert res_java["status"] == "SKIPPED"

    # Go empty
    res_go = run_linter_check(tmp_path, stack="go")
    assert res_go["status"] in ("PASS", "FAIL", "SKIPPED")


def test_run_test_check_all_stacks(tmp_path: Path):
    res_py = run_test_check(tmp_path, stack="python")
    assert "status" in res_py

    res_node = run_test_check(tmp_path, stack="node")
    assert res_node["status"] == "SKIPPED"

    pkg_json = tmp_path / "package.json"
    pkg_json.write_text('{"scripts": {"test": "echo test_ok"}}')
    res_node_script = run_test_check(tmp_path, stack="node")
    assert res_node_script["status"] == "PASS"

    res_java = run_test_check(tmp_path, stack="java")
    assert res_java["status"] == "SKIPPED"

    res_go = run_test_check(tmp_path, stack="go")
    assert res_go["status"] in ("PASS", "FAIL", "SKIPPED")



def test_run_get_check_http_url(monkeypatch):
    class DummyResponse:
        def getcode(self):
            return 200
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass

    def dummy_urlopen(req, timeout=5):
        return DummyResponse()

    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", dummy_urlopen)

    res = run_get_check(url="http://localhost:8080/health")
    assert res["status"] == "PASS"
    assert "HTTP GET" in res["method"]


def test_run_get_check_http_url_failure(monkeypatch):
    import urllib.error
    def dummy_urlopen(req, timeout=5):
        raise urllib.error.URLError("Connection refused")

    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", dummy_urlopen)

    res = run_get_check(url="http://localhost:8080/fail")
    assert res["status"] == "FAIL"


def test_run_get_check_unparseable_json(tmp_path: Path):
    bad_json = tmp_path / "bad.json"
    bad_json.write_text("{invalid json")

    res = run_get_check(tmp_path, modified_files=[bad_json])
    assert res["status"] == "FAIL"
    assert len(res["errors"]) == 1


def test_run_security_pii_audit_cc_and_ssn(tmp_path: Path):
    pii_file = tmp_path / "pii.txt"
    pii_file.write_text("SSN: 000-12-3456\nCard: 4532015112830366\n")

    res = run_security_pii_audit(tmp_path, files_to_scan=[pii_file])
    assert res["status"] == "FAIL"
    assert len(res["violations"]) >= 2


def test_run_verification_remediation(tmp_path: Path):
    bad_py = tmp_path / "bad.py"
    bad_py.write_text("def error(:\n")

    payload = run_verification(
        target_dir=str(tmp_path),
        modified_files=[bad_py],
        run_tests=False,
        run_linter=True,
    )

    assert isinstance(payload, VerificationPayload)
    assert payload.linter_status == "FAIL"
    assert payload.passed is False
    assert "Fix linter issues" in payload.remediation_instructions

