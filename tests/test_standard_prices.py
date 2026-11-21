"""Tests for the standard-price provider (Open Food Facts + Open Prices).

The fixtures mirror verified live payloads:

* ``search.openfoodfacts.org/search`` hits
* ``prices.openfoodfacts.org/api/v1/prices`` items, including the
  ``location.osm_address_country_code`` / ``osm_address_postcode`` fields that
  make the German filter and the regional preference possible.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from supermarket_comparison.services.standard_prices import StandardPriceService

CATALOG_PAYLOAD: dict[str, Any] = {
    "count": 3,
    "hits": [
        {
            "code": "4008400404127",
            "product_name": "Milbona Butter",
            "brands": "Milbona",
            "quantity": "250 g",
            "categories_tags": ["en:dairies", "en:butters"],
            "image_url": "https://images.openfoodfacts.org/x.jpg",
        },
        {
            "code": "4062139000014",
            "product_name": "Balea Shampoo",
            "brands": "Balea",
            "quantity": "300 ml",
            "categories_tags": ["en:shampoos"],
        },
        {"code": None, "product_name": "Ohne EAN"},
    ],
}


def price_item(
    *,
    price_id: int,
    price: float,
    country: str = "DE",
    postcode: str = "65618",
    store: str = "Lidl",
    product_code: str = "4008400404127",
    name: str = "Milbona Butter",
    date: str = "2026-10-01",
    unit: str = "g",
    quantity: float = 250,
    name_ok: bool = True,
) -> dict[str, Any]:
    return {
        "id": price_id,
        "product_code": product_code,
        "price": price,
        "price_per_unit": None,
        "date": date,
        "location": {
            "osm_name": store,
            "osm_address_country_code": country,
            "osm_address_postcode": postcode,
        },
        "product": {
            "code": product_code,
            "product_name": name,
            "brands": "Milbona",
            "product_quantity": quantity,
            "product_quantity_unit": unit,
            "categories_tags": ["en:dairies"],
        },
    }


def make_service(handler: Any, **kwargs: Any) -> StandardPriceService:
    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(
        transport=transport, headers={"Accept": "application/json"}
    )
    return StandardPriceService(cache_ttl=0, client=client, **kwargs)


def route(request: httpx.Request) -> httpx.Response:
    if request.url.path.endswith("/search"):
        return httpx.Response(200, json=CATALOG_PAYLOAD)
    code = request.url.params.get("product_code")
    if code == "4008400404127":
        return httpx.Response(
            200,
            json={
                "items": [
                    price_item(price_id=1, price=2.49, postcode="24103"),
                    price_item(price_id=2, price=2.29, postcode="65618"),
                    price_item(price_id=3, price=1.99, country="BE", postcode="6791"),
                ]
            },
        )
    return httpx.Response(200, json={"items": []})


# -- catalogue --------------------------------------------------------------


@pytest.mark.asyncio
async def test_catalog_parses_hits_and_skips_missing_eans() -> None:
    service = make_service(route, limit=5)
    hits = await service.search_catalog("milbona")

    assert [hit.ean for hit in hits] == ["4008400404127", "4062139000014"]
    assert hits[0].brand == "Milbona"
    assert hits[0].quantity == pytest.approx(0.25)
    assert hits[0].unit == "kg"
    assert hits[0].category == "Dairies"
    await service.aclose()


# -- prices -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_only_german_observations_are_kept() -> None:
    service = make_service(route)
    offers = await service.prices_for_ean("4008400404127")

    assert len(offers) == 1
    assert offers[0].price == pytest.approx(2.29)  # the 65618 observation
    assert offers[0].store == "lidl"
    assert offers[0].offer_type == "standard"
    assert offers[0].source == "openprices"
    assert offers[0].postal_code == "65618"
    await service.aclose()


@pytest.mark.asyncio
async def test_local_region_is_preferred_over_other_german_shops() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "items": [
                    price_item(price_id=1, price=1.79, postcode="10115"),
                    price_item(price_id=2, price=2.49, postcode="65618"),
                ]
            },
        )

    service = make_service(handler)
    offers = await service.prices_for_ean("4008400404127", postal_code="65618")

    assert [offer.price for offer in offers] == [pytest.approx(2.49)]
    await service.aclose()


@pytest.mark.asyncio
async def test_newest_observation_wins_per_store() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "items": [
                    price_item(price_id=1, price=2.99, date="2025-01-01"),
                    price_item(price_id=2, price=2.49, date="2026-10-01"),
                ]
            },
        )

    service = make_service(handler)
    offers = await service.prices_for_ean("4008400404127")

    assert [offer.price for offer in offers] == [pytest.approx(2.49)]
    assert offers[0].id == "std-2"
    await service.aclose()


@pytest.mark.asyncio
async def test_catalog_hits_without_prices_are_dropped() -> None:
    service = make_service(route)
    offers = await service.search("milbona")

    # Balea has no price observation in the fixture => not returned at all.
    assert [offer.name for offer in offers] == ["Milbona Butter"]
    await service.aclose()


@pytest.mark.asyncio
async def test_unknown_ean_returns_nothing() -> None:
    service = make_service(route)
    assert await service.prices_for_ean("0000000000000") == []
    await service.aclose()


@pytest.mark.asyncio
async def test_empty_query_does_not_hit_the_network() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        calls.append(str(request.url))
        return httpx.Response(200, json={"hits": []})

    service = make_service(handler)
    assert await service.search("   ") == []
    assert calls == []
    await service.aclose()


@pytest.mark.asyncio
async def test_catalogue_is_cached() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, json=CATALOG_PAYLOAD)

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    service = StandardPriceService(cache_ttl=60, client=client, limit=3)

    await service.search_catalog("milbona")
    await service.search_catalog("milbona")
    assert len(calls) == 1
    await service.aclose()


@pytest.mark.asyncio
async def test_failed_price_lookup_does_not_break_the_result() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/search"):
            return httpx.Response(200, json=CATALOG_PAYLOAD)
        return httpx.Response(503, json={"error": "down"})

    service = make_service(handler)
    assert await service.search("milbona") == []
    await service.aclose()
