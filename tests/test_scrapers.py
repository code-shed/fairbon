"""Tests for the remaining HTTP client (Open Food Facts Open Prices).

Fixtures mirror the verified live payload of
``GET https://prices.openfoodfacts.org/api/v1/prices?product_code=...``.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from supermarket_comparison.scrapers import (
    BaseScraper,
    OpenFoodFactsScraper,
    slugify,
)
from supermarket_comparison.scrapers.base import make_branch, make_product

# ---------------------------------------------------------------------------
# Open Prices fixture (real response shape)
# ---------------------------------------------------------------------------

OPEN_PRICES: dict[str, Any] = {
    "items": [
        {
            "id": 77,
            "product_code": "4012345678901",
            "product_name": "Bio Vollmilch",
            "price": 1.29,
            "price_per_unit": None,
            "currency": "EUR",
            "date": "2026-11-01",
            "location_id": 7820,
            "location": {
                "osm_name": "Spar",
                "osm_address_postcode": "10115",
                "osm_address_city": "Berlin",
            },
            "product": {
                "code": "4012345678901",
                "product_name": "Bio Vollmilch",
                "brands": "Weihenstephan",
                "product_quantity": 1000,
                "product_quantity_unit": "g",
                "categories_tags": ["en:dairies", "en:milks"],
                "image_url": "https://img.example/off.jpg",
            },
        },
    ],
    "page": 1,
    "pages": 1,
    "size": 20,
    "total": 1,
}


def _client(handler: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


class DummyScraper(BaseScraper):
    store = "dummy"

    async def fetch_offers(self, *, postal_code=None, query=None, ean=None):
        return []


# ---------------------------------------------------------------------------
# Base plumbing
# ---------------------------------------------------------------------------


def test_scraper_exposes_store_identifier() -> None:
    assert OpenFoodFactsScraper.store == "openfoodfacts"
    assert OpenFoodFactsScraper.base_url.startswith("https://")


def test_base_scraper_is_abstract() -> None:
    with pytest.raises(TypeError):
        BaseScraper()  # type: ignore[abstract]


@pytest.mark.asyncio
async def test_get_json_with_injected_client() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://example.org/api"
        return httpx.Response(200, json={"ok": True})

    async with _client(handler) as client:
        scraper = DummyScraper(client=client)
        assert await scraper.get_json("https://example.org/api") == {"ok": True}
        await scraper.aclose()

        # An injected client is owned by the caller and must stay open.
        assert client.is_closed is False


@pytest.mark.asyncio
async def test_context_manager_closes_owned_client() -> None:
    scraper = DummyScraper()
    client = scraper.client

    async with scraper:
        assert client.is_closed is False

    assert client.is_closed is True


@pytest.mark.asyncio
async def test_http_errors_propagate() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": "unavailable"})

    async with _client(handler) as client:
        scraper = DummyScraper(client=client)
        with pytest.raises(httpx.HTTPStatusError):
            await scraper.get_json("https://example.org/api")


def test_parse_helpers_reject_incomplete_records() -> None:
    assert make_product("lidl", {"name": "Ohne Preis", "price": None}) is None
    assert make_product("lidl", {"title": "", "price": 1.0}) is None
    assert make_branch("lidl", {"name": "Ohne Adresse"}) is None


def test_slugify() -> None:
    assert slugify("ALDI SÜD") == "aldi-sued"
    assert slugify("Netto Marken-Discount") == "netto-marken-discount"
    assert slugify("  ") == ""


# ---------------------------------------------------------------------------
# Open Food Facts
# ---------------------------------------------------------------------------


class TestOpenFoodFactsScraper:
    @pytest.mark.asyncio
    async def test_ean_lookup_maps_the_real_payload(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert "product_code=4012345678901" in str(request.url)
            return httpx.Response(200, json=OPEN_PRICES)

        async with _client(handler) as client:
            scraper = OpenFoodFactsScraper(client=client)
            products = await scraper.fetch_offers(ean="4012345678901")

        assert len(products) == 1
        product = products[0]
        assert product.ean == "4012345678901"
        assert product.name == "Bio Vollmilch"
        assert product.brand == "Weihenstephan"
        assert product.price == pytest.approx(1.29)
        assert product.quantity == pytest.approx(1.0)
        assert product.unit == "kg"
        assert product.image_url == "https://img.example/off.jpg"

    @pytest.mark.asyncio
    async def test_text_search_never_calls_open_prices(self) -> None:
        called = False

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal called
            called = True
            return httpx.Response(200, json={"items": []})

        async with _client(handler) as client:
            scraper = OpenFoodFactsScraper(client=client)
            products = await scraper.fetch_offers(query="Butter")

        assert products == []
        assert called is False

    @pytest.mark.asyncio
    async def test_ean_in_query_is_accepted(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"items": []})

        async with _client(handler) as client:
            scraper = OpenFoodFactsScraper(client=client)
            products = await scraper.fetch_offers(query="4012345678901")

        assert products == []

    @pytest.mark.asyncio
    async def test_empty_payload_returns_empty_list(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={})

        async with _client(handler) as client:
            scraper = OpenFoodFactsScraper(client=client)
            products = await scraper.fetch_offers(ean="4012345678901")

        assert products == []
