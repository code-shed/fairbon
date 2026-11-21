"""Tests for the smart basket optimiser."""

from __future__ import annotations

from collections.abc import Iterable

import pytest

from supermarket_comparison.models import NormalizedProduct
from supermarket_comparison.scrapers.base import BaseScraper
from supermarket_comparison.services.aggregator import Aggregator
from supermarket_comparison.services.validity import classify


def offer(
    store: str,
    name: str,
    price: float,
    *,
    quantity: float = 1.0,
    unit: str = "stueck",
    unit_price: float | None = None,
    valid_to: str | None = None,
) -> NormalizedProduct:
    return NormalizedProduct(
        id=f"{store}-{name}-{price}",
        store=store,
        name=name,
        price=price,
        quantity=quantity,
        unit=unit,
        unit_price=unit_price,
        valid_to=valid_to,
    )


class CatalogScraper(BaseScraper):
    """Returns the catalogue; the aggregator filters by query."""

    def __init__(self, store: str, offers: Iterable[NormalizedProduct]) -> None:
        super().__init__()
        self.store = store
        self._offers = list(offers)

    async def fetch_offers(self, *, postal_code=None, query=None, ean=None):
        return list(self._offers)


def build_catalog() -> list[CatalogScraper]:
    lidl = CatalogScraper(
        "lidl",
        [
            offer("lidl", "Butter", 1.49, quantity=0.25, unit="kg"),
            offer("lidl", "Milch", 0.99, quantity=1.0, unit="l"),
            offer("lidl", "Nutella", 2.49),
            offer("lidl", "Kaffee", 5.99),
        ],
    )
    rewe = CatalogScraper(
        "rewe",
        [
            offer("rewe", "Butter", 1.39, quantity=0.25, unit="kg"),
            offer("rewe", "Milch", 1.09, quantity=1.0, unit="l"),
            offer("rewe", "Nutella", 2.29),
        ],
    )
    edeka = CatalogScraper(
        "edeka",
        [
            offer("edeka", "Butter", 1.59, quantity=0.25, unit="kg"),
            offer("edeka", "Milch", 0.89, quantity=1.0, unit="l"),
            offer("edeka", "Nutella", 2.59),
        ],
    )
    return [lidl, rewe, edeka]


@pytest.fixture
def aggregator() -> Aggregator:
    return Aggregator(build_catalog())


@pytest.mark.asyncio
async def test_option_a_picks_global_cheapest_per_item(
    aggregator: Aggregator,
) -> None:
    plan = await aggregator.optimize_basket(
        items=["Butter", "Milch", "Nutella", "Kaffee"],
        postal_code="65618",
        max_stores=2,
    )

    assert plan.unmatched == []
    assert [item.status for item in plan.items] == ["matched"] * 4
    assert plan.option_a.covers_all is True
    assert plan.option_a.total == pytest.approx(10.56)
    assert plan.option_a.merchants == 3

    picks = {
        line.item: (line.store, line.product.price)
        for group in plan.option_a.stores
        for line in group.lines
    }
    assert picks == {
        "Butter": ("rewe", 1.39),
        "Milch": ("edeka", 0.89),
        "Nutella": ("rewe", 2.29),
        "Kaffee": ("lidl", 5.99),
    }

    await aggregator.aclose()


@pytest.mark.asyncio
async def test_option_b_respects_max_stores_and_covers_everything(
    aggregator: Aggregator,
) -> None:
    plan = await aggregator.optimize_basket(
        items=["Butter", "Milch", "Nutella", "Kaffee"],
        postal_code="65618",
        max_stores=2,
    )

    assert plan.option_b.covers_all is True
    assert plan.option_b.missing_items == []
    assert len(plan.option_b.stores) <= 2
    assert plan.option_b.total == pytest.approx(10.66)
    assert {group.store for group in plan.option_b.stores} == {"lidl", "rewe"}
    assert plan.option_a.total <= plan.option_b.total

    await aggregator.aclose()


@pytest.mark.asyncio
async def test_savings_are_relative_to_the_best_single_store(
    aggregator: Aggregator,
) -> None:
    plan = await aggregator.optimize_basket(
        items=["Butter", "Milch", "Nutella", "Kaffee"],
        postal_code="65618",
        max_stores=2,
    )

    # A single Lidl covers all four items for 10.96 €.
    assert plan.option_a.baseline_total == pytest.approx(10.96)
    assert plan.option_a.baseline_partial is False
    assert plan.option_a.savings == pytest.approx(0.40)
    assert plan.option_b.savings == pytest.approx(0.30)
    assert plan.option_a.savings >= 0
    assert plan.option_b.savings >= 0

    await aggregator.aclose()


@pytest.mark.asyncio
async def test_missing_items_and_coverage_fallback() -> None:
    rewe = CatalogScraper("rewe", [offer("rewe", "Butter", 1.39)])
    edeka = CatalogScraper("edeka", [offer("edeka", "Kaffee", 5.49)])
    aggregator = Aggregator([rewe, edeka])

    plan = await aggregator.optimize_basket(
        items=["Butter", "Kaffee"],
        postal_code="65618",
        max_stores=1,
    )

    assert plan.option_b.covers_all is False
    assert len(plan.option_b.missing_items) == 1
    assert len(plan.option_b.stores) == 1

    await aggregator.aclose()


