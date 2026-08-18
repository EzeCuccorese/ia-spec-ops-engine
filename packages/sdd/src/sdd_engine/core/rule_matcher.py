"""
sdd_engine.core.rule_matcher — Motor de indexación dinámica y filtrado de reglas por presupuesto de tokens (Context Engineering).

Analiza las rutas de archivos modificados o en edición y selecciona exclusivamente las reglas
scoped pertinentes junto con las reglas globales, reduciendo el consumo de tokens entre 40% y 70%.
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple, Union

from sdd_engine.adapters.bridge import RuleDefinition, load_rules_catalog
from sdd_engine.core.utils import find_project_root


@dataclass
class RuleMatchResult:
    """Resultado del filtrado dinámico de reglas y estimación de presupuesto de contexto."""

    global_rules: List[RuleDefinition]
    matched_scoped_rules: List[RuleDefinition]
    unmatched_scoped_rules: List[RuleDefinition]
    matched_files: List[str]
    total_catalog_tokens: int
    injected_tokens: int
    saved_tokens: int
    savings_percentage: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "global_rules": [r.name for r in self.global_rules],
            "matched_scoped_rules": [r.name for r in self.matched_scoped_rules],
            "unmatched_scoped_rules": [r.name for r in self.unmatched_scoped_rules],
            "matched_files": self.matched_files,
            "total_catalog_tokens": self.total_catalog_tokens,
            "injected_tokens": self.injected_tokens,
            "saved_tokens": self.saved_tokens,
            "savings_percentage": round(self.savings_percentage, 2),
        }

    def render_context(self) -> str:
        """Genera el texto Markdown optimizado para inyección en el contexto del agente."""
        sections: List[str] = ["# Reglas y Estándares Activos (Filtrado Dinámico de Contexto)\n"]

        if self.global_rules:
            sections.append("## 🌐 Reglas Globales (Universales)\n")
            for r in self.global_rules:
                sections.append(f"### {r.name}\n{r.content.strip()}\n")

        if self.matched_scoped_rules:
            sections.append("## 🎯 Reglas Scoped Aplicables al Diff/Archivos Activos\n")
            for r in self.matched_scoped_rules:
                sections.append(f"### {r.name} (Patrones: {', '.join(r.globs)})\n{r.content.strip()}\n")

        return "\n".join(sections)


def _estimate_tokens(text: str) -> int:
    """Estimación heurística estándar de tokens (promedio ~4 caracteres por token)."""
    return max(1, len(text) // 4)


def match_rules_for_files(
    target_files: Sequence[Union[str, Path]],
    target_dir: Union[str, Path] = ".",
) -> RuleMatchResult:
    """
    Filtra dinámicamente las reglas del catálogo para un conjunto específico de archivos.
    """
    td = Path(target_dir).resolve()
    global_rules, scoped_rules = load_rules_catalog(str(td))

    str_files = [str(Path(f).as_posix()) for f in target_files]
    matched_scoped: List[RuleDefinition] = []
    unmatched_scoped: List[RuleDefinition] = []

    for rule in scoped_rules:
        if rule.always_apply:
            matched_scoped.append(rule)
            continue

        is_matched = False
        for fpath in str_files:
            fname = Path(fpath).name
            for glob_pat in rule.globs:
                clean_glob = glob_pat.strip()
                if fnmatch.fnmatch(fpath, clean_glob) or fnmatch.fnmatch(fname, clean_glob):
                    is_matched = True
                    break
                if clean_glob.startswith("**/"):
                    suffix_pat = clean_glob[3:]
                    if fnmatch.fnmatch(fpath, f"*{suffix_pat}") or fnmatch.fnmatch(fname, suffix_pat):
                        is_matched = True
                        break
            if is_matched:
                break

        if is_matched:
            matched_scoped.append(rule)
        else:
            unmatched_scoped.append(rule)

    # Estimación de presupuesto de contexto
    all_rules_text = "".join([r.content for r in global_rules + scoped_rules])
    injected_rules_text = "".join([r.content for r in global_rules + matched_scoped])

    total_tokens = _estimate_tokens(all_rules_text)
    injected_tokens = _estimate_tokens(injected_rules_text)
    saved_tokens = max(0, total_tokens - injected_tokens)
    savings_pct = (saved_tokens / total_tokens * 100.0) if total_tokens > 0 else 0.0

    return RuleMatchResult(
        global_rules=global_rules,
        matched_scoped_rules=matched_scoped,
        unmatched_scoped_rules=unmatched_scoped,
        matched_files=str_files,
        total_catalog_tokens=total_tokens,
        injected_tokens=injected_tokens,
        saved_tokens=saved_tokens,
        savings_percentage=savings_pct,
    )
