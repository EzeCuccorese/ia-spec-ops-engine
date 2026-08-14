"""
sdd_engine.analyzer — Auditor estático de consistencia entre artefactos de especificación SDD.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from sdd_engine.utils import find_project_root as get_repo_root
from sdd_engine.exceptions import AnalysisError, FeatureNotFoundError



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
    if pm.exists() and "mermaid" not in pm.read_text().lower():
        print("  ⚠️ [WARN] plan.md does not contain a Mermaid diagram.")
        warnings += 1

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
