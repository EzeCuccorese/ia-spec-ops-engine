"""Local telemetry configuration, threshold state, and optional notifications."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any


def atomic_json_write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, delete=False
        ) as handle:
            json.dump(value, handle, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
            temporary = Path(handle.name)
        temporary.replace(path)
    finally:
        if temporary and temporary.exists():
            temporary.unlink(missing_ok=True)


def _normalize_config_data(data: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(data)
    for field_name in ("daily_thresholds_pct", "monthly_thresholds_pct"):
        if field_name in normalized:
            normalized[field_name] = tuple(int(value) for value in normalized[field_name])
    if "holiday_dates" in normalized:
        normalized["holiday_dates"] = tuple(str(value) for value in normalized["holiday_dates"])
    return normalized


def _filter_known_fields(
    known_fields: dict[str, Any], data: dict[str, Any], path: Path
) -> dict[str, Any]:
    ignored = sorted(set(data) - set(known_fields))
    if ignored:
        print(f"warning: ignoring unknown key(s) in {path}: {', '.join(ignored)}", file=sys.stderr)
    return {key: value for key, value in data.items() if key in known_fields}


@dataclass(frozen=True)
class UsageConfig:
    monthly_budget_usd: float = 100.0
    monthly_hard_limit_usd: float | None = None
    calibration: float = 1.0
    daily_thresholds_pct: tuple[int, ...] = (50, 75, 90, 100)
    monthly_thresholds_pct: tuple[int, ...] = (50, 75, 90, 100)
    notify_macos: bool = False
    holiday_dates: tuple[str, ...] = ()

    @property
    def holidays(self) -> set[date]:
        try:
            return {date.fromisoformat(value) for value in self.holiday_dates}
        except ValueError as exc:
            raise ValueError(f"Invalid holiday date: {exc}") from exc

    @property
    def effective_monthly_limit(self) -> float:
        if self.monthly_hard_limit_usd is None:
            return self.monthly_budget_usd
        return min(self.monthly_budget_usd, self.monthly_hard_limit_usd)

    @classmethod
    def load(cls, path: Path) -> UsageConfig:
        if not path.exists():
            return cls()
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("Telemetry config must be a JSON object")
        normalized = _normalize_config_data(data)
        known = _filter_known_fields(cls.__dataclass_fields__, normalized, path)
        config = cls(**known)
        if config.monthly_budget_usd <= 0 or config.calibration <= 0:
            raise ValueError("Budget and calibration must be greater than zero")
        return config

    def save(self, path: Path) -> None:
        data = asdict(self)
        data["daily_thresholds_pct"] = list(self.daily_thresholds_pct)
        data["monthly_thresholds_pct"] = list(self.monthly_thresholds_pct)
        data["holiday_dates"] = list(self.holiday_dates)
        atomic_json_write(path, data)


@dataclass(frozen=True)
class _ThresholdCheck:
    label: str
    cost: float
    limit: float
    thresholds: tuple[int, ...]


class ThresholdTracker:
    @staticmethod
    def _crossed(percent: float, thresholds: tuple[int, ...], notified: list[int]) -> int | None:
        matches = [
            value for value in sorted(thresholds) if percent >= value and value not in notified
        ]
        return matches[-1] if matches else None

    @classmethod
    def _check_period(cls, check: _ThresholdCheck, notified: list[int]) -> str | None:
        pct = check.cost / check.limit * 100 if check.limit else 0.0
        hit = cls._crossed(pct, check.thresholds, notified)
        if hit is None:
            return None
        notified.append(hit)
        return f"{check.label} estimated usage crossed {hit}% (${check.cost:.2f})."

    @classmethod
    def evaluate(
        cls,
        summary: dict[str, float],
        config: UsageConfig,
        state: dict[str, Any],
        *,
        today: date | None = None,
    ) -> tuple[list[str], dict[str, Any]]:
        current = today or date.today()
        day_key, month_key = current.isoformat(), current.strftime("%Y-%m")
        day_notified = list(state.get("day_notified", [])) if state.get("day") == day_key else []
        month_notified = (
            list(state.get("month_notified", [])) if state.get("month") == month_key else []
        )
        daily_budget = float(summary.get("daily_budget_usd") or 0)
        day_cost = float(summary.get("today_cost_usd") or 0)
        month_cost = float(summary.get("month_cost_usd") or 0)
        daily = _ThresholdCheck("Daily", day_cost, daily_budget, config.daily_thresholds_pct)
        monthly = _ThresholdCheck(
            "Monthly", month_cost, config.effective_monthly_limit, config.monthly_thresholds_pct
        )
        candidates = (
            cls._check_period(daily, day_notified),
            cls._check_period(monthly, month_notified),
        )
        messages = [msg for msg in candidates if msg is not None]
        updated = {
            "day": day_key,
            "day_notified": sorted(set(day_notified)),
            "month": month_key,
            "month_notified": sorted(set(month_notified)),
            "last_day_cost": day_cost,
            "last_month_cost": month_cost,
        }
        return messages, updated

    @staticmethod
    def load(path: Path) -> dict[str, Any]:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (OSError, ValueError):
            return {}

    @staticmethod
    def save(path: Path, state: dict[str, Any]) -> None:
        atomic_json_write(path, state)


def _escape_applescript(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"').replace("\r", " ").replace("\n", " ")


def notify_macos(title: str, message: str) -> bool:
    escaped_title = _escape_applescript(title)
    escaped_message = _escape_applescript(message)
    script = f'display notification "{escaped_message}" with title "{escaped_title}"'
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            timeout=5,
            check=False,
        )
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False
