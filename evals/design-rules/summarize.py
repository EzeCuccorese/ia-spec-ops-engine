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


def load_rows() -> list[dict]:
    if not RESULTS_CSV.exists():
        return []
    with RESULTS_CSV.open(newline="") as f:
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


def render(stats: dict[str, dict]) -> str:
    lines = ["# Design-rules eval summary", ""]
    if not stats:
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

    lines.append("## Decision")
    lines.append("")
    lines.extend(decision(stats))
    lines.append("")

    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> int:
    rows = load_rows()
    stats = per_condition_stats(rows)
    text = render(stats)
    SUMMARY_MD.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY_MD.write_text(text)
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
