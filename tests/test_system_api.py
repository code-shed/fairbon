"""Tests for the system endpoints: health, backup and restore."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from supermarket_comparison.api.main import create_app
from supermarket_comparison.api.routes.history import get_repository
from supermarket_comparison.storage import Database, Repository

PREFIX = "/api/v1"


@pytest.fixture()
def repository() -> Iterator[Repository]:
    repo = Repository(Database(":memory:"))
    yield repo
    repo.close()


def build_app(repository: Repository) -> Any:
    app = create_app()
    app.dependency_overrides[get_repository] = lambda: repository
    return app


def test_health_is_public() -> None:
    app = create_app()
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_stats_summary_reports_row_counts(repository: Repository) -> None:
    app = build_app(repository)
    with TestClient(app) as client:
        response = client.get(f"{PREFIX}/stats/summary")
    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {
        "products",
        "price_points",
        "price_changes",
        "search_events",
    }
    assert payload["products"] == 0
