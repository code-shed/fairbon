"""Integration tests for the history/statistics endpoints and the new flags."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from supermarket_comparison.api.deps import get_aggregator
from supermarket_comparison.api.main import create_app
from supermarket_comparison.api.routes.history import get_repository
from supermarket_comparison.models import (
    BasketItemResult,
    BasketOption,
    BasketPlan,
    NormalizedProduct,
    QuickFilter,
    RankedItem,
    RankedSearchResult,
    RelevanceInfo,
    ValidityInfo,
)
from supermarket_comparison.storage import Database, Repository


def milk(store: str = "lidl", price: float = 1.29) -> NormalizedProduct:
    return NormalizedProduct(
        id=f"{store}-1",
        store=store,
        name="Bio Vollmilch",
        brand="Weihenstephan",
        ean="4012345678901",
        price=price,
        quantity=1.0,
        unit="l",
    )


class RecordingAggregator:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def search(self, **kwargs: Any) -> list[NormalizedProduct]:
        self.calls.append(("search", kwargs))
        return [milk()]

    async def search_ranked(self, **kwargs: Any) -> RankedSearchResult:
        self.calls.append(("search_ranked", kwargs))
        product = milk()
        return RankedSearchResult(
            query=kwargs["query"],
            postal_code=kwargs.get("postal_code"),
            total_found=1,
            total_returned=1,
            items=[
                RankedItem(
                    product=product,
                    relevance=RelevanceInfo(
                        tier=3, score=1.0, matched_as="exact", matched_terms=["milch"]
                    ),
                    validity=ValidityInfo(state="today", label="Heute gültig"),
                )
            ],
            quick_filters=[QuickFilter(term="Buttermilch", count=1)],
            sources={"lidl": 1},
            errors={},
        )

    async def optimize_basket(self, **kwargs: Any) -> BasketPlan:
        self.calls.append(("optimize_basket", kwargs))
        option = BasketOption(
            label="Bester Split",
            stores=[],
            total=1.29,
            merchants=1,
            covers_all=True,
        )
        return BasketPlan(
            postal_code=kwargs.get("postal_code"),
            items=[
                BasketItemResult(query=item, status="matched")
                for item in kwargs["items"]
            ],
            option_a=option,
            option_b=option.model_copy(update={"label": "Max. 2 Märkte"}),
        )

    async def compare(
        self, **kwargs: Any
    ) -> list[NormalizedProduct]:  # pragma: no cover
        return [milk()]

    async def search_stores(self, **kwargs: Any) -> list[Any]:  # pragma: no cover
        return []

    def last_call(self, name: str) -> dict[str, Any]:
        for call_name, kwargs in reversed(self.calls):
            if call_name == name:
                return kwargs
        raise AssertionError(f"{name} was not called")


@pytest.fixture()
def repository() -> Iterator[Repository]:
    repo = Repository(Database(":memory:"))
    yield repo
    repo.close()


@pytest.fixture()
def client(repository: Repository) -> Iterator[TestClient]:
    app = create_app()
    recording = RecordingAggregator()
    app.dependency_overrides[get_aggregator] = lambda: recording
    app.dependency_overrides[get_repository] = lambda: repository
    app.state.recording = recording
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


# -- price history ----------------------------------------------------------


def test_history_requires_an_identifier(client: TestClient) -> None:
    assert client.get("/api/v1/products/history").status_code == 422


def test_history_is_empty_for_unknown_products(client: TestClient) -> None:
    response = client.get("/api/v1/products/history", params={"name": "Butter"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["points"] == []
    assert payload["count"] == 0
    assert payload["currency"] == "EUR"


def test_history_returns_recorded_changes(
    client: TestClient, repository: Repository
) -> None:
    repository.record_offers([milk(price=1.29)])
    repository.record_offers([milk(price=1.19)])

    response = client.get("/api/v1/products/history", params={"ean": "4012345678901"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 2
    assert payload["min"] == pytest.approx(1.19)
    assert payload["max"] == pytest.approx(1.29)
    assert [point["price"] for point in payload["points"]] == [1.29, 1.19]


# -- statistics -------------------------------------------------------------


def test_trends_are_aggregated_and_anonymised(
    client: TestClient, repository: Repository
) -> None:
    repository.record_search(
        query="Butter", postal_code="65618", result_count=3, stores=["lidl"]
    )

    response = client.get("/api/v1/stats/trends", params={"days": 7})

    assert response.status_code == 200
    payload = response.json()
    assert payload["items"][0]["query"] == "butter"
    assert payload["items"][0]["searches"] == 1
    assert "No IP addresses" in payload["privacy"]


def test_regional_trends_filter_by_postal_code(
    client: TestClient, repository: Repository
) -> None:
    repository.record_search(query="Bier", postal_code="65618", result_count=1)
    repository.record_search(query="Wein", postal_code="10115", result_count=1)

    response = client.get(
        "/api/v1/stats/trends", params={"postal_code": "65618", "days": 7}
    )

    assert response.status_code == 200
    assert [item["query"] for item in response.json()["items"]] == ["bier"]


def test_stats_summary_counts_rows(client: TestClient, repository: Repository) -> None:
    repository.record_offers([milk()])
    repository.record_search(query="milch", postal_code="65618", result_count=1)

    payload = client.get("/api/v1/stats/summary").json()

    assert payload["products"] == 1
    assert payload["price_points"] == 1
    assert payload["search_events"] == 1


# -- new query flags --------------------------------------------------------


def test_ranked_search_forwards_standard_price_flags(client: TestClient) -> None:
    client.get(
        "/api/v1/products/search/ranked",
        params={
            "query": "milch",
            "include_standard": "true",
            "offers_only": "true",
            "limit": 500,
        },
    )

    kwargs = client.app.state.recording.last_call("search_ranked")  # type: ignore[attr-defined]
    assert kwargs["include_standard"] is True
    assert kwargs["offers_only"] is True
    assert kwargs["limit"] == 500


def test_search_limit_accepts_large_pages(client: TestClient) -> None:
    response = client.get(
        "/api/v1/products/search", params={"query": "milch", "limit": 1000}
    )

    assert response.status_code == 200
    kwargs = client.app.state.recording.last_call("search")  # type: ignore[attr-defined]
    assert kwargs["limit"] == 1000


def test_search_limit_above_ceiling_is_rejected(client: TestClient) -> None:
    assert (
        client.get(
            "/api/v1/products/search", params={"query": "milch", "limit": 1001}
        ).status_code
        == 422
    )


def test_basket_forwards_include_standard(client: TestClient) -> None:
    response = client.post(
        "/api/v1/basket/optimize",
        json={"items": ["Milch"], "include_standard": True},
    )

    assert response.status_code == 200
    kwargs = client.app.state.recording.last_call("optimize_basket")  # type: ignore[attr-defined]
    assert kwargs["include_standard"] is True
