"""Receipt backup export/import (real data safety, unlike the access token)."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from supermarket_comparison.api.main import create_app
from supermarket_comparison.api.routes.history import get_repository
from supermarket_comparison.storage import Database, Repository

PREFIX = "/api/v1"
OWNER = "backup-owner-token-1234"


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


def test_backup_roundtrip(client: TestClient, repository: Repository) -> None:
    receipt_id = repository.insert_user_receipt(
        owner_token=OWNER,
        store="rewe",
        postal_code="65618",
        country_code="DE",
        currency="EUR",
        receipt_date="2026-11-22",
        total_cents=499,
        shared_to_community=False,
        is_business=True,
        items=[
            {
                "raw_text": "Nutella 1,99",
                "normalized_name": "Nutella",
                "category": "Lebensmittel",
                "quantity": 1.0,
                "unit": "stueck",
                "price_cents": 499,
                "vat_rate": 19.0,
            }
        ],
    )

    exported = client.get(f"{PREFIX}/receipts/backup").json()
    assert exported["version"] == 1
    assert len(exported["receipts"]) == 1
    assert exported["receipts"][0]["items"][0]["normalized_name"] == "Nutella"
    assert "owner_token" not in str(exported)

    # Simulate data loss and restore from the exported file.
    client.delete(f"{PREFIX}/receipts/{receipt_id}")
    assert client.get(f"{PREFIX}/receipts").json() == []

    result = client.post(f"{PREFIX}/receipts/backup/import", json=exported)
    assert result.status_code == 200
    assert result.json()["imported"] == 1

    restored = client.get(f"{PREFIX}/receipts").json()
    assert len(restored) == 1
    assert restored[0]["store"] == "rewe"
    assert restored[0]["is_business"] == 1
    assert restored[0]["items"][0]["normalized_name"] == "Nutella"


def test_backup_import_validates_and_stays_owner_scoped(client: TestClient) -> None:
    bad = client.post(
        f"{PREFIX}/receipts/backup/import",
        json={"version": 99, "receipts": []},
    )
    assert bad.status_code == 422

    payload = {
        "version": 1,
        "receipts": [
            {
                "store": "aldi",
                "postal_code": "65618",
                "receipt_date": "2026-11-22",
                "total_cents": 199,
                "items": [
                    {
                        "normalized_name": "Milch",
                        "category": "Getraenke",
                        "price_cents": 199,
                    }
                ],
            }
        ],
    }
    ok = client.post(f"{PREFIX}/receipts/backup/import", json=payload)
    assert ok.status_code == 200
    restored = client.get(f"{PREFIX}/receipts").json()
    assert restored[0]["store"] == "aldi"
    assert restored[0]["items"][0]["category"] == "Getränke"
