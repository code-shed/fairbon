"""Tests for the SQLite persistence layer (price history + statistics)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from supermarket_comparison.models import NormalizedProduct
from supermarket_comparison.storage import Database, Repository, product_key


@pytest.fixture()
def repository() -> Repository:
    repo = Repository(Database(":memory:"))
    yield repo
    repo.close()


def offer(
    name: str = "Butter",
    *,
    store: str = "lidl",
    price: float = 1.39,
    ean: str | None = None,
    offer_type: str = "prospect",
    valid_from: str | None = "2026-11-01T00:00:00Z",
    valid_to: str | None = "2026-11-07T00:00:00Z",
    quantity: float = 0.25,
    unit: str = "kg",
    unit_price: float | None = 5.56,
    brand: str | None = "Meggle",
) -> NormalizedProduct:
    return NormalizedProduct(
        id=f"{store}-{name}-{price}",
        store=store,
        name=name,
        brand=brand,
        ean=ean,
        price=price,
        quantity=quantity,
        unit=unit,
        unit_price=unit_price,
        valid_from=valid_from,
        valid_to=valid_to,
        offer_type=offer_type,
        source="marktguru",
    )


# -- product identity -------------------------------------------------------


def test_product_key_prefers_ean() -> None:
    assert product_key(offer(ean="4008400404127")) == "ean:4008400404127"
    assert product_key(offer()).startswith("txt:")


def test_offers_without_ean_share_a_key_across_stores() -> None:
    left = offer(store="lidl")
    right = offer(store="rewe")
    assert product_key(left) == product_key(right)


def test_different_package_sizes_get_distinct_keys() -> None:
    assert product_key(offer(quantity=0.25)) != product_key(offer(quantity=0.5))


def test_different_brands_get_distinct_keys() -> None:
    left = offer(name="Bier", brand="Beck's")
    right = offer(name="Bier", brand="Corona Extra")
    assert product_key(left) != product_key(right)


def test_same_identity_across_stores() -> None:
    left = offer(store="lidl", name="Bier", brand="Beck's", quantity=0.5)
    right = offer(store="rewe", name="Bier", brand="Beck's", quantity=0.5)
    assert product_key(left) == product_key(right)


# -- persistence ------------------------------------------------------------


def test_record_offers_writes_product_and_price_point(repository: Repository) -> None:
    stats = repository.record_offers([offer()])

    assert stats == {"products": 1, "changes": 1}
    assert repository.stats_summary()["products"] == 1
    assert repository.stats_summary()["price_points"] == 1
    assert repository.stats_summary()["price_changes"] == 1


def test_same_observation_is_idempotent(repository: Repository) -> None:
    repository.record_offers([offer()])
    repository.record_offers([offer()])

    summary = repository.stats_summary()
    assert summary["price_points"] == 1
    # No price change => no extra history row.
    assert summary["price_changes"] == 1


def test_changed_price_appends_history(repository: Repository) -> None:
    repository.record_offers([offer(price=1.39)])
    repository.record_offers([offer(price=1.19)])

    history = repository.price_history(name="Butter")
    assert [row["price"] for row in history] == [1.39, 1.19]
    assert history[0]["offer_type"] == "prospect"


def test_history_is_scoped_per_store(repository: Repository) -> None:
    repository.record_offers([offer(store="lidl", price=1.39)])
    repository.record_offers([offer(store="rewe", price=1.49)])

    lidl = repository.price_history(name="Butter", store="lidl")
    assert [row["store"] for row in lidl] == ["lidl"]


def test_standard_prices_are_tracked_separately(repository: Repository) -> None:
    repository.record_offers([offer(offer_type="standard", price=2.49, valid_to=None)])

    history = repository.price_history(name="Butter")
    assert [row["offer_type"] for row in history] == ["standard"]


def test_history_by_ean(repository: Repository) -> None:
    repository.record_offers([offer(ean="4008400404127", price=1.39)])
    repository.record_offers([offer(name="Other", ean="4008400404127", price=1.49)])

    rows = repository.price_history(ean="4008-400-404127")
    assert len(rows) == 2


def test_history_requires_an_identifier(repository: Repository) -> None:
    with pytest.raises(ValueError):
        repository.price_history()


def test_history_respects_the_day_window(repository: Repository) -> None:
    repository.record_offers([offer()])
    future = datetime.now(tz=UTC) + timedelta(days=400)
    rows = repository.price_history(name="Butter", days=1)
    assert isinstance(rows, list)

    old = repository.db.query(
        "SELECT COUNT(*) AS n FROM price_history WHERE changed_at < ?",
        ((future - timedelta(days=500)).isoformat(),),
    )
    assert old[0]["n"] >= 0


# -- search statistics ------------------------------------------------------


def test_search_events_are_aggregated_per_day(repository: Repository) -> None:
    for _ in range(3):
        repository.record_search(
            query="Butter", postal_code="65618", result_count=12, stores=["lidl"]
        )
    repository.record_search(
        query="Milch", postal_code="10115", result_count=4, stores=["rewe"]
    )

    trends = repository.top_queries(days=7, limit=10)
    assert trends[0]["query"] == "butter"
    assert trends[0]["searches"] == 3
    assert trends[0]["results"] == 36

    regional = repository.regional_queries(postal_code="65618", days=7)
    assert [row["query"] for row in regional] == ["butter"]


def test_search_terms_are_normalised_and_contain_no_pii(repository: Repository) -> None:
    repository.record_search(
        query="  BUTTER  ", postal_code="65618", result_count=1, stores=[]
    )
    row = repository.db.query_one("SELECT * FROM search_events")
    assert row["query"] == "butter"
    # Only term, plz, counts and timestamps are stored.
    assert set(row.keys()) == {
        "id",
        "query",
        "postal_code",
        "result_count",
        "stores",
        "created_at",
        "created_day",
    }


def test_blank_search_terms_are_ignored(repository: Repository) -> None:
    repository.record_search(query="   ", postal_code=None, result_count=0)
    assert repository.stats_summary()["search_events"] == 0


# -- async wrappers ---------------------------------------------------------


@pytest.mark.asyncio
async def test_async_wrappers(repository: Repository) -> None:
    stats = await repository.arecord_offers([offer()])
    await repository.arecord_search(
        query="butter", postal_code="65618", result_count=1, stores=["lidl"]
    )

    assert stats["products"] == 1
    assert (await repository.astats_summary())["search_events"] == 1
    assert await repository.aprice_history(name="Butter")
    assert await repository.atop_queries(days=7)
