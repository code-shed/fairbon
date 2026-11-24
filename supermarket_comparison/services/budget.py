"""Local budget period maths shared by the API and the overview UI.

A budget period starts on a configurable day (1–28) and ends the day
before the next period starts, e.g. 25.11 – 24.12 for a salary-day budget.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Final

__all__ = ["budget_period", "daily_allowance", "ring_state"]

MAX_START_DAY: Final = 28

#: Remaining fraction thresholds for the ring colour.
_AMBER_BELOW: Final = 0.30
_DANGER_BELOW: Final = 0.10


def _clamped_day(start_day: int) -> int:
    try:
        return max(1, min(MAX_START_DAY, int(start_day)))
    except (TypeError, ValueError):
        return 1


def budget_period(year: int, month: int, start_day: int = 1) -> tuple[date, date]:
    """Return the inclusive ``(start, end)`` of the budget period."""

    day = _clamped_day(start_day)
    year, month = int(year), int(month)
    month = max(1, min(12, month))
    start = date(year, month, day)
    next_year, next_month = (year + 1, 1) if month == 12 else (year, month + 1)
    end = date(next_year, next_month, day) - timedelta(days=1)
    return start, end


def daily_allowance(
    remaining_cents: int, period_end: date, *, today: date | None = None
) -> int:
    """Even split of the remaining budget over the days still in the period."""

    current = today or date.today()
    remaining_days = max(1, (period_end - current).days + 1)
    return max(0, int(remaining_cents)) // remaining_days


def ring_state(remaining_ratio: float) -> str:
    """Ring colour key for the remaining-budget fraction."""

    if remaining_ratio > _AMBER_BELOW:
        return "accent"
    if remaining_ratio >= _DANGER_BELOW:
        return "amber"
    return "danger"
