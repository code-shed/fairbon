"""Hardening tests from the code review (iteration 11, fix pass)."""

from __future__ import annotations

import base64
import math
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from supermarket_comparison.api.main import create_app
from supermarket_comparison.api.routes.history import get_repository
from supermarket_comparison.services.price_validator import (
    PriceContext,
    validate_price,
)
from supermarket_comparison.storage import (
    CommunityPriceInput,
    Database,
    Repository,
)


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


def coverage(client: TestClient) -> int:
    return client.get("/api/v1/crowd/coverage", params={"postal_code": "65618"}).json()[
        "observations"
    ]


# -- Critical 1: the category band must run for API submissions ------------


def test_band_outlier_without_unit_price_is_flagged(client: TestClient) -> None:
    payload = submit(client, name="Milch", price=150.0, unit="l", quantity=1.0)

    assert payload["price"]["status"] == "pending_review"
    assert "Band" in payload["price"]["review_reason"]


def test_grams_are_normalised_before_validation(client: TestClient) -> None:
    payload = submit(client, name="Butter", price=2.49, unit="g", quantity=250)

    assert payload["price"]["unit"] == "kg"
    assert payload["price"]["quantity"] == pytest.approx(0.25)
    assert payload["price"]["unit_price"] == pytest.approx(9.96)
    assert payload["price"]["status"] == "pending"


def test_unknown_unit_is_rejected(client: TestClient) -> None:
    response = client.post(
        "/api/v1/crowd/prices",
        json={
            "name": "Butter",
            "store": "lidl",
            "price": 2.49,
            "postal_code": "65618",
            "unit": "eimer",
            "quantity": 1,
        },
    )
    assert response.status_code == 422


# -- Critical 2: batch approval must re-validate ---------------------------


def test_batch_approval_revalidates_legacy_rows(repository: Repository) -> None:
    # Simulate a pre-v8 row that was inserted without validation.
    repository.db.execute(
        """
        INSERT INTO community_prices
            (id, identity, name, store, price, unit, quantity, unit_price,
             postal_code, scout_id, source, status, confirmations,
             created_at, updated_at)
        VALUES ('legacy', 'txt:milch|1l', 'Milch', 'lidl', 999.99, 'l',
                1.0, 999.99, '65618', 'S1', 'manual', 'pending', 1, 'x', 'x')
        """
    )

    approved = repository.community.approve_all_pending(reviewer="admin")

    row = repository.community.get_price("legacy")
    assert approved == 0
    assert row["status"] == "pending_review"
    assert row["review_reason"]


# -- Important 3: status=all lists both buckets ----------------------------


def test_review_all_lists_both_buckets(client: TestClient) -> None:
    submit(client)  # plausible, pending
    submit(client, name="Milch", price=999.99, unit="l", quantity=1.0)

    data = client.get("/api/v1/crowd/review", params={"status": "all"}).json()

    assert len(data["items"]) == 2
    assert {item["status"] for item in data["items"]} == {"pending", "pending_review"}


# -- Important 5: rejected stays rejected ----------------------------------


def test_approve_after_reject_returns_404(client: TestClient) -> None:
    price_id = submit(client)["price"]["id"]
    client.post(f"/api/v1/crowd/prices/{price_id}/reject", json={"reason": "Test"})

    response = client.post(f"/api/v1/crowd/prices/{price_id}/approve")

    assert response.status_code == 404
    assert coverage(client) == 0


# -- Important 6: the public list hides unapproved rows --------------------


def test_public_price_list_hides_pending_and_scout_ids(client: TestClient) -> None:
    submit(client, name="Butter", price=2.49)
    submit(client, name="Milch", price=999.99, unit="l", quantity=1.0)

    data = client.get("/api/v1/crowd/prices", params={"postal_code": "65618"}).json()

    assert data["submissions"] == []
    assert data["aggregated"] == []


# -- Important 12: pending_review is admin-only ----------------------------


def test_scouts_cannot_verify_a_flagged_price(repository: Repository) -> None:
    created = repository.community.add_price(
        CommunityPriceInput(
            name="Milch",
            store="lidl",
            price=999.99,
            postal_code="65618",
            quantity=1.0,
            unit="l",
            scout_id="A",
        )
    )
    assert created["status"] == "pending_review"

    for scout in ("B", "C", "D"):
        repository.community.confirm(created["id"], scout)

    assert repository.community.get_price(created["id"])["status"] == "pending_review"


def test_scouts_can_verify_a_plausible_price(repository: Repository) -> None:
    created = repository.community.add_price(
        CommunityPriceInput(
            name="Butter",
            store="lidl",
            price=2.49,
            postal_code="65618",
            quantity=0.25,
            unit="kg",
            scout_id="A",
        )
    )
    for scout in ("B", "C"):
        repository.community.confirm(created["id"], scout)

    assert repository.community.get_price(created["id"])["status"] == "verified"


# -- Important 10: NaN / Infinity -----------------------------------------


def test_nan_price_is_rejected_by_the_api(client: TestClient) -> None:
    response = client.post(
        "/api/v1/crowd/prices",
        content=(
            '{"name":"Milch","store":"lidl","price":NaN,'
            '"postal_code":"65618","unit":"l","quantity":1}'
        ),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422


def test_validator_rejects_non_finite_values() -> None:
    assert validate_price(PriceContext(name="Milch", price=math.nan)).status == (
        "pending_review"
    )
    assert validate_price(
        PriceContext(name="Milch", price=1.99, unit_price=math.inf, unit="l")
    ).status == ("pending_review")


# -- Important 9: confirmations are not double counted ---------------------


def test_confirmation_count_is_monotonic(repository: Repository) -> None:
    created = repository.community.add_price(
        CommunityPriceInput(
            name="Butter",
            store="lidl",
            price=2.49,
            postal_code="65618",
            quantity=0.25,
            unit="kg",
            scout_id="A",
        )
    )
    first = repository.community.confirm(created["id"], "B")
    second = repository.community.confirm(created["id"], "C")

    assert second["confirmations"] == first["confirmations"] + 1
