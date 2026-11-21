"""Tests for Europe/Berlin validity classification and DST boundaries."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from supermarket_comparison.services.validity import classify, is_today

BERLIN = ZoneInfo("Europe/Berlin")


def noon(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, 12, 0, tzinfo=BERLIN)


def test_late_utc_timestamp_is_still_the_same_local_day() -> None:
    # 22:59:59Z on 7 Nov is 23:59:59 CET on 7 Nov.
    validity = classify(None, "2026-11-07T22:59:59Z", now=noon(2026, 11, 7))

    assert validity.state == "today"
    assert validity.label == "Heute gültig"
    assert validity.ends.isoformat() == "2026-11-07"


def test_midnight_utc_is_the_next_local_day() -> None:
    # 23:00:00Z on 8 Nov is 00:00 CET on 9 Nov.
    validity = classify("2026-11-08T23:00:00Z", None, now=noon(2026, 11, 9))

    assert validity.state == "today"
    assert validity.starts.isoformat() == "2026-11-09"


def test_next_local_day_is_upcoming_before_midnight() -> None:
    validity = classify(
        "2026-11-08T23:00:00Z",
        "2026-11-14T22:59:59Z",
        now=noon(2026, 11, 8),
    )

    assert validity.state == "upcoming"
    assert validity.label == "Ab Montag, 09.11."
    assert validity.starts.isoformat() == "2026-11-09"
    assert validity.ends.isoformat() == "2026-11-14"


def test_upcoming_label_includes_the_year_when_it_differs() -> None:
    validity = classify("2027-01-04T00:00:00Z", None, now=noon(2026, 12, 28))

    assert validity.state == "upcoming"
    assert validity.label == "Ab Montag, 04.01.2027"


@pytest.mark.parametrize(
    ("start", "now_date", "expected"),
    [
        # DST starts on Sunday 29 March 2026 (01:00 UTC).
        ("2026-03-29T00:30:00Z", (2026, 3, 29), "today"),
        ("2026-03-30T00:30:00Z", (2026, 3, 29), "upcoming"),
        # DST ends on Sunday 25 October 2026 (01:00 UTC).
        ("2026-10-25T00:30:00Z", (2026, 10, 25), "today"),
        ("2026-10-25T00:30:00Z", (2026, 10, 24), "upcoming"),
    ],
)
def test_dst_boundaries(
    start: str, now_date: tuple[int, int, int], expected: str
) -> None:
    validity = classify(start, None, now=noon(*now_date))
    assert validity.state == expected


def test_expired_offer() -> None:
    validity = classify(
        "2026-10-26T00:00:00Z",
        "2026-11-01T22:59:59Z",
        now=noon(2026, 11, 7),
    )

    assert validity.state == "expired"
    assert validity.label == "Abgelaufen"


def test_unknown_when_both_values_are_missing() -> None:
    validity = classify(None, None, now=noon(2026, 11, 7))

    assert validity.state == "unknown"
    assert validity.label == ""
    assert validity.starts is None
    assert validity.ends is None


@pytest.mark.parametrize("value", ["not-a-date", "2026-13-45", "", object()])
def test_malformed_values_do_not_raise(value: object) -> None:
    validity = classify(value, None, now=noon(2026, 11, 7))
    assert validity.state == "unknown"


def test_malformed_end_degrades_to_unknown() -> None:
    validity = classify("2026-11-01T00:00:00Z", "kaputt", now=noon(2026, 11, 7))
    assert validity.state == "unknown"


def test_open_start_and_open_end() -> None:
    started = classify("2026-11-01T09:00:00Z", None, now=noon(2026, 11, 7))
    ends_later = classify(None, "2026-11-20T22:59:59Z", now=noon(2026, 11, 7))

    assert started.state == "today"
    assert ends_later.state == "today"
    assert started.starts.isoformat() == "2026-11-01"
    assert ends_later.ends.isoformat() == "2026-11-20"
    assert started.label == "Heute gültig"


def test_date_only_strings_are_accepted() -> None:
    validity = classify("2026-11-01", "2026-11-20", now=noon(2026, 11, 7))
    assert validity.state == "today"


def test_naive_now_is_interpreted_as_berlin_time() -> None:
    validity = classify("2026-11-07T00:00:00Z", None, now=datetime(2026, 11, 7, 12))
    assert validity.state == "today"


def test_is_today_helper() -> None:
    now = noon(2026, 11, 7)

    assert is_today("2026-11-01T00:00:00Z", "2026-11-07T22:59:59Z", now) is True
    assert is_today("2026-11-08T23:00:00Z", None, now) is False
    assert is_today("2026-10-01T00:00:00Z", "2026-11-01T22:59:59Z", now) is False
    assert is_today(None, None, now) is False
