"""In-memory rate limiting and a global daily counter (circuit breaker).

Phase 1 ships the skeleton: an IP-keyed sliding window limiter and a
persistent-in-memory daily counter.  The scan endpoints in Phase 2 use
``scan_limit`` (default 3/min, 15/day per IP, configurable) and the global
``MAX_GLOBAL_SCANS_PER_DAY`` cap.

The limiter only trusts ``CF-Connecting-IP`` / ``X-Forwarded-For`` when the
deployment sets ``TRUST_PROXY=true`` — otherwise it uses the socket peer IP
so a client cannot spoof its way around a limit.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Final

from fastapi import Request

from ..config import get_settings


@dataclass
class _Window:
    """Fixed 60-second window with a counter."""

    window_start: float
    count: int


class SlidingWindowLimiter:
    """Per-key token counts inside a fixed window (small, lock-guarded)."""

    def __init__(self, *, max_events: int, window_seconds: float = 60.0) -> None:
        self.max_events = max_events
        self.window_seconds = window_seconds
        self._buckets: dict[str, _Window] = {}
        self._lock = threading.Lock()

    def allow(self, key: str, *, now: float | None = None) -> bool:
        moment = now if now is not None else time.monotonic()
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None or moment - bucket.window_start >= self.window_seconds:
                self._buckets[key] = _Window(moment, 1)
                return True
            if bucket.count >= self.max_events:
                return False
            bucket.count += 1
            return True

    def reset(self, key: str | None = None) -> None:
        with self._lock:
            if key is None:
                self._buckets.clear()
            else:
                self._buckets.pop(key, None)


class DailyCounter:
    """A monotonic-day counter (e.g. for the global scan budget)."""

    def __init__(self) -> None:
        self._day: str | None = None
        self._count: int = 0
        self._lock = threading.Lock()

    @staticmethod
    def _today() -> str:
        return time.strftime("%Y-%m-%d", time.localtime())

    def remaining(self, cap: int) -> int:
        return max(0, cap - self.count())

    def count(self) -> int:
        with self._lock:
            if self._day != self._today():
                self._day = self._today()
                self._count = 0
            return self._count

    def increment(self) -> int:
        with self._lock:
            today = self._today()
            if self._day != today:
                self._day = today
                self._count = 0
            self._count += 1
            return self._count

    def reset(self) -> None:
        with self._lock:
            self._day = None
            self._count = 0


#: Defaults — configurable via environment in Phase 2.
READ_LIMIT_PER_MINUTE: Final = 60
SCAN_LIMIT_PER_MINUTE: Final = 3
SCAN_LIMIT_PER_DAY_PER_IP: Final = 15
GLOBAL_SCANS_PER_DAY: Final = 500


def client_ip(request: Request) -> str:
    """Return the client IP, trusting proxy headers only when configured."""

    settings = get_settings()
    if settings.trust_proxy:
        forwarded = request.headers.get("cf-connecting-ip")
        if not forwarded:
            forwarded = (request.headers.get("x-forwarded-for") or "").split(",", 1)[0]
        if forwarded and forwarded.strip():
            return forwarded.strip()
    return request.client.host if request.client else "unknown"


# Module-level singletons (one process; fine for a single-worker service).
read_limiter = SlidingWindowLimiter(max_events=READ_LIMIT_PER_MINUTE)
scan_per_ip_limiter = SlidingWindowLimiter(max_events=SCAN_LIMIT_PER_MINUTE)
scan_daily_per_ip: dict[str, DailyCounter] = {}
scan_daily_global = DailyCounter()


def allow_read(request: Request) -> bool:
    """True when the client is within the read rate limit."""

    return read_limiter.allow(client_ip(request))


def allow_scan(request: Request) -> tuple[bool, str | None]:
    """Check scan limits; returns ``(allowed, reason)``.

    ``reason`` is a German, user-facing message when the limit triggers.
    """

    ip = client_ip(request)
    if not scan_per_ip_limiter.allow(ip):
        return False, "Zu viele Foto-Scans in kurzer Zeit – bitte kurz warten."
    daily = scan_daily_per_ip.setdefault(ip, DailyCounter())
    if daily.count() >= SCAN_LIMIT_PER_DAY_PER_IP:
        return False, "Das Tageslimit für Foto-Scans ist für dieses Gerät erreicht."
    daily.increment()
    return True, None


__all__ = [
    "GLOBAL_SCANS_PER_DAY",
    "READ_LIMIT_PER_MINUTE",
    "SCAN_LIMIT_PER_DAY_PER_IP",
    "SCAN_LIMIT_PER_MINUTE",
    "DailyCounter",
    "SlidingWindowLimiter",
    "allow_read",
    "allow_scan",
    "client_ip",
]
