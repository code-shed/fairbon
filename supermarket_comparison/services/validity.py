"""Offer validity classification in ``Europe/Berlin`` local time.

The upstream APIs return UTC timestamps such as ``2026-11-07T22:59:59Z``.
That is ``2026-11-07 23:59:59`` in Berlin (CET) and therefore still part of
the *local* day 7 November, while ``2026-11-08T23:00:00Z`` is already
``00:00`` on 9 November.  All comparisons therefore happen on Berlin local
dates, never on naive ``datetime.now()`` values.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any, Final, Literal
from zoneinfo import ZoneInfo

BERLIN: Final = ZoneInfo("Europe/Berlin")

ValidityState = Literal["today", "upcoming", "expired", "unknown"]

_WEEKDAYS: Final = (
    "Montag",
    "Dienstag",
    "Mittwoch",
    "Donnerstag",
    "Freitag",
    "Samstag",
    "Sonntag",
)


@dataclass(frozen=True)
class Validity:
    """Result of :func:`classify`."""

    state: ValidityState
    label: str
    starts: date | None = None
    ends: date | None = None


_UNKNOWN: Final = Validity(state="unknown", label="")


def _local_date(value: Any) -> date | None:
    """Convert an ISO string/date/datetime to a Berlin local date."""

    if value is None or isinstance(value, bool):
        return None

    moment: datetime | None = None

    if isinstance(value, datetime):
        moment = value
    elif isinstance(value, date):
        return value
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            # Date-only strings are also valid ISO values.
            try:
                return date.fromisoformat(text)
            except ValueError:
                return None
    elif isinstance(value, (int, float)):
        try:
            moment = datetime.fromtimestamp(float(value), tz=UTC)
        except (OverflowError, OSError, ValueError):
            return None
    else:
        return None

    if moment.tzinfo is None:
        # The documented API contract is UTC ISO; treat naive values as UTC.
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(BERLIN).date()


def _now_date(now: datetime | None) -> date:
    if now is None:
        return datetime.now(tz=BERLIN).date()
    if isinstance(now, datetime):
        if now.tzinfo is None:
            return now.replace(tzinfo=BERLIN).date()
        return now.astimezone(BERLIN).date()
    return _local_date(now) or datetime.now(tz=BERLIN).date()


def _format_upcoming(start: date, today: date) -> str:
    weekday = _WEEKDAYS[start.weekday()]
    if start.year == today.year:
        return f"Ab {weekday}, {start.day:02d}.{start.month:02d}."
    return f"Ab {weekday}, {start.day:02d}.{start.month:02d}.{start.year}"


def classify(
    valid_from: Any,
    valid_to: Any,
    *,
    now: datetime | None = None,
) -> Validity:
    """Classify an offer as ``today``, ``upcoming``, ``expired`` or ``unknown``.

    Missing ``valid_from`` means "already started"; missing ``valid_to`` means
    "open ended".  Malformed values degrade to ``unknown`` instead of raising.
    """

    try:
        start = _local_date(valid_from)
        end = _local_date(valid_to)
    except (TypeError, ValueError, OverflowError):
        return _UNKNOWN

    if valid_from is not None and start is None:
        return _UNKNOWN
    if valid_to is not None and end is None:
        return _UNKNOWN
    if start is None and end is None:
        return _UNKNOWN

    today = _now_date(now)

    if start is not None and start > today:
        return Validity(
            state="upcoming",
            label=_format_upcoming(start, today),
            starts=start,
            ends=end,
        )
    if end is not None and end < today:
        return Validity(state="expired", label="Abgelaufen", starts=start, ends=end)

    return Validity(state="today", label="Heute gültig", starts=start, ends=end)


def is_today(valid_from: Any, valid_to: Any, now: datetime | None = None) -> bool:
    """Whether an offer is valid on the current Berlin local date."""

    return classify(valid_from, valid_to, now=now).state == "today"


__all__ = ["BERLIN", "Validity", "ValidityState", "classify", "is_today"]
