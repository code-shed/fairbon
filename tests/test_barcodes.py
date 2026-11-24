"""Barcode lookup, 1-to-N aliases and the link-barcode endpoint."""

from __future__ import annotations

from collections.abc import Iterator

import httpx
import pytest
from fastapi.testclient import TestClient

from supermarket_comparison.api.main import create_app
from supermarket_comparison.api.routes.history import get_repository
from supermarket_comparison.storage import Database, Repository

PREFIX = "/api/v1"
OWNER = "barcode-owner-token-1234"


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


def _receipt(repository: Repository, *, shared: bool = False) -> tuple[int, int]:
    receipt_id = repository.insert_user_receipt(
        owner_token=OWNER,
        store="rewe",
        postal_code="65618",
        country_code="DE",
        currency="EUR",
        receipt_date="2026-11-22",
        total_cents=399,
        shared_to_community=shared,
        items=[
            {
                "raw_text": "RITTER SPORT 100G",
                "normalized_name": "Ritter Sport",
                "category": "Lebensmittel",
                "quantity": 1.0,
                "unit": "stueck",
                "price_cents": 399,
            }
        ],
    )
    items = repository.user_receipt_items_for(receipt_id)
    return receipt_id, int(items[0]["id"])


def test_alias_variants_are_not_overwritten(repository: Repository) -> None:
    for ean in ("4000400011111", "4000400022222"):
        repository.upsert_alias(
            store="rewe",
            raw_text_norm="ritter sport 100g",
            normalized_name="Ritter Sport",
            brand=None,
            category="Lebensmittel",
            quantity=1.0,
            unit="stueck",
            ean=ean,
        )

    alias = repository.db.query_one(
        "SELECT * FROM receipt_aliases WHERE store = 'rewe'"
    )
    codes = {
        row["ean"]
        for row in repository.db.query("SELECT ean FROM alias_barcodes")
    }
    assert alias["ean"] in codes
    assert codes == {"4000400011111", "4000400022222"}
    assert alias["variant_group"]
    assert alias["hit_count"] == 2

    # Collective receipt terms are flagged as ambiguous for the scan UI.
    repository.upsert_alias(
        store="rewe",
        raw_text_norm="backwaren",
        normalized_name="Backwaren",
        brand=None,
        category="Bäcker/Gastronomie",
        quantity=None,
        unit=None,
    )
    flagged = repository.db.query_one(
        "SELECT is_ambiguous FROM receipt_aliases WHERE raw_text_norm = 'backwaren'"
    )
    assert flagged["is_ambiguous"] == 1


def test_link_barcode_uses_open_food_facts(
    client: TestClient, repository: Repository
) -> None:
    from supermarket_comparison.services import barcode

    _, item_id = _receipt(repository)
    payload = {"ean": "4000400011111"}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "product": {
                    "product_name": "Ritter Sport 100g",
                    "brands": "Ritter Sport",
                    "product_quantity": 100,
                    "product_quantity_unit": "g",
                }
            },
        )

    mock = httpx.MockTransport(handler)
    original = barcode.httpx.AsyncClient
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(
        barcode.httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=mock),
    )
    try:
        response = client.post(
            f"{PREFIX}/receipts/items/{item_id}/link-barcode",
            json=payload,
        )
    finally:
        monkeypatch.undo()

    assert response.status_code == 200
    body = response.json()
    assert body["ean"] == "4000400011111"
    assert body["brand"] == "Ritter Sport"



def test_barcode_preview_does_not_modify_the_item(
    client: TestClient, repository: Repository, monkeypatch: pytest.MonkeyPatch
) -> None:
    from supermarket_comparison.services import barcode

    _, item_id = _receipt(repository)

    async def fake_lookup(ean: str) -> dict[str, object]:
        return {"name": "Ritter Sport 100g", "brand": "Ritter Sport",
                "quantity": 100.0, "unit": "g"}

    monkeypatch.setattr(barcode, "lookup_barcode", fake_lookup)

    response = client.post(
        f"{PREFIX}/receipts/items/{item_id}/link-barcode?preview=true",
        json={"ean": "4000400011111"},
    )

    assert response.status_code == 200
    assert response.json()["name"] == "Ritter Sport 100g"
    item = repository.item_for_owner(item_id=item_id, owner_token=OWNER)
    assert item["ean"] is None
