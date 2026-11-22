"""Tests for community prices, receipts and the crowdsourcing API."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from supermarket_comparison.api.main import create_app
from supermarket_comparison.api.routes.history import get_repository
from supermarket_comparison.services.receipts import (
    detect_postal_code,
    detect_store,
    parse_receipt_text,
)
from supermarket_comparison.storage import (
    VERIFY_THRESHOLD,
    CommunityPriceInput,
    Database,
    Repository,
    badges_for,
    identity_of,
    to_products,
)

SAMPLE_RECEIPT = """REWE Markt GmbH
Invalidenstr. 1
10115 Berlin
Tel. 030 123456

Datum 03.11.2026 18:42

BIO VOLLMILCH 1L        1,29 B
JA! BUTTER 250G         2,19 A
GUT & GÜNSTIG MEHL 1KG
  1,49
SPÜLMITTEL 500ML        1,99
BANANEN 1KG             1,99
4012345678901
SUMME EUR               8,95
EC-KARTE                8,95
"""


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


def price_input(**overrides: Any) -> CommunityPriceInput:
    data: dict[str, Any] = {
        "name": "JA! Butter 250g",
        "store": "rewe",
        "price": 2.19,
        "postal_code": "10115",
        "quantity": 0.25,
        "unit": "kg",
        "scout_id": "Scout-0001",
    }
    data.update(overrides)
    return CommunityPriceInput(**data)


# -- identity / aggregation -------------------------------------------------


def test_identity_prefers_ean() -> None:
    assert identity_of(ean="4012345678901", name="X", unit=None, quantity=None) == (
        "ean:4012345678901"
    )
    assert identity_of(ean=None, name="Butter", unit="kg", quantity=0.25).startswith(
        "txt:butter"
    )


def test_submissions_are_aggregated_by_median(repository: Repository) -> None:
    community = repository.community
    for value, scout in [(2.19, "A"), (1.99, "B"), (2.49, "C"), (9.99, "D")]:
        entry = community.add_price(price_input(price=value, scout_id=scout))
        # Strict mode: only confirmed prices are aggregated.
        community.approve(entry["id"], reviewer="test")

    aggregate = community.aggregate(
        identity=identity_of(
            ean=None, name="JA! Butter 250g", unit="kg", quantity=0.25
        ),
        store="rewe",
        postal_code="10115",
    )

    assert aggregate is not None
    assert aggregate["observations"] == 4
    # median of 1.99, 2.19, 2.49, 9.99 -> 2.34
    assert aggregate["median_price"] == pytest.approx(2.34)
    assert aggregate["min_price"] == pytest.approx(1.99)
    assert aggregate["max_price"] == pytest.approx(9.99)


def test_distinct_confirmations_verify_a_price(repository: Repository) -> None:
    community = repository.community
    entry = community.add_price(price_input(scout_id="A"))

    assert entry["status"] == "pending"
    for scout in ["B", "C"]:
        entry = community.confirm(entry["id"], scout)

    assert entry["status"] == "verified"
    assert entry["confirmations"] == VERIFY_THRESHOLD

    # A repeated confirmation from the same scout is ignored.
    again = community.confirm(entry["id"], "C")
    assert again["confirmations"] == VERIFY_THRESHOLD


def test_coverage_labels(repository: Repository) -> None:
    community = repository.community
    assert community.coverage("10115")["level"] == "keine Daten"

    entry = community.add_price(price_input(scout_id="A"))
    assert community.coverage("10115")["observations"] == 0  # hidden until approved
    community.approve(entry["id"], reviewer="test")
    coverage = community.coverage("10115")
    assert coverage["observations"] == 1
    assert community.coverage("10115")["level"] == "im Aufbau"

    for index in range(9):
        added = community.add_price(price_input(name=f"Artikel {index}", scout_id="A"))
        community.approve(added["id"], reviewer="test")
    assert community.coverage("10115")["level"] == "aktiv"


def test_scout_stats_and_badges(repository: Repository) -> None:
    community = repository.community
    for index in range(5):
        community.add_price(price_input(name=f"Artikel {index}", scout_id="Scout-42"))

    stats = community.scout_stats("Scout-42")
    assert stats["contributions"] == 5
    badge_ids = [badge["id"] for badge in stats["badges"]]
    assert "first-price" in badge_ids
    assert "neighbourhood" in badge_ids


def test_community_products_are_standard_prices(repository: Repository) -> None:
    community = repository.community
    created = community.add_price(price_input())
    community.approve(created["id"], reviewer="test")

    aggregated = community.aggregated_for_query(query="butter", postal_code="10115")
    products = to_products(aggregated)

    assert len(products) == 1
    assert products[0].offer_type == "standard"
    assert products[0].source == "community"
    assert products[0].price == pytest.approx(2.19)
    assert products[0].postal_code == "10115"


# -- receipt parsing --------------------------------------------------------


def test_receipt_metadata_is_detected() -> None:
    parsed = parse_receipt_text(SAMPLE_RECEIPT)

    assert parsed.store == "rewe"
    assert parsed.postal_code == "10115"
    assert parsed.total == pytest.approx(8.95)


def test_receipt_items_are_extracted() -> None:
    parsed = parse_receipt_text(SAMPLE_RECEIPT)
    names = [item.name for item in parsed.items]

    assert "BIO VOLLMILCH 1L" in names
    assert "JA! BUTTER 250G" in names
    assert "GUT & GÜNSTIG MEHL 1KG" in names
    assert "BANANEN 1KG" in names
    # Totals and payment lines are never products.
    assert not any("SUMME" in name.upper() for name in names)
    assert not any("EC-KARTE" in name.upper() for name in names)


def test_receipt_parses_units_and_ean() -> None:
    parsed = parse_receipt_text(SAMPLE_RECEIPT)
    by_name = {item.name: item for item in parsed.items}

    milk = by_name["BIO VOLLMILCH 1L"]
    assert milk.unit == "l"
    assert milk.quantity == pytest.approx(1.0)
    assert milk.unit_price == pytest.approx(1.29)

    bananas = by_name["BANANEN 1KG"]
    assert bananas.ean == "4012345678901"


def test_receipt_follows_the_price_on_the_next_line() -> None:
    parsed = parse_receipt_text(SAMPLE_RECEIPT)
    flour = {item.name: item for item in parsed.items}["GUT & GÜNSTIG MEHL 1KG"]
    assert flour.price == pytest.approx(1.49)


def test_detect_store_and_postcode_helpers() -> None:
    assert detect_store("LIDL SAGT DANKE") == "lidl"
    assert detect_store("Edeka Center") == "edeka"
    assert detect_postal_code("Beispielweg 3\n65618 Münster") == "65618"


def test_empty_receipt_reports_a_warning() -> None:
    parsed = parse_receipt_text("nur header\nkeine preise")
    assert parsed.items == []
    assert parsed.warnings


def test_badges_for_helper() -> None:
    assert badges_for(0, 0) == []
    assert [b["id"] for b in badges_for(1, 0)] == ["first-price"]
    assert "receipt-scout" in [b["id"] for b in badges_for(1, 1)]
    assert "local-hero" in [b["id"] for b in badges_for(20, 0)]


# -- API --------------------------------------------------------------------


def test_submit_price_returns_median(client: TestClient) -> None:
    payload = {
        "name": "JA! Butter 250g",
        "store": "rewe",
        "price": 2.19,
        "postal_code": "10115",
        "scout_id": "Scout-0001",
    }
    first = client.post("/api/v1/crowd/prices", json=payload)
    assert first.status_code == 201
    # Strict mode: a fresh report is not aggregated until it is approved.
    assert first.json()["price"]["status"] == "pending"
    assert first.json()["aggregate"] is None

    payload["price"] = 1.79
    payload["scout_id"] = "Scout-0002"
    second = client.post("/api/v1/crowd/prices", json=payload)
    assert second.status_code == 201
    assert second.json()["aggregate"] is None


def test_submit_price_validates_input(client: TestClient) -> None:
    invalid = [
        {"name": "x", "store": "rewe", "price": 1.0, "postal_code": "10115"},
        {"name": "Butter", "store": "rewe", "price": -1, "postal_code": "10115"},
        {"name": "Butter", "store": "rewe", "price": 1.0, "postal_code": "1"},
        {"name": "Butter", "store": "REWE Markt", "price": 1.0, "postal_code": "10115"},
    ]
    for body in invalid:
        assert client.post("/api/v1/crowd/prices", json=body).status_code == 422


def test_confirm_endpoint_verifies(client: TestClient) -> None:
    created = client.post(
        "/api/v1/crowd/prices",
        json={
            "name": "Butter",
            "store": "lidl",
            "price": 1.39,
            "postal_code": "65618",
            "scout_id": "A",
        },
    ).json()

    price_id = created["price"]["id"]
    for scout in ["B", "C"]:
        response = client.post(
            f"/api/v1/crowd/prices/{price_id}/confirm", json={"scout_id": scout}
        )
        assert response.status_code == 200

    assert response.json()["price"]["status"] == "verified"


def test_confirm_unknown_price_returns_404(client: TestClient) -> None:
    response = client.post(
        "/api/v1/crowd/prices/does-not-exist/confirm", json={"scout_id": "A"}
    )
    assert response.status_code == 404


def test_coverage_endpoint(client: TestClient) -> None:
    client.post(
        "/api/v1/crowd/prices",
        json={
            "name": "Butter",
            "store": "lidl",
            "price": 1.39,
            "postal_code": "65618",
            "scout_id": "A",
        },
    )

    response = client.get("/api/v1/crowd/coverage", params={"postal_code": "65618"})

    assert response.status_code == 200
    payload = response.json()
    # Strict mode: unapproved community prices are invisible.
    assert payload["observations"] == 0
    assert payload["level"] == "keine Daten"


def test_scout_endpoint(client: TestClient) -> None:
    client.post(
        "/api/v1/crowd/prices",
        json={
            "name": "Butter",
            "store": "lidl",
            "price": 1.39,
            "postal_code": "65618",
            "scout_id": "Scout-4812",
        },
    )

    payload = client.get("/api/v1/crowd/scouts/Scout-4812").json()

    assert payload["contributions"] == 1
    assert payload["badges"][0]["label"] == "Erster Preis"


def test_receipt_text_import(client: TestClient) -> None:
    response = client.post(
        "/api/v1/crowd/receipts/text",
        json={"text": SAMPLE_RECEIPT, "scout_id": "Scout-7"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["store"] == "rewe"
    assert payload["postal_code"] == "10115"
    assert payload["imported"] == len(payload["items"]) > 0
    # Imported prices are pending, so coverage stays at zero until approval.
    assert payload["coverage"]["observations"] == 0


def test_receipt_upload_as_text_file(client: TestClient) -> None:
    response = client.post(
        "/api/v1/crowd/upload-receipt",
        files={"file": ("bon.txt", SAMPLE_RECEIPT.encode("utf-8"), "text/plain")},
        data={"postal_code": "10115", "scout_id": "Scout-9"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["engine"] == "text"
    assert payload["imported"] > 0


def test_receipt_upload_rejects_unknown_types(client: TestClient) -> None:
    response = client.post(
        "/api/v1/crowd/upload-receipt",
        files={"file": ("bon.bin", b"\x00\x01", "application/octet-stream")},
    )
    assert response.status_code == 415


def test_receipt_upload_without_ocr_returns_503(client: TestClient) -> None:
    response = client.post(
        "/api/v1/crowd/upload-receipt",
        files={"file": ("bon.png", b"\x89PNG\r\n\x1a\n", "image/png")},
    )
    assert response.status_code == 503
    assert "OCR" in response.json()["detail"]


def test_community_search_includes_nearby_postal_codes() -> None:
    """Nearby PLZs (3-4 shared leading digits) keep local prices visible."""
    from supermarket_comparison.storage import CommunityPriceInput, Database, Repository

    repo = Repository(Database(":memory:"))
    for plz in ("65618", "65631", "12345"):
        repo.community.add_price(
            CommunityPriceInput(
                name="Fenchelsalami",
                store="penny",
                price=2.49,
                postal_code=plz,
                ean=None,
                unit="stueck",
                quantity=1.0,
                scout_id=None,
                source="receipt",
                receipt_id=None,
            ),
            auto_verify=True,
        )

    def found(plz: str) -> list[str]:
        entries = repo.community.aggregated_for_query(
            query="Fenchelsalami", postal_code=plz
        )
        return [entry["postal_code"] for entry in entries]

    # Exact match ranks first; the neighbouring 656xx rows still appear.
    assert found("65618") == ["65618", "65631"]
    assert found("65617") == ["65618", "65631"]
    assert found("65630") == ["65631", "65618"]
    # An unrelated region stays hidden (no 8k-entry geo table needed).
    assert found("12345") == ["12345"]
