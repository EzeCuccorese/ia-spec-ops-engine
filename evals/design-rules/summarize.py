#!/usr/bin/env python3
"""Summarize results/results.csv into results/summary.md.

Computes, per condition: mean design violations per 100 added lines (total
and per metric), hidden-test pass rate, mean cost/turns; and applies the
decision rule documented in evals/design-rules/README.md.
"""

from __future__ import annotations

import csv
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

EVAL_ROOT = Path(__file__).resolve().parent
RESULTS_CSV = EVAL_ROOT / "results" / "results.csv"
SUMMARY_MD = EVAL_ROOT / "results" / "summary.md"
TESTS_CSV = EVAL_ROOT / "results" / "tests-results.csv"
TESTS_SUMMARY_MD = EVAL_ROOT / "results" / "tests-summary.md"


def load_rows(path: Path = RESULTS_CSV) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def _is_valid_run(row: dict) -> bool:
    if (row.get("error") or "").strip():
        return False
    try:
        tests_total = int(row.get("hidden_tests_total") or 0)
        cost = float(row.get("cost_usd") or 0)
    except ValueError:
        return False
    return tests_total > 0 and math.isfinite(cost) and cost >= 0


def _col_sum(crows: list[dict], key: str) -> int:
    return sum(_num(row, key) for row in crows)


def _col_mean(crows: list[dict], key: str) -> float:
    values = [float(row[key]) for row in crows if row.get(key)]
    return sum(values) / len(values) if values else 0.0


def _mean_known_cost(crows: list[dict]) -> float | None:
    values = [float(raw) for row in crows if (raw := (row.get("cost_usd") or "").strip())]
    return sum(values) / len(values) if values else None


def _sum_violations_by_metric(crows: list[dict]) -> dict[str, int]:
    by_metric: dict[str, int] = defaultdict(int)
    for row in crows:
        metrics = json.loads(row["violations_by_metric"] or "{}")
        for metric, count in metrics.items():
            by_metric[metric] += count
    return by_metric


def _summarize_condition(crows: list[dict]) -> dict:
    total_added = _col_sum(crows, "added_lines") or 1
    total_violations = _col_sum(crows, "violations_total")
    by_metric = _sum_violations_by_metric(crows)
    passed = _col_sum(crows, "hidden_tests_passed")
    total_tests = _col_sum(crows, "hidden_tests_total") or 1
    return {
        "n_runs": len(crows),
        "violations_per_100_lines": 100 * total_violations / total_added,
        "violations_by_metric_per_100_lines": {
            m: round(100 * c / total_added, 3) for m, c in by_metric.items()
        },
        "hidden_pass_rate": passed / total_tests,
        "mean_cost_usd": _mean_known_cost(crows),
        "mean_turns": _col_mean(crows, "num_turns"),
    }


def per_condition_stats(rows: list[dict]) -> dict[str, dict]:
    by_condition: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        if _is_valid_run(row):
            by_condition[row["condition"]].append(row)
    return {cond: _summarize_condition(crows) for cond, crows in by_condition.items()}


def _decide_rules_vs_none(none: dict | None, rules: dict | None) -> str:
    if not (none and rules):
        return "- Not enough data for `rules` vs `none` (missing runs)."
    reduction = _reduction(none["violations_per_100_lines"], rules["violations_per_100_lines"])
    keep = reduction >= 0.30 and rules["hidden_pass_rate"] >= none["hidden_pass_rate"]
    bar = "meets" if reduction >= 0.30 else "below"
    verdict = "keep" if keep else "drop"
    return (
        f"- `rules` vs `none`: violations/100 lines reduced by "
        f"{reduction * 100:.1f}% ({bar} the 30% bar); "
        f"pass rate {rules['hidden_pass_rate']:.0%} vs {none['hidden_pass_rate']:.0%}. "
        f"**Decision: {verdict} the text rules on their own.**"
    )


