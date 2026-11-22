"""Shared pytest fixtures (no background tasks in tests)."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from supermarket_comparison.api.main import create_app
from supermarket_comparison.config import get_settings
from supermarket_comparison.services.rate_limit import (
    read_limiter,
    scan_daily_global,
    scan_daily_per_ip,
)

#: Test-wide admin password so admin-gated endpoints are reachable in tests.
TEST_ADMIN_PASSWORD = "test-admin-pw"


@pytest.fixture(autouse=True)
def _reset_rate_limits() -> Iterator[None]:
    """Reset in-memory rate limiters so tests never trip on a shared bucket."""

    read_limiter.reset()
    scan_daily_global.reset()
    scan_daily_per_ip.clear()
    yield
    read_limiter.reset()
    scan_daily_global.reset()
    scan_daily_per_ip.clear()


@pytest.fixture(autouse=True)
def _reset_vision_settings() -> Iterator[None]:
    """Reset mutated VISION_* settings so tests don't leak state into each other."""

    settings = get_settings()
    previous = {
        key: getattr(settings, key)
        for key in (
            "vision_primary_provider",
            "vision_primary_api_key",
            "vision_primary_model",
            "vision_fallback_provider",
            "vision_fallback_api_key",
            "vision_fallback_model",
            "max_global_scans_per_day",
            "max_scans_per_day_per_ip",
        )
    }
    object.__setattr__(settings, "vision_primary_provider", "")
    object.__setattr__(settings, "vision_primary_api_key", "")
    object.__setattr__(settings, "vision_primary_model", "")
    object.__setattr__(settings, "vision_fallback_provider", "")
    object.__setattr__(settings, "vision_fallback_api_key", "")
    object.__setattr__(settings, "vision_fallback_model", "")
    object.__setattr__(settings, "max_global_scans_per_day", 500)
    object.__setattr__(settings, "max_scans_per_day_per_ip", 15)
    yield
    for key, value in previous.items():
        object.__setattr__(settings, key, value)


@pytest.fixture()
def client() -> Iterator[TestClient]:
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def _admin_password_for_tests() -> Iterator[None]:
    """Give every test a working ADMIN_PASSWORD (fail-closed stays covered)."""

    settings = get_settings()
    previous = settings.admin_password
    object.__setattr__(settings, "admin_password", TEST_ADMIN_PASSWORD)
    yield
    object.__setattr__(settings, "admin_password", previous)
