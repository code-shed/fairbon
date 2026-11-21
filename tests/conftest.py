"""Shared pytest fixtures (no background tasks in tests)."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from supermarket_comparison.api.main import create_app
from supermarket_comparison.config import get_settings
from supermarket_comparison.services.rate_limit import read_limiter, scan_daily_global

#: Test-wide admin password so admin-gated endpoints are reachable in tests.
TEST_ADMIN_PASSWORD = "test-admin-pw"


@pytest.fixture(autouse=True)
def _reset_rate_limits() -> Iterator[None]:
    """Reset in-memory rate limiters so tests never trip on a shared bucket."""

    read_limiter.reset()
    scan_daily_global.reset()
    yield
    read_limiter.reset()
    scan_daily_global.reset()


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