def _decide_rules_gate(gate: dict | None, rules_gate: dict | None) -> str:
    if not (gate and rules_gate):
        return "- Not enough data for `rules+gate` vs `gate` (missing runs)."
    reduction = _reduction(gate["violations_per_100_lines"], rules_gate["violations_per_100_lines"])
    no_more_violations = rules_gate["violations_per_100_lines"] <= gate["violations_per_100_lines"]
    gate_cost = gate.get("mean_cost_usd")
    rg_cost = rules_gate.get("mean_cost_usd")
    comparable_cost = gate_cost is not None and rg_cost is not None
    lower_cost = comparable_cost and rg_cost < gate_cost
    worth_it = no_more_violations and (reduction >= 0.30 or lower_cost)
    verdict = "worth it" if worth_it else "not worth it"
    cost_text = f"cost ${rg_cost:.3f} vs ${gate_cost:.3f}" if comparable_cost else "cost n/a"
    return (
        f"- `rules+gate` vs `gate`: violations/100 lines reduced by "
        f"{reduction * 100:.1f}%; turns {rules_gate['mean_turns']:.1f} vs "
        f"{gate['mean_turns']:.1f}, {cost_text}. "
        f"**Decision: rules are {verdict} on top of the gate.**"
    )


def decision(stats: dict[str, dict]) -> list[str]:
    return [
        _decide_rules_vs_none(stats.get("none"), stats.get("rules")),
        _decide_rules_gate(stats.get("gate"), stats.get("rules+gate")),
    ]


TEST_CONDITIONS = ["tests-none", "tests-rules", "tests-gate", "tests-rules+gate"]


def _num(row: dict, key: str) -> int:
    return int(row.get(key) or 0)


def _summarize_test_condition(crows: list[dict]) -> dict:
    n = len(crows)
    prod = _col_sum(crows, "prod_loc_added") or 1
    mut_total = _col_sum(crows, "mutants_total")
    passed = _col_sum(crows, "hidden_tests_passed")
    total = _col_sum(crows, "hidden_tests_total") or 1
    return {
        "n_runs": n,
        "test_loc_per_100_prod": 100 * _col_sum(crows, "test_loc_added") / prod,
        "test_functions": _col_sum(crows, "test_functions_added") / n,
        "test_violations": _col_sum(crows, "test_violations") / n,
        "mutation_score": (
            100 * _col_sum(crows, "mutants_killed") / mut_total if mut_total else None
        ),
        "hidden_pass_rate": passed / total,
        "mean_cost_usd": _mean_known_cost(crows),
        "mean_turns": _col_sum(crows, "num_turns") / n,
    }


def test_condition_stats(rows: list[dict]) -> dict[str, dict]:
    by_condition: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        if _is_valid_run(row) and row["condition"] in TEST_CONDITIONS:
            by_condition[row["condition"]].append(row)
    return {cond: _summarize_test_condition(crows) for cond, crows in by_condition.items()}


def _reduction(base: float, new: float) -> float:
    return (base - new) / base if base > 0 else 0.0


def test_decision(stats: dict[str, dict]) -> list[str]:
    """Keep guidance if test LOC/100 prod LOC drops >=20% OR test violations drop >=30%,
    while mutation score drops <=5 points and hidden pass rate does not drop."""
    pairs = [("tests-rules", "tests-none"), ("tests-rules+gate", "tests-gate")]
    lines = []
    for new_name, base_name in pairs:
        new, base = stats.get(new_name), stats.get(base_name)
        if not new or not base:
            lines.append(f"- Not enough data for `{new_name}` vs `{base_name}`.")
            continue
        loc = _reduction(base["test_loc_per_100_prod"], new["test_loc_per_100_prod"])
        viol = _reduction(base["test_violations"], new["test_violations"])
        m_new, m_base = new["mutation_score"], base["mutation_score"]
        drop = (m_base - m_new) if m_new is not None and m_base is not None else 0.0
        mutation_ok = drop <= 5
        hidden_ok = new["hidden_pass_rate"] >= base["hidden_pass_rate"]
        keep = (loc >= 0.20 or viol >= 0.30) and mutation_ok and hidden_ok
        lines.append(
            f"- `{new_name}` vs `{base_name}`: test LOC/100 prod LOC {loc * 100:+.1f}% "
            f"reduction (bar 20%); test violations {viol * 100:+.1f}% reduction (bar 30%); "
            f"mutation score drop {drop:.1f} pts (max 5); hidden pass "
            f"{new['hidden_pass_rate']:.0%} vs {base['hidden_pass_rate']:.0%}. "
            f"**Decision: {'keep' if keep else 'drop'} the guidance"
            f"{' on its own' if new_name == 'tests-rules' else ' on top of the gate'}.**"
        )
    return lines


