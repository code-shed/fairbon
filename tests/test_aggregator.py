"""Tests for the concurrent aggregator and its merge/compare pipeline."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable

from supermarket_comparison.models import NormalizedProduct, StoreBranch
from supermarket_comparison.scrapers.base import BaseScraper
from supermarket_comparison.services.aggregator import default_scrapers


def product(
    store: str,
    name: str,
    price: float,
    *,
    ean: str | None = None,
    quantity: float = 1.0,
    unit: str = "l",
) -> NormalizedProduct:
    return NormalizedProduct(
        id=f"{store}-{name}",
        store=store,
        name=name,
        price=price,
        ean=ean,
        quantity=quantity,
        unit=unit,
    )


def branch(store: str, branch_id: str, *, distance: float | None = None) -> StoreBranch:
    return StoreBranch(
        store=store,
        branch_id=branch_id,
        name=f"{store.title()} Berlin",
        address="Teststraße 1",
        postal_code="10115",
        city="Berlin",
        distance_km=distance,
    )


class FakeScraper(BaseScraper):
    def __init__(
        self,
        store: str,
        *,
        offers: Iterable[NormalizedProduct] | None = None,
        branches: Iterable[StoreBranch] | None = None,
        error: Exception | None = None,
    ) -> None:
        super().__init__()
        self.store = store
        self._offers = list(offers or [])
        self._branches = list(branches or [])
        self._error = error
        self.offers_calls: list[tuple[str | None, str | None, str | None]] = []

    async def fetch_offers(self, *, postal_code=None, query=None, ean=None):
        self.offers_calls.append((postal_code, query, ean))
        if self._error is not None:
            raise self._error
        return list(self._offers)

    async def fetch_stores(self, *, postal_code=None, limit=50):
        if self._error is not None:
            raise self._error
        return list(self._branches)


class BarrierScraper(BaseScraper):
    """Only returns offers when both scrapers run concurrently."""

    def __init__(self, store: str, offers: list[NormalizedProduct]) -> None:
        super().__init__()
        self.store = store
        self._offers = offers
        self.started = asyncio.Event()
        self.peer_started: asyncio.Event | None = None

    async def fetch_offers(self, *, postal_code=None, query=None, ean=None):
        self.started.set()
        assert self.peer_started is not None
        await asyncio.wait_for(self.peer_started.wait(), timeout=1.0)
        return list(self._offers)


class LegacyScraper(BaseScraper):
    """Implements only the original ``postal_code``/``query`` signature."""

    store = "legacy"

    async def fetch_offers(self, *, postal_code=None, query=None):
        return [product("legacy", "Bio Vollmilch", 1.39)]


def test_default_scrapers_cover_all_sources() -> None:
    scrapers = default_scrapers()

    assert [scraper.store for scraper in scrapers] == ["openfoodfacts"]



