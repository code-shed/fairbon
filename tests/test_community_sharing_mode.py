"""Hosted give-and-take mode (REQUIRE_COMMUNITY_SHARING)."""

from __future__ import annotations

import json
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from supermarket_comparison.api.main import create_app
from supermarket_comparison.api.routes.history import get_repository
from supermarket_comparison.config import get_settings
from supermarket_comparison.storage import Database, Repository

PREFIX = "/api/v1"
OWNER = "sharing-owner-token-1234"


@pytest.fixture()
def repository() -> Iterator[Repository]:
    repo = Repository(Database(":memory:"))
    yield repo
    repo.close()


@pytest.fixture()
def client(repository: Repository) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[get_repository] = lambda: repository
    with TestClient(app, headers={"X-Owner-Token": OWNER}) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _items() -> str:
    return json.dumps(
        [
            {
                "raw_text": name,
                "normalized_name": name,
                "category": category,
                "quantity": 1.0,
                "unit": "stueck",
                "price_cents": 199,
                "is_private": private,
            }
            for name, category, private in (
                ("Brot", "Lebensmittel", False),
                ("Wasser", "Getränke", True),
                ("Shampoo", "Drogerie", False),
                ("Spüli", "Haushalt", True),
                ("Brötchen", "Bäcker/Gastronomie", False),
            )
        ]
    )


def _payload(**extra: object) -> dict[str, object]:
    return {
        "store": "REWE",
        "postal_code": "65618",
        "currency": "EUR",
        "receipt_date": "2026-11-22",
        "total_cents": 5 * 199,
        "items_json": _items(),
        **extra,
    }


def test_require_sharing_auto_enables_and_ignores_is_private(
    client: TestClient, repository: Repository
) -> None:
    object.__setattr__(get_settings(), "require_community_sharing", True)

    response = client.post(f"{PREFIX}/receipts", data=_payload())

    assert response.status_code == 200
    assert response.json()["shared_count"] == 4
    names = {
        row["name"] for row in repository.db.query("SELECT name FROM community_prices")
    }
    assert names == {"Brot", "Wasser", "Shampoo", "Spüli"}
    # is_private remains in the private household book for the tax export.
    items = repository.user_receipt_items_for(response.json()["receipt_id"])
    assert sum(int(item["is_private"]) for item in items) == 2


def test_byok_keeps_opt_in(client: TestClient, repository: Repository) -> None:
    object.__setattr__(get_settings(), "require_community_sharing", True)

    response = client.post(
        f"{PREFIX}/receipts",
        data=_payload(),
        headers={"X-User-Vision-Key": "my-own-key"},
    )

    assert response.status_code == 200
    assert response.json()["shared_count"] == 0
    assert repository.db.query("SELECT id FROM community_prices") == []


def test_self_hosted_default_requires_opt_in(
    client: TestClient, repository: Repository
) -> None:
    object.__setattr__(get_settings(), "require_community_sharing", False)

    response = client.post(f"{PREFIX}/receipts", data=_payload())

    assert response.json()["shared_count"] == 0
    opted = client.post(
        f"{PREFIX}/receipts", data=_payload(share_anonymized="true")
    )
    # Self-hosters keep the old opt-in flow, including is_private exclusion.
    assert opted.json()["shared_count"] == 2
    # Without the hosted flag, is_private still excludes private lines.
    shared = {
        row["name"] for row in repository.db.query("SELECT name FROM community_prices")
    }
    assert shared == {"Brot", "Shampoo"}


def test_demo_receipt_is_never_shared(client: TestClient) -> None:
    object.__setattr__(get_settings(), "require_community_sharing", True)

    response = client.post(f"{PREFIX}/receipts", data=_payload(is_demo="true"))

    assert response.json()["shared_count"] == 0


def test_health_exposes_the_flag(client: TestClient) -> None:
    object.__setattr__(get_settings(), "require_community_sharing", True)
    assert client.get("/health").json()["require_community_sharing"] is True
    object.__setattr__(get_settings(), "require_community_sharing", False)
    assert client.get("/health").json()["require_community_sharing"] is False
