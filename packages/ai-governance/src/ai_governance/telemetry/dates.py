"""Lenient date parsing for `calibrate`: dates are typed in local time, compared in UTC."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, time

_MONTHS = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")
_SEPARATORS = re.compile(r"[/\-.\s]+")


class DateParseError(ValueError):
    pass


def parse_date(text: str, today: date) -> date:
    """Accept `15`, `15/10`, `15/10/2026`, `10/15`, `2026-10-15`, `20261015` and friends.

    Missing parts come from `today`. With two numbers where both are <= 12 the order is
    day/month (Argentine); a number above 12 settles it either way (31/12 and 12/31 both work).
    """
    cleaned = text.strip()
    if re.fullmatch(r"\d{8}", cleaned):
        year, month, day = int(cleaned[:4]), int(cleaned[4:6]), int(cleaned[6:])
    else:
        parts = [part for part in _SEPARATORS.split(cleaned) if part]
        if not parts or not all(part.isdigit() for part in parts) or len(parts) > 3:
            raise DateParseError(f"cannot read {text!r} as a date")
        year, month, day = _fields(parts, today)
    try:
        return date(year, month, day)
    except ValueError as error:
        raise DateParseError(f"{text!r} is not a valid date") from error


def _fields(parts: list[str], today: date) -> tuple[int, int, int]:
    numbers = [int(part) for part in parts]
    if len(numbers) == 1:
        return today.year, today.month, numbers[0]
    if len(numbers) == 3 and len(parts[0]) == 4:
        return numbers[0], numbers[1], numbers[2]
    first, second = numbers[0], numbers[1]
    day, month = (second, first) if second > 12 >= first else (first, second)
    if len(numbers) == 2:
        return today.year, month, day
    year = numbers[2]
    return (year + 2000 if len(parts[2]) <= 2 else year), month, day


@dataclass(frozen=True)
class Window:
    start: datetime  # aware, local
    end: datetime  # aware, local

    @property
    def utc(self) -> tuple[datetime, datetime]:
        return self.start.astimezone(UTC), self.end.astimezone(UTC)

    def describe(self) -> str:
        start, end = self.utc
        return (
            f"{_label(self.start)} -> {_label(self.end)} (local) = "
            f"{start:%Y-%m-%d %H:%M}Z -> {end:%Y-%m-%d %H:%M}Z"
        )


def _label(moment: datetime) -> str:
    return f"{moment.day} {_MONTHS[moment.month - 1]} {moment.year} {moment:%H:%M}"


def resolve_window(from_text: str | None, to_text: str | None, now: datetime) -> Window:
    """Local-time window: start of `from` (default: day 1 of this month) to end of `to`."""
    now = now.astimezone()
    today = now.date()
    first = parse_date(from_text, today) if from_text else today.replace(day=1)
    start = datetime.combine(first, time.min).astimezone()
    if to_text:
        last = parse_date(to_text, today)
        end = datetime.combine(last, time.max).astimezone()
    else:
        end = now
    if start > end:
        raise DateParseError(f"the range is reversed: {_label(start)} is after {_label(end)}")
    return Window(start, end)
