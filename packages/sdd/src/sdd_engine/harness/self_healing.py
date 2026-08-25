"""
sdd_engine.harness.self_healing — Orquestador de auto-corrección multi-agente guiado por trazas de error y AST.

Parsea fallos de tests y linters (pytest, npm, junit, ruff, eslint), extrae el contexto mínimo
localizado del error y coordina el ciclo de auto-reparación Worker -> Test -> QA -> Fix.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from sdd_engine.core.utils import find_project_root


@dataclass
class TestFailureDetail:
    """Información estructurada de un fallo en la ejecución de tests."""

    __test__ = False  # Evita que pytest intente recolectar esta dataclass como test

    test_name: str
    file_path: str
    line_number: Optional[int] = None
    error_type: str = "AssertionError"
    error_message: str = ""
    failing_assertion: str = ""
    traceback_snippet: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "test_name": self.test_name,
            "file_path": self.file_path,
            "line_number": self.line_number,
            "error_type": self.error_type,
            "error_message": self.error_message,
            "failing_assertion": self.failing_assertion,
            "traceback_snippet": self.traceback_snippet,
        }


def parse_pytest_failures(output: str) -> List[TestFailureDetail]:
    """Extrae detalles estructurados de fallos generados por pytest."""
    failures: List[TestFailureDetail] = []
    
    # Patrón 1: Bloque de fallo estándar de pytest (FAILED test_file.py::test_func - Error)
    summary_pattern = re.compile(r"FAILED\s+([^\s:]+)::([^\s\-]+)(?:\s+-\s+(.+))?")
    for match in summary_pattern.finditer(output):
        fpath, tname, emsg = match.groups()
        failures.append(
            TestFailureDetail(
                test_name=tname.strip(),
                file_path=fpath.strip(),
                error_message=(emsg or "").strip(),
            )
        )

    # Patrón 2: Ubicación de archivo y línea al pie del bloque de error (ej: tests/test_flow.py:42: AssertionError)
    file_line_pattern = re.compile(r"([^\s\n]+\.py):(\d+):\s*([A-Za-z0-9_]+Error)?")
    for match in file_line_pattern.finditer(output):
        fpath, line_str, err_type = match.groups()
        for f in failures:
            if f.file_path in fpath or fpath in f.file_path:
                if f.line_number is None:
                    f.line_number = int(line_str)
                if err_type and f.error_type == "AssertionError":
                    f.error_type = err_type

    # Patrón 3: Extracción de excepciones y líneas (E   assert ...)
    assertion_pattern = re.compile(r"([^\n]+\.py):(\d+):\s+in\s+([^\n]+)\n[\s\S]*?(E\s+[^\n]+)", re.MULTILINE)
    for match in assertion_pattern.finditer(output):
        fpath, line_str, func_name, assertion_line = match.groups()
        matched_existing = next((f for f in failures if f.file_path in fpath or f.test_name in func_name), None)
        if matched_existing:
            if matched_existing.line_number is None:
                matched_existing.line_number = int(line_str)
            matched_existing.failing_assertion = assertion_line.strip()
            if not matched_existing.error_message:
                matched_existing.error_message = assertion_line.strip()
        else:
            failures.append(
                TestFailureDetail(
                    test_name=func_name.strip(),
                    file_path=fpath.strip(),
                    line_number=int(line_str),
                    error_message=assertion_line.strip(),
                    failing_assertion=assertion_line.strip(),
                )
            )

    return failures


def parse_generic_failures(output: str, stack: str = "generic") -> List[TestFailureDetail]:
    """Parser genérico de errores y fallos de ejecución."""
    if stack == "python" or "FAILED" in output or "pytest" in output:
        return parse_pytest_failures(output)

    failures: List[TestFailureDetail] = []
    error_line_pattern = re.compile(r"(?:FAIL|Error|Exception):\s*(.+)", re.IGNORECASE)
    for line in output.splitlines():
        m = error_line_pattern.search(line)
        if m:
            failures.append(
                TestFailureDetail(
                    test_name="generic_test",
                    file_path="unknown",
                    error_message=m.group(1).strip(),
                )
            )
    return failures


@dataclass
class SelfHealingCycle:
    """Gestiona el estado y presupuesto de reintentos de auto-corrección."""

    task_id: str
    max_retries: int = 3
    current_attempt: int = 0
    history: List[Dict[str, Any]] = field(default_factory=list)

    def record_attempt(
        self,
        passed: bool,
        failures: List[TestFailureDetail],
        linter_errors: List[str],
        patch_summary: str = "",
    ) -> Dict[str, Any]:
        self.current_attempt += 1
        attempt_record = {
            "attempt": self.current_attempt,
            "passed": passed,
            "failures_count": len(failures),
            "linter_errors_count": len(linter_errors),
            "patch_summary": patch_summary,
            "can_retry": (not passed) and (self.current_attempt < self.max_retries),
        }
        self.history.append(attempt_record)
        return attempt_record

    def generate_repair_instructions(
        self,
        failures: List[TestFailureDetail],
        linter_errors: List[str],
    ) -> str:
        """Genera el prompt de reparación enfocado para el Worker Agent."""
        instructions: List[str] = [
            f"### 🛠️ Instrucciones de Auto-Corrección SDD (Intento {self.current_attempt}/{self.max_retries})\n",
            "Se detectaron fallos durante la verificación automatizada del Quality Gate. Aplica una corrección mínima focalizada:\n",
        ]

        if linter_errors:
            instructions.append("#### 🚨 Errores de Linter:")
            for err in linter_errors[:5]:
                instructions.append(f"- `{err}`")
            instructions.append("")

        if failures:
            instructions.append("#### 🧪 Tests Fallidos:")
            for f in failures[:5]:
                loc = f"{f.file_path}:{f.line_number}" if f.line_number else f.file_path
                instructions.append(f"- **Test**: `{f.test_name}` ({loc})")
                if f.failing_assertion:
                    instructions.append(f"  - **Fallo**: `{f.failing_assertion}`")
                elif f.error_message:
                    instructions.append(f"  - **Mensaje**: `{f.error_message}`")
            instructions.append("")

        instructions.append(
            "> [!IMPORTANT]\n"
            "> - Mantener la modificación estrictamente acotada a resolver el fallo.\n"
            "> - No alterar contratos de datos ni romper especificaciones previas.\n"
        )
        return "\n".join(instructions)
