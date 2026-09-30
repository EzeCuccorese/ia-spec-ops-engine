#!/usr/bin/env python3
"""Summarize results/results.csv into results/summary.md.

Computes, per condition: mean design violations per 100 added lines (total
and per metric), hidden-test pass rate, mean cost/turns; and applies the
decision rule documented in evals/design-rules/README.md.
"""

from __future__ import annotations

import csv
import json
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


def per_condition_stats(rows: list[dict]) -> dict[str, dict]:
    by_condition: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        if row.get("error"):
            continue
        by_condition[row["condition"]].append(row)

    stats = {}
    for condition, crows in by_condition.items():
        total_added = sum(int(r["added_lines"]) for r in crows) or 1
        total_violations = sum(int(r["violations_total"]) for r in crows)
        by_metric: dict[str, int] = defaultdict(int)
        for r in crows:
            metrics = json.loads(r["violations_by_metric"] or "{}")
            for metric, count in metrics.items():
                by_metric[metric] += count

        passed = sum(int(r["hidden_tests_passed"]) for r in crows)
        total_tests = sum(int(r["hidden_tests_total"]) for r in crows) or 1
        costs = [float(r["cost_usd"]) for r in crows if r["cost_usd"]]
        turns = [int(r["num_turns"]) for r in crows if r["num_turns"]]

        stats[condition] = {
            "n_runs": len(crows),
            "violations_per_100_lines": 100 * total_violations / total_added,
            "violations_by_metric_per_100_lines": {
                m: round(100 * c / total_added, 3) for m, c in by_metric.items()
            },
            "hidden_pass_rate": passed / total_tests,
            "mean_cost_usd": sum(costs) / len(costs) if costs else 0.0,
            "mean_turns": sum(turns) / len(turns) if turns else 0.0,
        }
    return stats


def decision(stats: dict[str, dict]) -> list[str]:
    lines = []
    none = stats.get("none")
    rules = stats.get("rules")
    gate = stats.get("gate")
    rules_gate = stats.get("rules+gate")

    if none and rules:
        reduction = (
            (none["violations_per_100_lines"] - rules["violations_per_100_lines"])
            / none["violations_per_100_lines"]
            if none["violations_per_100_lines"] > 0
            else 0.0
        )
        keep = reduction >= 0.30 and rules["hidden_pass_rate"] >= none["hidden_pass_rate"]
        lines.append(
            f"- `rules` vs `none`: violations/100 lines reduced by "
            f"{reduction * 100:.1f}% ({'meets' if reduction >= 0.30 else 'below'} the "
            f"30% bar); pass rate {rules['hidden_pass_rate']:.0%} vs {none['hidden_pass_rate']:.0%}. "
            f"**Decision: {'keep' if keep else 'drop'} the text rules on their own.**"
        )
    else:
        lines.append("- Not enough data for `rules` vs `none` (missing runs).")

    if gate and rules_gate:
        reduction = (
            (gate["violations_per_100_lines"] - rules_gate["violations_per_100_lines"])
            / gate["violations_per_100_lines"]
            if gate["violations_per_100_lines"] > 0
            else 0.0
        )
        cheaper = (
            rules_gate["mean_turns"] < gate["mean_turns"]
            or rules_gate["mean_cost_usd"] < gate["mean_cost_usd"]
        )
        worth_it = reduction >= 0.30 or cheaper
        lines.append(
            f"- `rules+gate` vs `gate`: violations/100 lines reduced by "
            f"{reduction * 100:.1f}%; turns {rules_gate['mean_turns']:.1f} vs "
            f"{gate['mean_turns']:.1f}, cost ${rules_gate['mean_cost_usd']:.3f} vs "
            f"${gate['mean_cost_usd']:.3f}. "
            f"**Decision: rules are {'worth it' if worth_it else 'not worth it'} on top of the gate.**"
        )
    else:
        lines.append("- Not enough data for `rules+gate` vs `gate` (missing runs).")

    return lines


TEST_CONDITIONS = ["tests-none", "tests-rules", "tests-gate", "tests-rules+gate"]


def _num(row: dict, key: str) -> int:
    return int(row.get(key) or 0)


def test_condition_stats(rows: list[dict]) -> dict[str, dict]:
    by_condition: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        if not row.get("error") and row["condition"] in TEST_CONDITIONS:
            by_condition[row["condition"]].append(row)
    stats = {}
    for condition, crows in by_condition.items():
        n = len(crows)
        prod = sum(_num(r, "prod_loc_added") for r in crows) or 1
        mut_total = sum(_num(r, "mutants_total") for r in crows)
        passed = sum(_num(r, "hidden_tests_passed") for r in crows)
        total = sum(_num(r, "hidden_tests_total") for r in crows) or 1
        stats[condition] = {
            "n_runs": n,
            "test_loc_per_100_prod": 100 * sum(_num(r, "test_loc_added") for r in crows) / prod,
            "test_functions": sum(_num(r, "test_functions_added") for r in crows) / n,
            "test_violations": sum(_num(r, "test_violations") for r in crows) / n,
            "mutation_score": (
                100 * sum(_num(r, "mutants_killed") for r in crows) / mut_total
                if mut_total
                else None
            ),
            "hidden_pass_rate": passed / total,
            "mean_cost_usd": sum(float(r["cost_usd"] or 0) for r in crows) / n,
            "mean_turns": sum(_num(r, "num_turns") for r in crows) / n,
        }
    return stats


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
            f"{s['hidden_pass_rate']:.0%} | {s['mean_cost_usd']:.3f} | {s['mean_turns']:.1f} |"
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
            f"{s['hidden_pass_rate']:.0%} | {s['mean_cost_usd']:.3f} | {s['mean_turns']:.1f} |"
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
