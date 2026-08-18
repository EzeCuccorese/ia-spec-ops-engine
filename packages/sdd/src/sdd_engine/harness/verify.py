"""
devscripts.sdd.verify — Spec-Driven Development Automated Verification Engine.

Provides stack auto-detection (Python/pytest, Node/npm/eslint, Java/gradle/mvn, Go/go test),
linter execution, automated test running, post-mutation GET checks, and PII/Secret security audits.
"""

from __future__ import annotations

import ast
import json
import os
import re
import shutil
import sys
import urllib.request
import urllib.error
from pathlib import Path
from typing import Dict, Any, List, Optional, Union, Tuple

from sdd_engine.core.utils import detect_project_type, ProjectType, run_command_safe
from sdd_engine.core.invariants import VerificationPayload



# Standard Secret & PII Detection Regexes
SECRET_PATTERNS: List[Tuple[str, str]] = [
    ("AWS Key", r"(?:A3T[A-Z0-9]|AKIA|AGPA|AIDA|AROA|AIPA|ANPA|ANVA|ASIA)[A-Z0-9]{16}"),
    ("GitHub Token", r"(?:ghp|gho|ghu|ghs|ghr)_[a-zA-Z0-9]{36}"),
    ("GitHub PAT", r"github_pat_[a-zA-Z0-9]{22}_[a-zA-Z0-9]{59}"),
    ("OpenAI/Anthropic Key", r"sk-(?:ant-)?[a-zA-Z0-9_-]{32,}"),
    ("Private Key Header", r"-----BEGIN (?:RSA|EC|DSA|OPENSSH|PRIVATE) KEY-----"),
    ("Generic Hardcoded Secret", r"(?i)(?:api_key|apikey|secret_key|access_token|auth_token|private_key)\s*[:=]\s*['\"][A-Za-z0-9_\-]{16,}['\"]"),
    ("JWT Token", r"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
]

IGNORED_EMAIL_DOMAINS = {"example.com", "example.org", "test.com", "domain.com", "localhost", "email.com", "schema.org"}

PII_PATTERNS: List[Tuple[str, str]] = [
    ("Credit Card", r"\b(?:4[0-9]{12}(?:[0-9]{3})?|5[1-5][0-9]{14}|3[47][0-9]{13}|6(?:011|5[0-9]{2})[0-9]{12})\b"),
    ("SSN", r"\b\d{3}-\d{2}-\d{4}\b"),
]

EMAIL_REGEX = re.compile(r"\b([A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,}))\b")


def detect_stack(target_dir: Union[str, Path] = ".") -> str:
    """
    Auto-detect target project technology stack.
    Returns: 'python', 'node', 'java', 'go', or 'unknown'.
    """
    path = Path(target_dir).resolve()
    ptype = detect_project_type(path)

    if ptype == ProjectType.PYTHON:
        return "python"
    elif ptype == ProjectType.NODE:
        return "node"
    elif ptype in (ProjectType.SPRING_BOOT, ProjectType.GRADLE, ProjectType.MAVEN):
        return "java"
    elif ptype == ProjectType.GO:
        return "go"

    # Secondary heuristic fallback
    if list(path.glob("*.py")) or list(path.glob("src/**/*.py")):
        return "python"
    if (path / "package.json").is_file() or list(path.glob("*.js")) or list(path.glob("*.ts")):
        return "node"
    if (path / "go.mod").is_file() or list(path.glob("*.go")):
        return "go"
    if (path / "pom.xml").is_file() or (path / "build.gradle").is_file() or (path / "gradlew").is_file() or list(path.glob("*.java")):
        return "java"

    return "unknown"


def run_linter_check(target_dir: Union[str, Path] = ".", stack: Optional[str] = None) -> Dict[str, Any]:
    """
    Execute static linter check based on project stack.
    """
    path = Path(target_dir).resolve()
    stack = stack or detect_stack(path)
    result: Dict[str, Any] = {"status": "SKIPPED", "command": "", "returncode": 0, "output": "", "errors": []}

    if stack == "python":
        if shutil.which("ruff"):
            cmd = ["ruff", "check", "."]
            code, stdout, stderr = run_command_safe(cmd, cwd=str(path))
            result.update({"command": "ruff check .", "returncode": code, "output": stdout + stderr})
            result["status"] = "PASS" if code == 0 else "FAIL"
        elif shutil.which("flake8"):
            cmd = ["flake8"]
            code, stdout, stderr = run_command_safe(cmd, cwd=str(path))
            result.update({"command": "flake8", "returncode": code, "output": stdout + stderr})
            result["status"] = "PASS" if code == 0 else "FAIL"
        else:
            errors = []
            py_files = [f for f in path.rglob("*.py") if not any(part.startswith(".") or part in ("venv", "__pycache__", "build", "dist") for part in f.parts)]
            for py_file in py_files:
                try:
                    ast.parse(py_file.read_text(encoding="utf-8", errors="replace"), filename=str(py_file))
                except SyntaxError as se:
                    errors.append(f"{py_file}:{se.lineno}: SyntaxError: {se.msg}")
            
            if errors:
                result.update({"status": "FAIL", "command": "python_ast_check", "returncode": 1, "output": "\n".join(errors), "errors": errors})
            else:
                result.update({"status": "PASS", "command": "python_ast_check", "returncode": 0, "output": f"Parsed {len(py_files)} Python files clean."})

    elif stack == "node":
        pkg_json = path / "package.json"
        has_lint_script = False
        if pkg_json.is_file():
            try:
                data = json.loads(pkg_json.read_text(encoding="utf-8"))
                has_lint_script = "lint" in data.get("scripts", {})
            except (json.JSONDecodeError, OSError):
                has_lint_script = False

        
        if has_lint_script:
            code, stdout, stderr = run_command_safe(["npm", "run", "lint"], cwd=str(path))
            result.update({"command": "npm run lint", "returncode": code, "output": stdout + stderr})
            result["status"] = "PASS" if code == 0 else "FAIL"
        elif shutil.which("npx"):
            code, stdout, stderr = run_command_safe(["npx", "eslint", "."], cwd=str(path))
            result.update({"command": "npx eslint .", "returncode": code, "output": stdout + stderr})
            result["status"] = "PASS" if code == 0 else "FAIL"
        else:
            result.update({"status": "SKIPPED", "output": "No Node linter found."})

    elif stack == "java":
        if (path / "gradlew").is_file():
            cmd = ["./gradlew", "check"]
            code, stdout, stderr = run_command_safe(cmd, cwd=str(path))
            result.update({"command": "./gradlew check", "returncode": code, "output": stdout + stderr})
            result["status"] = "PASS" if code == 0 else "FAIL"
        elif (path / "pom.xml").is_file():
            cmd = ["./mvnw" if (path / "mvnw").is_file() else "mvn", "compile"]
            code, stdout, stderr = run_command_safe(cmd, cwd=str(path))
            result.update({"command": "mvn compile", "returncode": code, "output": stdout + stderr})
            result["status"] = "PASS" if code == 0 else "FAIL"
        else:
            result.update({"status": "SKIPPED", "output": "No Java build tool found."})

    elif stack == "go":
        if shutil.which("golangci-lint"):
            code, stdout, stderr = run_command_safe(["golangci-lint", "run"], cwd=str(path))
            result.update({"command": "golangci-lint run", "returncode": code, "output": stdout + stderr})
            result["status"] = "PASS" if code == 0 else "FAIL"
        elif shutil.which("go"):
            code, stdout, stderr = run_command_safe(["go", "vet", "./..."], cwd=str(path))
            result.update({"command": "go vet ./...", "returncode": code, "output": stdout + stderr})
            result["status"] = "PASS" if code == 0 else "FAIL"
        else:
            result.update({"status": "SKIPPED", "output": "No Go linter found."})

    return result


def run_test_check(target_dir: Union[str, Path] = ".", stack: Optional[str] = None) -> Dict[str, Any]:
    """
    Execute automated test runner based on project stack.
    """
    path = Path(target_dir).resolve()
    stack = stack or detect_stack(path)
    result: Dict[str, Any] = {"status": "SKIPPED", "command": "", "returncode": 0, "output": ""}

    if stack == "python":
        cmd = [sys.executable, "-m", "pytest"]
        code, stdout, stderr = run_command_safe(cmd, cwd=str(path))
        result.update({"command": "python -m pytest", "returncode": code, "output": stdout + stderr})
        result["status"] = "PASS" if code == 0 else "FAIL"

    elif stack == "node":
        pkg_json = path / "package.json"
        has_test_script = False
        if pkg_json.is_file():
            try:
                data = json.loads(pkg_json.read_text(encoding="utf-8"))
                has_test_script = "test" in data.get("scripts", {})
            except (json.JSONDecodeError, OSError):
                has_test_script = False


        if has_test_script:
            code, stdout, stderr = run_command_safe(["npm", "test"], cwd=str(path))
            result.update({"command": "npm test", "returncode": code, "output": stdout + stderr})
            result["status"] = "PASS" if code == 0 else "FAIL"
        else:
            result.update({"status": "SKIPPED", "output": "No npm test script found."})

    elif stack == "java":
        if (path / "gradlew").is_file():
            cmd = ["./gradlew", "test"]
            code, stdout, stderr = run_command_safe(cmd, cwd=str(path))
            result.update({"command": "./gradlew test", "returncode": code, "output": stdout + stderr})
            result["status"] = "PASS" if code == 0 else "FAIL"
        elif (path / "pom.xml").is_file():
            cmd = ["./mvnw" if (path / "mvnw").is_file() else "mvn", "test"]
            code, stdout, stderr = run_command_safe(cmd, cwd=str(path))
            result.update({"command": "mvn test", "returncode": code, "output": stdout + stderr})
            result["status"] = "PASS" if code == 0 else "FAIL"
        else:
            result.update({"status": "SKIPPED", "output": "No Java test runner found."})

    elif stack == "go":
        if shutil.which("go"):
            code, stdout, stderr = run_command_safe(["go", "test", "./..."], cwd=str(path))
            result.update({"command": "go test ./...", "returncode": code, "output": stdout + stderr})
            result["status"] = "PASS" if code == 0 else "FAIL"
        else:
            result.update({"status": "SKIPPED", "output": "Go binary not found."})

    return result


def run_get_check(
    target_dir: Union[str, Path] = ".",
    modified_files: Optional[List[Union[str, Path]]] = None,
    url: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Execute post-mutation confirmation read check (GET check / file integrity read).
    """
    path = Path(target_dir).resolve()
    result: Dict[str, Any] = {"status": "PASS", "method": "", "details": [], "errors": []}

    # 1. HTTP GET request confirmation check if URL provided
    if url:
        result["method"] = f"HTTP GET {url}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "devscripts-sdd-verify"})
            with urllib.request.urlopen(req, timeout=5) as response:
                status_code = response.getcode()
                if 200 <= status_code < 300:
                    result["details"].append(f"HTTP GET {url} returned {status_code}")
                    result["status"] = "PASS"
                else:
                    result["errors"].append(f"HTTP GET {url} returned status {status_code}")
                    result["status"] = "FAIL"
        except urllib.error.URLError as e:
            result["errors"].append(f"HTTP GET {url} failed: {e}")
            result["status"] = "FAIL"
        return result

    # 2. File read verification for modified files or git modified files
    result["method"] = "File Read Verification"
    files_to_check: List[Path] = []
    
    if modified_files:
        for f in modified_files:
            fp = Path(f) if Path(f).is_absolute() else path / f
            files_to_check.append(fp)
    else:
        code, stdout, _ = run_command_safe(["git", "status", "--porcelain"], cwd=str(path))
        if code == 0 and stdout.strip():
            for line in stdout.strip().splitlines():
                parts = line.strip().split()
                if len(parts) >= 2:
                    files_to_check.append(path / parts[-1])

    if not files_to_check:
        result["details"].append("No specific modified files provided/detected for GET read check.")
        result["status"] = "PASS"
        return result

    # Expand any directory paths into individual files
    expanded_files: List[Path] = []
    for fp in files_to_check:
        if fp.is_dir():
            for sub_fp in fp.rglob("*"):
                if sub_fp.is_file() and not any(p.startswith(".") or p in ("__pycache__", "node_modules", "venv", ".venv") for p in sub_fp.parts):
                    expanded_files.append(sub_fp)
        else:
            expanded_files.append(fp)

    errors = []
    for fp in expanded_files:
        if not fp.exists():
            errors.append(f"File missing post-mutation: {fp}")
            continue
        if not os.access(fp, os.R_OK):
            errors.append(f"File not readable: {fp}")
            continue
        try:
            content = fp.read_bytes()
            if fp.suffix.lower() == ".json":
                json.loads(content.decode("utf-8"))
            elif fp.suffix.lower() == ".py":
                ast.parse(content.decode("utf-8"), filename=str(fp))
            rel = fp.relative_to(path) if fp.is_relative_to(path) else fp
            result["details"].append(f"Verified read: {rel} ({len(content)} bytes)")
        except (json.JSONDecodeError, SyntaxError, UnicodeDecodeError, OSError) as e:
            errors.append(f"Failed to parse/read file {fp}: {e}")

    if errors:
        result["status"] = "FAIL"
        result["errors"] = errors
    else:
        result["status"] = "PASS"

    return result


def run_security_pii_audit(
    target_dir: Union[str, Path] = ".",
    files_to_scan: Optional[List[Union[str, Path]]] = None,
) -> Dict[str, Any]:
    """
    Execute security and PII audit scanning for hardcoded secrets, keys, tokens, and PII.
    """
    path = Path(target_dir).resolve()
    result: Dict[str, Any] = {"status": "PASS", "scanned_files_count": 0, "violations": []}

    target_files: List[Path] = []
    if files_to_scan:
        for f in files_to_scan:
            fp = Path(f) if Path(f).is_absolute() else path / f
            if fp.is_file():
                target_files.append(fp)
    else:
        code, stdout, _ = run_command_safe(["git", "status", "--porcelain"], cwd=str(path))
        if code == 0 and stdout.strip():
            for line in stdout.strip().splitlines():
                parts = line.strip().split()
                if len(parts) >= 2:
                    fp = path / parts[-1]
                    if fp.is_file():
                        target_files.append(fp)
        
        if not target_files:
            valid_exts = {".py", ".js", ".ts", ".java", ".go", ".json", ".yml", ".yaml", ".env", ".properties", ".md"}
            for fp in path.rglob("*"):
                if fp.is_file() and fp.suffix.lower() in valid_exts:
                    if not any(p.startswith(".") or p in ("node_modules", "venv", "__pycache__", "dist", "build", ".git", ".specify") for p in fp.parts):
                        target_files.append(fp)

    violations = []
    result["scanned_files_count"] = len(target_files)

    for fp in target_files:
        try:
            text = fp.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue


        for line_num, line in enumerate(text.splitlines(), start=1):
            for name, pattern in SECRET_PATTERNS:
                if re.search(pattern, line):
                    snippet = line.strip()[:60]
                    violations.append({
                        "file": str(fp.relative_to(path) if fp.is_relative_to(path) else fp),
                        "line": line_num,
                        "type": "SECRET",
                        "rule": name,
                        "snippet": snippet[:15] + "..." if len(snippet) > 15 else snippet,
                    })

            for name, pattern in PII_PATTERNS:
                if re.search(pattern, line):
                    snippet = line.strip()[:60]
                    violations.append({
                        "file": str(fp.relative_to(path) if fp.is_relative_to(path) else fp),
                        "line": line_num,
                        "type": "PII",
                        "rule": name,
                        "snippet": snippet[:15] + "..." if len(snippet) > 15 else snippet,
                    })

            for match in EMAIL_REGEX.finditer(line):
                full_email, domain = match.group(1), match.group(2).lower()
                if domain not in IGNORED_EMAIL_DOMAINS:
                    violations.append({
                        "file": str(fp.relative_to(path) if fp.is_relative_to(path) else fp),
                        "line": line_num,
                        "type": "PII",
                        "rule": "Email Address",
                        "snippet": full_email,
                    })

    if violations:
        result["status"] = "FAIL"
        result["violations"] = violations
    else:
        result["status"] = "PASS"

    return result


def run_verification(
    target_dir: str = ".",
    modified_files: Optional[List[Union[str, Path]]] = None,
    get_check_url: Optional[str] = None,
    run_tests: bool = True,
    run_linter: bool = True,
    run_get_check_flag: bool = True,
    run_security: bool = True,
) -> VerificationPayload:
    """
    Run full SDD verification suite on target_dir:
    - Stack autodetection
    - Static linter check
    - Automated unit test check
    - Post-mutation confirmation read (GET check)
    - PII and Secret security audit
    Returns immutable VerificationPayload.
    """
    path = Path(target_dir).resolve()
    stack = detect_stack(path)

    # 1. Linter
    if run_linter:
        linter_res = run_linter_check(path, stack=stack)
        linter_status = linter_res["status"]
    else:
        linter_res = {"status": "SKIPPED"}
        linter_status = "SKIPPED"

    # 2. Tests
    if run_tests:
        test_res = run_test_check(path, stack=stack)
        test_status = test_res["status"]
    else:
        test_res = {"status": "SKIPPED"}
        test_status = "SKIPPED"

    # 3. GET check
    if run_get_check_flag:
        get_res = run_get_check(path, modified_files=modified_files, url=get_check_url)
        confirmation_read_status = get_res["status"]
    else:
        get_res = {"status": "SKIPPED"}
        confirmation_read_status = "SKIPPED"

    # 4. Security & PII Audit
    if run_security:
        security_res = run_security_pii_audit(path, files_to_scan=modified_files)
        security_status = security_res["status"]
    else:
        security_res = {"status": "SKIPPED"}
        security_status = "SKIPPED"

    statuses = [linter_status, test_status, confirmation_read_status, security_status]
    passed = all(s in ("PASS", "SKIPPED") for s in statuses)

    remediation = []
    if linter_status == "FAIL":
        remediation.append(f"Fix linter issues ({linter_res.get('command')} failed).")
    if test_status == "FAIL":
        remediation.append(f"Fix failing unit tests ({test_res.get('command')} failed).")
    if confirmation_read_status == "FAIL":
        remediation.append(f"Fix post-mutation confirmation read issues: {get_res.get('errors')}")
    if security_status == "FAIL":
        remediation.append(f"Remove hardcoded secrets or PII violations: {security_res.get('violations')}")

    remediation_instructions = " ".join(remediation) if remediation else ""

    details = {
        "stack": stack,
        "target_dir": str(path),
        "linter": linter_res,
        "test": test_res,
        "confirmation_read": get_res,
        "security": security_res,
    }

    return VerificationPayload(
        passed=passed,
        linter_status=linter_status,
        test_status=test_status,
        confirmation_read_status=confirmation_read_status,
        security_status=security_status,
        remediation_instructions=remediation_instructions,
        details=details,
    )
