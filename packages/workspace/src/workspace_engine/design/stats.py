"""workspace_engine.design.stats — Metric distribution and limit suggestion."""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lizard_languages import languages

from .config import DesignConfig
from .metrics import FunctionMetrics, analyze_file, supported
from .testquality import is_test_file

METRIC_NAMES = ("complexity", "length", "args", "nesting")


def _extension_to_language() -> dict[str, str]:
    mapping: dict[str, str] = {}
    for reader in languages():
        names = getattr(reader, "language_names", None)
        lang = names[0] if names else "unknown"
        for ext in reader.ext:
            mapping[ext.lstrip(".")] = lang
    return mapping


_EXT_TO_LANG = _extension_to_language()


def language_of(path: str | Path) -> str:
    """Canonical lizard language name for ``path``."""
    suffix = Path(path).suffix.lstrip(".").lower()
    return _EXT_TO_LANG.get(suffix, suffix or "unknown")


@dataclass(frozen=True)
class MetricStats:
    p50: float
    p90: float
    p99: float
    max: int
    exceeded: int


@dataclass(frozen=True)
class Distribution:
    count: int
    metrics: dict[str, MetricStats]


@dataclass(frozen=True)
class DesignStats:
    by_language: dict[str, dict[str, Distribution]]
    suggested_limits: dict[str, int]


def _percentiles(values: list[int]) -> tuple[float, float, float]:
    if not values:
        return 0.0, 0.0, 0.0
    if len(values) == 1:
        val = float(values[0])
        return val, val, val
    q = statistics.quantiles(values, n=100, method="inclusive")
    return float(q[49]), float(q[89]), float(q[98])


def _calculate_metric_stats(values: list[int], limit: int) -> MetricStats:
    if not values:
        return MetricStats(p50=0.0, p90=0.0, p99=0.0, max=0, exceeded=0)
    p50, p90, p99 = _percentiles(values)
    return MetricStats(
        p50=p50,
        p90=p90,
        p99=p99,
        max=max(values),
        exceeded=sum(1 for v in values if v > limit),
    )


def _collect_file_functions(
    root: Path, path: Path
) -> tuple[str, str, list[FunctionMetrics]] | None:
    if not path.is_file() or not supported(path):
        return None
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None

    relative = path.resolve().relative_to(root.resolve()).as_posix()
    ext = path.suffix.lstrip(".")
    split = "test" if is_test_file(relative, ext, source) else "prod"
    lang = language_of(path)
    fms = analyze_file(root, path)
    if not fms:
        return None
    return lang, split, fms


def _group_functions(root: Path, files: list[Path]) -> dict[str, dict[str, list[FunctionMetrics]]]:
    grouped: dict[str, dict[str, list[FunctionMetrics]]] = {}
    for path in files:
        result = _collect_file_functions(root, path)
        if result is None:
            continue
        lang, split, fms = result
        grouped.setdefault(lang, {"prod": [], "test": []})[split].extend(fms)
    return grouped


def _metric_values(fms: list[FunctionMetrics], metric: str) -> list[int]:
    if metric == "nesting":
        return [fm.nesting for fm in fms if fm.nesting is not None]
    return [getattr(fm, metric) for fm in fms]


def _build_distribution(fms: list[FunctionMetrics], limits: dict[str, int]) -> Distribution:
    metric_data: dict[str, MetricStats] = {}
    for metric in METRIC_NAMES:
        vals = _metric_values(fms, metric)
        metric_data[metric] = _calculate_metric_stats(vals, limits[metric])
    return Distribution(count=len(fms), metrics=metric_data)


def _suggest_limits(prod_fms: list[FunctionMetrics], limits: dict[str, int]) -> dict[str, int]:
    suggested: dict[str, int] = {}
    for metric in METRIC_NAMES:
        vals = _metric_values(prod_fms, metric)
        if vals:
            _, _, p99 = _percentiles(vals)
            suggested[metric] = max(1, math.ceil(p99))
        else:
            suggested[metric] = limits[metric]
    return suggested


