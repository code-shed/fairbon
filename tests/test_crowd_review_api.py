"""Admin review queue endpoints."""

from __future__ import annotations

import base64
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


ADMIN_AUTH = {
    "Authorization": "Basic "
    + base64.b64encode(b"admin:test-admin-pw").decode()
}


@pytest.fixture()
def client(repository: Repository) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[get_repository] = lambda: repository
    with TestClient(app, headers=ADMIN_AUTH) as test_client:
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


def test_review_queue_lists_anomalies(client: TestClient) -> None:
    submit(client, name="Milch", price=999.99, unit="l", quantity=1.0)
    submit(client)

    queue = client.get(
        "/api/v1/crowd/review", params={"status": "pending_review"}
    ).json()

    assert queue["counts"] == {"pending": 1, "pending_review": 1}
    assert [item["name"] for item in queue["items"]] == ["Milch"]


def test_approve_makes_price_visible(client: TestClient) -> None:
    price_id = submit(client)["price"]["id"]

    response = client.post(f"/api/v1/crowd/prices/{price_id}/approve")

    assert response.status_code == 200
    assert response.json()["price"]["status"] == "approved"
    coverage = client.get(
        "/api/v1/crowd/coverage", params={"postal_code": "65618"}
    ).json()
    assert coverage["observations"] == 1


def test_reject_keeps_price_hidden(client: TestClient) -> None:
    price_id = submit(client)["price"]["id"]

    response = client.post(
        f"/api/v1/crowd/prices/{price_id}/reject", json={"reason": "Test"}
    )

    assert response.status_code == 200
    assert response.json()["price"]["status"] == "rejected"
    coverage = client.get(
        "/api/v1/crowd/coverage", params={"postal_code": "65618"}
    ).json()
    assert coverage["observations"] == 0


def test_approve_all_only_touches_pending(client: TestClient) -> None:
    submit(client)
    submit(client, name="Milch", price=999.99, unit="l", quantity=1.0)

    response = client.post("/api/v1/crowd/review/approve-all")

    assert response.status_code == 200
    assert response.json() == {"approved": 1}
    queue = client.get(
        "/api/v1/crowd/review", params={"status": "pending_review"}
    ).json()
    assert queue["counts"] == {"pending": 0, "pending_review": 1}


def test_unknown_price_returns_404(client: TestClient) -> None:
    assert client.post("/api/v1/crowd/prices/nope/approve").status_code == 404
    assert client.post("/api/v1/crowd/prices/nope/reject", json={}).status_code == 404
