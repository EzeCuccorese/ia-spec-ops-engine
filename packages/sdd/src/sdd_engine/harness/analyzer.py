"""
sdd_engine.analyzer — Auditor estático de consistencia entre artefactos de especificación SDD y validación AST de contratos.
"""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from sdd_engine.core.utils import find_project_root as get_repo_root
from sdd_engine.core.exceptions import AnalysisError, FeatureNotFoundError


def extract_declared_contracts_from_plan(plan_text: str) -> List[str]:
    """
    Extrae nombres de clases, interfaces, modelos o DTOs declarados en plan.md.
    Busca patrones de bloques de código como `class Foo`, `interface Bar`, `type Baz`, `record Qux`.
    """
    contracts: Set[str] = set()
    
    # 1. Regex de clases/interfaces/modelos en snippets de código
    class_pattern = re.compile(r"\b(?:class|interface|type|record|struct|enum)\s+([A-Z][a-zA-Z0-9_]+)\b")
    for match in class_pattern.finditer(plan_text):
        contracts.add(match.group(1))

    # 2. Regex de modelos Pydantic o DTOs mencionados en listas o tablas
    dto_pattern = re.compile(r"`([A-Z][a-zA-Z0-9_]+(?:DTO|Payload|Request|Response|Schema|Model|Config|State))`")
    for match in dto_pattern.finditer(plan_text):
        contracts.add(match.group(1))

    return sorted(list(contracts))


def scan_source_ast_symbols(repo_root: Path) -> Set[str]:
    """
    Escanea el código fuente (Python, TypeScript/JS, Java, Go) para descubrir símbolos declarados en AST.
    """
    symbols: Set[str] = set()

    # 1. Python AST
    for py_file in repo_root.rglob("*.py"):
        if any(part.startswith(".") or part in ("venv", ".venv", "__pycache__", "build", "dist") for part in py_file.parts):
            continue
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8", errors="replace"), filename=str(py_file))
            for node in ast.walk(tree):
                if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                    symbols.add(node.name)
        except Exception:
            pass

    # 2. Otros lenguajes (TypeScript, Java, Go) mediante regex de alto rendimiento
    symbol_regex = re.compile(r"\b(?:class|interface|type|record|struct|enum|func)\s+([A-Z][a-zA-Z0-9_]+)\b")
    for ext in ("*.ts", "*.tsx", "*.java", "*.go", "*.rs"):
        for src_file in repo_root.rglob(ext):
            if any(part.startswith(".") or part in ("node_modules", "target", "build", "vendor") for part in src_file.parts):
                continue
            try:
                text = src_file.read_text(encoding="utf-8", errors="replace")
                for match in symbol_regex.finditer(text):
                    symbols.add(match.group(1))
            except Exception:
                pass

    return symbols


def validate_contracts_conformance(plan_text: str, repo_root: Path) -> Tuple[List[str], List[str]]:
    """
    Verifica si los contratos y modelos declarados en plan.md existen en el código fuente.
    Retorna (matched_symbols, missing_symbols).
    """
    declared = extract_declared_contracts_from_plan(plan_text)
    if not declared:
        return [], []

    source_symbols = scan_source_ast_symbols(repo_root)
    matched = [s for s in declared if s in source_symbols]
    missing = [s for s in declared if s not in source_symbols]
    return matched, missing


def analyze(feature_name: Optional[str] = None) -> bool:
    rr = get_repo_root()
    sd = rr / ".specify"

    if not feature_name:
        ff = sd / "feature.json"
        if ff.exists():
            with open(ff, encoding="utf-8") as f:
                feature_name = json.load(f).get("active_feature", "")
        if not feature_name:
            raise FeatureNotFoundError("Specify feature name or set an active feature using 'sdd feature set <name>'.")

    feat_dir = sd / "specs" / feature_name
    print("========================================================")
    print(f" 🔍 Analyzing SDD consistency for: {feature_name}")
    print("========================================================")

    errors = 0
    warnings = 0

    def check_file(f: Path, label: str) -> None:
        nonlocal errors
        if f.exists():
            print(f"  🟢 [OK] {label} present: {f.name}")
        else:
            print(f"  ❌ [ERROR] {label} MISSING: {f.name}")
            errors += 1

    check_file(feat_dir / "spec.md", "Functional Specification (spec.md)")
    check_file(feat_dir / "clarify.md", "Clarification & Quality Gate (clarify.md)")
    check_file(feat_dir / "plan.md", "Technical Plan & Architecture (plan.md)")
    check_file(feat_dir / "checklist.md", "Quality Gate Checklist (checklist.md)")
    check_file(feat_dir / "tasks.md", "Executable Task Breakdown (tasks.md)")

    pm = feat_dir / "plan.md"
    if pm.exists():
        plan_text = pm.read_text(encoding="utf-8")
        if "mermaid" not in plan_text.lower():
            print("  ⚠️ [WARN] plan.md does not contain a Mermaid diagram.")
            warnings += 1

        matched_contracts, missing_contracts = validate_contracts_conformance(plan_text, rr)
        if matched_contracts or missing_contracts:
            print("  📋 Contract Conformance Audit:")
            for sym in matched_contracts:
                print(f"     ✔ Symbol implemented: {sym}")
            for sym in missing_contracts:
                print(f"     ℹ Symbol declared in plan (pending/planned): {sym}")

    sm = feat_dir / "spec.md"
    if sm.exists():
        t = sm.read_text().lower()
        if "gherkin" not in t and "given" not in t:
            print("  ⚠️ [WARN] spec.md does not contain Gherkin acceptance scenarios.")
            warnings += 1

    print("-" * 56)
    if errors == 0:
        print(f"✅ Analysis completed with 0 errors ({warnings} warning(s)).")
        return True
    else:
        print(f"❌ Analysis failed with {errors} error(s) and {warnings} warning(s).")
        raise AnalysisError(f"Analysis failed with {errors} error(s) and {warnings} warning(s).")