def _format_cost(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.3f}"


def render_tests(stats: dict[str, dict]) -> list[str]:
    if not stats:
        return []
    lines = [
        "## Test-guidance conditions",
        "",
        "| condition | runs | test LOC/100 prod LOC | test funcs/run | test violations/run "
        "| mutation score | hidden pass rate | mean cost (USD) | mean turns |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for condition in TEST_CONDITIONS:
        s = stats.get(condition)
        if not s:
            continue
        mutation = "n/a" if s["mutation_score"] is None else f"{s['mutation_score']:.0f}%"
        lines.append(
            f"| {condition} | {s['n_runs']} | {s['test_loc_per_100_prod']:.1f} | "
            f"{s['test_functions']:.1f} | {s['test_violations']:.2f} | {mutation} | "
            f"{s['hidden_pass_rate']:.0%} | {_format_cost(s['mean_cost_usd'])} | {s['mean_turns']:.1f} |"
        )
    lines += ["", "### Test decision", "", *test_decision(stats), ""]
    return lines


def render(stats: dict[str, dict], tstats: dict[str, dict] | None = None) -> str:
    lines = ["# Design-rules eval summary", ""]
    if not stats and not tstats:
        lines.append("No results yet — run `run.py` first.")
        return "\n".join(lines) + "\n"

    lines.append(
        "| condition | runs | violations/100 lines | hidden pass rate | mean cost (USD) | mean turns |"
    )
    lines.append("|---|---|---|---|---|---|")
    for condition in ["none", "rules", "gate", "rules+gate"]:
        s = stats.get(condition)
        if not s:
            continue
        lines.append(
            f"| {condition} | {s['n_runs']} | {s['violations_per_100_lines']:.2f} | "
            f"{s['hidden_pass_rate']:.0%} | {_format_cost(s['mean_cost_usd'])} | {s['mean_turns']:.1f} |"
        )
    lines.append("")

    lines.append("## Violations per 100 added lines, by metric")
    lines.append("")
    for condition in ["none", "rules", "gate", "rules+gate"]:
        s = stats.get(condition)
        if not s:
            continue
        lines.append(f"- **{condition}**: {s['violations_by_metric_per_100_lines']}")
    lines.append("")

    if any(c in stats for c in ["none", "rules", "gate", "rules+gate"]):
        lines.append("## Decision")
        lines.append("")
        lines.extend(decision(stats))
        lines.append("")

    lines.extend(render_tests(tstats or {}))

    return "\n".join(lines) + "\n"


def render_tests_doc(tstats: dict[str, dict]) -> str:
    lines = ["# Test-guidance eval summary", ""]
    body = render_tests(tstats)
    lines += body if body else ["No results yet."]
    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> int:
    stats = per_condition_stats(load_rows())
    text = render(stats)
    SUMMARY_MD.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY_MD.write_text(text)
    tstats = test_condition_stats(load_rows(TESTS_CSV))
    ttext = render_tests_doc(tstats)
    TESTS_SUMMARY_MD.write_text(ttext)
    print(text)
    print(ttext)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
