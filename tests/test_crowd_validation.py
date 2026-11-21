"""Submission paths run the validator and report the result."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from supermarket_comparison.api.main import create_app
from supermarket_comparison.api.routes.history import get_repository
from supermarket_comparison.storage import Database, Repository


@pytest.fixture()
def repository() -> Iterator[Repository]:
    repo = Repository(Database(":memory:"))
    yield repo
    repo.close()


@pytest.fixture()
def client(repository: Repository) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[get_repository] = lambda: repository
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def submit(client: TestClient, **overrides: object) -> dict:
    payload: dict[str, object] = {
        "name": "Butter",
        "store": "lidl",
        "price": 2.49,
        "postal_code": "65618",
        "quantity": 0.25,
        "unit": "kg",
        "scout_id": "Scout-A",
    }
    payload.update(overrides)
    return client.post("/api/v1/crowd/prices", json=payload).json()


def test_submission_reports_review_status(client: TestClient) -> None:
    payload = submit(client, name="Milch", price=999.99, unit="l", quantity=1.0)

    assert payload["price"]["status"] == "pending_review"
    assert payload["price"]["review_reason"]


def test_plausible_submission_is_pending_not_visible(client: TestClient) -> None:
    payload = submit(client)

    assert payload["price"]["status"] == "pending"
    assert payload["price"]["review_reason"] is None
    coverage = client.get(
        "/api/v1/crowd/coverage", params={"postal_code": "65618"}
    ).json()
    assert coverage["observations"] == 0


def test_receipt_import_isolates_bad_lines(client: TestClient) -> None:
    text = """LIDL
65618 Musterstadt
BUTTER 250G 2,49
MILCH 1L 999,99
SPAGHETTI 500G 0,99
SUMME 1003,47
"""
    result = client.post(
        "/api/v1/crowd/receipts/text", json={"text": text, "postal_code": "65618"}
    ).json()

    assert result["imported"] == 3
    assert result["pending_review"] == 1
    assert result["pending"] == 2


def test_receipt_import_reports_coverage_zero(client: TestClient) -> None:
    text = "REWE\n65618\nBUTTER 250G 2,49\nSUMME 2,49"
    result = client.post(
        "/api/v1/crowd/receipts/text", json={"text": text, "postal_code": "65618"}
    ).json()

    assert result["coverage"]["observations"] == 0
