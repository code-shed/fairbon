"""Community visibility must hold in search and the smart basket."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from supermarket_comparison.scrapers.base import BaseScraper
from supermarket_comparison.services.aggregator import Aggregator
from supermarket_comparison.storage import (
    CommunityPriceInput,
    Database,
    Repository,
)


class EmptyScraper(BaseScraper):
    """No leaflet offers — only the community feed contributes."""

    store = "lidl"

    async def fetch_offers(self, **kwargs: object) -> list:
        return []


@pytest.fixture()
def repository() -> Iterator[Repository]:
    repo = Repository(Database(":memory:"))
    yield repo
    repo.close()


def butter(price: float = 2.49) -> CommunityPriceInput:
    return CommunityPriceInput(
        name="Bio Butter 250g",
        store="lidl",
        price=price,
        postal_code="65618",
        quantity=0.25,
        unit="kg",
        scout_id="Scout-A",
    )


def milk(price: float = 999.99) -> CommunityPriceInput:
    return CommunityPriceInput(
        name="Milch",
        store="lidl",
        price=price,
        postal_code="65618",
        quantity=1.0,
        unit="l",
        scout_id="Scout-A",
    )


def build(repository: Repository) -> Aggregator:
    return Aggregator([EmptyScraper()], repository=repository)


@pytest.mark.asyncio
async def test_pending_price_never_reaches_search(repository: Repository) -> None:
    repository.community.add_price(butter())
    aggregator = build(repository)

    result = await aggregator.search_ranked(query="butter", postal_code="65618")

    assert [item for item in result.items if item.product.source == "community"] == []
    await aggregator.aclose()


@pytest.mark.asyncio
async def test_pending_review_price_is_ignored_by_basket(
    repository: Repository,
) -> None:
    repository.community.add_price(milk())
    aggregator = build(repository)

    plan = await aggregator.optimize_basket(
        items=["Milch"], postal_code="65618", include_standard=True
    )

    lines = [
        line
        for option in (plan.option_a, plan.option_b)
        for group in option.stores
        for line in group.lines
    ]
    assert all(line.product.source != "community" for line in lines)
    await aggregator.aclose()


@pytest.mark.asyncio
async def test_approved_price_reaches_search_and_basket(
    repository: Repository,
) -> None:
    created = repository.community.add_price(butter())
    repository.community.approve(created["id"], reviewer="admin")
    aggregator = build(repository)

    result = await aggregator.search_ranked(query="butter", postal_code="65618")
    products = [
        item.product for item in result.items if item.product.source == "community"
    ]
    assert products and products[0].price == pytest.approx(2.49)

    plan = await aggregator.optimize_basket(
        items=["Butter"], postal_code="65618", include_standard=True
    )
    total = plan.option_a.total
    assert total == pytest.approx(2.49)
    await aggregator.aclose()
