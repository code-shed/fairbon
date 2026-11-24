"""Budget period, daily allowance and ring colour calculation."""

from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from supermarket_comparison.services.budget import (
    budget_period,
    daily_allowance,
    ring_state,
)


@pytest.mark.parametrize(
    ("year", "month", "start_day", "start", "end"),
    [
        (2026, 11, 1, date(2026, 11, 1), date(2026, 11, 30)),
        (2026, 11, 25, date(2026, 11, 25), date(2026, 12, 24)),
        (2026, 12, 25, date(2026, 12, 25), date(2027, 1, 24)),
        (2024, 2, 28, date(2024, 2, 28), date(2024, 3, 27)),
        (2026, 1, 31, date(2026, 1, 28), date(2026, 2, 27)),
    ],
)
def test_budget_period(
    year: int,
    month: int,
    start_day: int,
    start: date,
    end: date,
) -> None:
    assert budget_period(year, month, start_day) == (start, end)


@pytest.mark.parametrize(
    ("remaining", "end", "today", "expected"),
    [
        (5718, date(2026, 11, 30), date(2026, 11, 23), 714),
        (1000, date(2026, 11, 30), date(2026, 11, 30), 1000),
        (1000, date(2026, 11, 1), date(2026, 11, 30), 1000),
    ],
)
def test_daily_allowance(
    remaining: int, end: date, today: date, expected: int
) -> None:
    assert daily_allowance(remaining, end, today=today) == expected


@pytest.mark.parametrize(
    ("ratio", "expected"),
    [(0.5, "accent"), (0.31, "accent"), (0.3, "amber"), (0.1, "amber"),
     (0.09, "danger"), (-0.2, "danger")],
)
def test_ring_state(ratio: float, expected: str) -> None:
    assert ring_state(ratio) == expected


def test_stats_honours_custom_budget_start(client: TestClient) -> None:
    response = client.get(
        "/api/v1/receipts/stats",
        params={"month": "2026-11", "start_day": 5},
        headers={"X-Owner-Token": "any-owner-token-1234"},
    )
    assert response.status_code == 200
    period = response.json()["period"]
    assert period == {"from": "2026-11-05", "to": "2026-12-04", "start_day": 5}