@pytest.mark.asyncio
async def test_unmatched_items_are_reported() -> None:
    lidl = CatalogScraper("lidl", [offer("lidl", "Butter", 1.49)])
    aggregator = Aggregator([lidl])

    plan = await aggregator.optimize_basket(
        items=["Butter", "Kaffee"],
        postal_code="65618",
    )

    assert plan.unmatched == ["Kaffee"]
    statuses = {item.query: item.status for item in plan.items}
    assert statuses == {"Butter": "matched", "Kaffee": "unmatched"}
    assert "Kaffee" not in {
        line.item for group in plan.option_a.stores for line in group.lines
    }

    await aggregator.aclose()


@pytest.mark.asyncio
async def test_unit_prices_are_only_compared_within_the_same_family() -> None:
    # Same store: 1 kg at 2.00 €/kg (2.00 €) vs 500 g at 3.60 €/kg (1.80 €).
    # The cheaper unit price wins even though its absolute price is higher.
    lidl = CatalogScraper(
        "lidl",
        [
            offer("lidl", "Butter 1 kg", 2.00, quantity=1.0, unit="kg"),
            offer("lidl", "Butter 500 g", 1.80, quantity=0.5, unit="kg"),
        ],
    )
    aggregator = Aggregator([lidl])

    plan = await aggregator.optimize_basket(items=["Butter"], postal_code="65618")

    line = plan.option_a.stores[0].lines[0]
    assert line.product.name == "Butter 1 kg"
    assert line.product.unit_price == pytest.approx(2.00)

    await aggregator.aclose()


@pytest.mark.asyncio
async def test_cross_family_comparison_falls_back_to_price() -> None:
    lidl = CatalogScraper(
        "lidl",
        [
            offer("lidl", "Butter Stück", 2.00, unit="stueck"),
            offer("lidl", "Butter Kilo", 3.00, quantity=1.0, unit="kg"),
        ],
    )
    aggregator = Aggregator([lidl])

    plan = await aggregator.optimize_basket(items=["Butter"], postal_code="65618")
    line = plan.option_a.stores[0].lines[0]

    assert line.product.name == "Butter Stück"
    assert line.product.price == pytest.approx(2.00)

    await aggregator.aclose()


@pytest.mark.asyncio
async def test_today_only_filters_expired_offers() -> None:
    expired = classify("2020-01-01T00:00:00Z", "2020-01-02T00:00:00Z")
    assert expired.state == "expired"

    lidl = CatalogScraper(
        "lidl",
        [
            offer(
                "lidl",
                "Butter",
                1.49,
                quantity=0.25,
                unit="kg",
                valid_to="2020-01-02T22:59:59Z",
            )
        ],
    )
    aggregator = Aggregator([lidl])

    all_offers = await aggregator.optimize_basket(
        items=["Butter"], postal_code="65618", today_only=False
    )
    today_only = await aggregator.optimize_basket(
        items=["Butter"], postal_code="65618", today_only=True
    )

    assert all_offers.unmatched == []
    assert today_only.unmatched == ["Butter"]

    await aggregator.aclose()


@pytest.mark.asyncio
async def test_money_is_rounded_to_two_decimals() -> None:
    lidl = CatalogScraper(
        "lidl",
        [offer("lidl", "Butter", 1.005), offer("lidl", "Milch", 0.995)],
    )
    aggregator = Aggregator([lidl])

    plan = await aggregator.optimize_basket(items=["Butter", "Milch"])

    assert plan.option_a.total == round(plan.option_a.total, 2)
    assert plan.option_b.total == round(plan.option_b.total, 2)
    for group in plan.option_a.stores:
        assert group.subtotal == round(group.subtotal, 2)

    await aggregator.aclose()


@pytest.mark.asyncio
async def test_empty_candidate_set_is_handled() -> None:
    aggregator = Aggregator([CatalogScraper("lidl", [])])

    plan = await aggregator.optimize_basket(items=["Butter"])

    assert plan.option_a.total == 0
    assert plan.option_b.total == 0
    assert plan.unmatched == ["Butter"]

    await aggregator.aclose()


@pytest.mark.asyncio
async def test_partial_single_store_baseline_is_flagged() -> None:
    # No single store covers all three items: Rewe has two, Edeka only noodles.
    rewe = CatalogScraper(
        "rewe",
        [offer("rewe", "Butter", 1.39), offer("rewe", "Nutella", 2.29)],
    )
    edeka = CatalogScraper("edeka", [offer("edeka", "Nudeln", 1.49)])
    aggregator = Aggregator([rewe, edeka])

    plan = await aggregator.optimize_basket(
        items=["Butter", "Nutella", "Nudeln"],
        postal_code="65618",
        max_stores=2,
    )

    assert plan.option_a.covers_all is True
    assert plan.option_a.total == pytest.approx(5.17)
    # A partial single-store sum (Rewe covers only 2 of 3 items) is not a valid
    # comparison baseline, so it must not be reported at all.
    assert plan.option_a.baseline_total is None
    assert plan.option_a.baseline_partial is True
    assert plan.option_a.savings == 0.0
    assert plan.option_b.baseline_partial is True
    assert plan.option_b.savings == 0.0

    await aggregator.aclose()