def compute_stats(root: Path, files: list[Path], config: DesignConfig) -> DesignStats:
    """Analyze all given files and calculate metrics distribution and suggested limits."""
    grouped = _group_functions(root, files)
    limits = {
        "complexity": config.max_complexity,
        "length": config.max_function_lines,
        "args": config.max_args,
        "nesting": config.max_nesting,
    }

    by_language: dict[str, dict[str, Distribution]] = {}
    all_prod_fms: list[FunctionMetrics] = []

    for lang in sorted(grouped.keys()):
        by_language[lang] = {}
        for split in ("prod", "test"):
            fms = grouped[lang].get(split, [])
            if split == "prod":
                all_prod_fms.extend(fms)
            by_language[lang][split] = _build_distribution(fms, limits)

    suggested = _suggest_limits(all_prod_fms, limits)
    return DesignStats(by_language=by_language, suggested_limits=suggested)


def format_stats_json(stats: DesignStats, suggest: bool = False) -> dict[str, Any]:
    """Emit the JSON representation of design stats and suggested limits."""
    data: dict[str, Any] = {
        "by_language": {
            lang: {
                split: {
                    "count": dist.count,
                    "metrics": {
                        m: {
                            "p50": m_stats.p50,
                            "p90": m_stats.p90,
                            "p99": m_stats.p99,
                            "max": m_stats.max,
                            "exceeded": m_stats.exceeded,
                        }
                        for m, m_stats in dist.metrics.items()
                    },
                }
                for split, dist in splits.items()
            }
            for lang, splits in stats.by_language.items()
        }
    }
    if suggest:
        data["suggested"] = {
            "max_complexity": stats.suggested_limits["complexity"],
            "max_function_lines": stats.suggested_limits["length"],
            "max_args": stats.suggested_limits["args"],
            "max_nesting": stats.suggested_limits["nesting"],
        }
    return data


def _fmt_val(val: float) -> str:
    return f"{int(val)}" if val.is_integer() else f"{val:.1f}"


def _format_split_rows(
    lang: str, split: str, dist: Distribution, show_lang: bool = True
) -> list[str]:
    rows: list[str] = []
    for i, metric in enumerate(METRIC_NAMES):
        m_stats = dist.metrics[metric]
        lang_col = lang if (show_lang and i == 0) else ""
        split_col = split if i == 0 else ""
        count_col = str(dist.count) if i == 0 else ""
        p50_s = _fmt_val(m_stats.p50)
        p90_s = _fmt_val(m_stats.p90)
        p99_s = _fmt_val(m_stats.p99)
        rows.append(
            f"{lang_col:<12} {split_col:<6} {metric:<12} {count_col:>6} "
            f"{p50_s:>6} {p90_s:>6} {p99_s:>6} "
            f"{m_stats.max:>6} {m_stats.exceeded:>9}"
        )
    return rows


def format_stats_table(stats: DesignStats) -> str:
    """Format human-readable table of metrics distribution."""
    if not stats.by_language:
        return "No functions found."

    lines: list[str] = [
        f"{'Language':<12} {'Split':<6} {'Metric':<12} {'Count':>6} {'p50':>6} {'p90':>6} {'p99':>6} {'Max':>6} {'Exceeded':>9}",
        f"{'-' * 12} {'-' * 6} {'-' * 12} {'-' * 6} {'-' * 6} {'-' * 6} {'-' * 6} {'-' * 6} {'-' * 9}",
    ]

    for lang, splits in stats.by_language.items():
        first_split = True
        for split in ("prod", "test"):
            dist = splits.get(split)
            if dist and dist.count > 0:
                lines.extend(_format_split_rows(lang, split, dist, show_lang=first_split))
                first_split = False

    return "\n".join(lines)


def format_suggest_toml(suggested: dict[str, int]) -> str:
    """Format suggested limits as a [design] TOML block."""
    return "\n".join(
        [
            "[design]",
            f"max_complexity = {suggested['complexity']}",
            f"max_function_lines = {suggested['length']}",
            f"max_args = {suggested['args']}",
            f"max_nesting = {suggested['nesting']}",
        ]
    )
