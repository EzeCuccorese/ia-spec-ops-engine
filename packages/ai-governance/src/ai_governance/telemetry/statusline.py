"""
statusline.py — High-visibility ANSI statusline generator for Claude Code.
Consumes native Claude Code payload from stdin and renders live cost, tokens, ctx % and 5h rate limit.
Fail-open: emits empty string if input is unavailable or malformed.
"""

from __future__ import annotations

import json
import sys
import time
from typing import Any

# ANSI Color Codes
RST = "\033[0m"
SEP_C = "\033[2;90m"  # dim gray
LBL = "\033[37m"  # white labels
CYN = "\033[36m"  # cyan for cost
MAG = "\033[35m"  # magenta for tokens
YLW = "\033[33m"  # yellow for context & warning
GRN = "\033[32m"  # green
RED = "\033[31m"  # red for high spend


def format_tokens(total: int) -> str:
    if total >= 1_000_000:
        return f"{total / 1_000_000:.1f}M"
    elif total >= 1_000:
        return f"{total / 1_000:.1f}k"
    return str(total)


def format_statusline(
    payload: dict[str, Any], include_ritmo: bool = False, monthly_budget: float = 0.0
) -> str:
    cost = float((payload.get("cost") or {}).get("total_cost_usd") or 0.0)
    ctx = payload.get("context_window") or {}
    total_in = int(ctx.get("total_input_tokens") or 0)
    total_out = int(ctx.get("total_output_tokens") or 0)
    used_pct = ctx.get("used_percentage")

    rl = payload.get("rate_limits") or {}
    five_hour = rl.get("five_hour") or {}
    usage_pct = five_hour.get("used_percentage")
    resets_at = five_hour.get("resets_at")

    cost_fmt = f"${cost:.2f}"
    total_tok = total_in + total_out
    total_fmt = format_tokens(total_tok)

    sep = f"{SEP_C} | {RST}"
    parts = [f"{LBL}cost:{RST} {CYN}{cost_fmt}{RST}", f"{LBL}tokens:{RST} {MAG}{total_fmt}{RST}"]

    if used_pct is not None:
        try:
            pct_val = round(float(used_pct))
            parts.append(f"{LBL}({RST}{YLW}{pct_val}% ctx{RST}{LBL}){RST}")
        except (ValueError, TypeError):
            pass

    if usage_pct is not None:
        reset_str = ""
        if resets_at is not None:
            try:
                diff = int(resets_at) - int(time.time())
                if diff > 0:
                    hours = diff // 3600
                    mins = (diff % 3600) // 60
                    if hours > 0:
                        reset_str = f" {LBL}resets {hours}h{mins}m{RST}"
                    else:
                        reset_str = f" {LBL}resets {mins}m{RST}"
            except (ValueError, TypeError):
                pass
        try:
            u_val = round(float(usage_pct))
            parts.append(f"{sep}{LBL}usage:{RST} {YLW}{u_val}%{RST}{reset_str}")
        except (ValueError, TypeError):
            pass

    if include_ritmo and monthly_budget > 0:
        from .ritmo import RitmoCalculator

        ritmo_stat = RitmoCalculator.calculate_pace(monthly_budget, actual_spend_usd=cost)
        ritmo_color = GRN if ritmo_stat.is_under_budget else RED
        parts.append(
            f"{sep}{LBL}ritmo:{RST} {ritmo_color}d{ritmo_stat.elapsed_business_days}/{ritmo_stat.total_business_days} ({ritmo_stat.status_label}){RST}"
        )

    # Join the first two parts cleanly, then add subsequent parts
    if len(parts) >= 2:
        out = f"{parts[0]}{sep}{parts[1]}"
        for p in parts[2:]:
            if p.startswith(sep):
                out += p
            else:
                out += f" {p}"
        return out
    return ""


def main() -> int:
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            return 0
        payload = json.loads(raw)
        res = format_statusline(payload)
        if res:
            print(res)
    except Exception:
        pass  # Fail open
    return 0


if __name__ == "__main__":
    sys.exit(main())
