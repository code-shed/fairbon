"""Integration tests for the FastAPI application using an injected aggregator."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from supermarket_comparison.api.deps import get_aggregator
from supermarket_comparison.api.main import create_app
from supermarket_comparison.models import (
    BasketItemResult,
    BasketOption,
    BasketPlan,
    NormalizedProduct,
    QuickFilter,
    RankedItem,
    RankedSearchResult,
    RelevanceInfo,
    StoreBranch,
    ValidityInfo,
)


def milk_product(store: str = "lidl", price: float = 1.29) -> NormalizedProduct:
    return NormalizedProduct(
        id=f"{store}-1",
        store=store,
        name="Bio Vollmilch",
        brand="Weihenstephan",
        ean="4012345678901",
        price=price,
        old_price=1.79,
        quantity=1.0,
        unit="l",
        image_url="https://img.example/milk.jpg",
    )


def berlin_branch(store: str = "lidl") -> StoreBranch:
    return StoreBranch(
        store=store,
        branch_id="s1",
        name="Lidl Berlin Mitte",
        address="Invalidenstraße 1",
        postal_code="10115",
        city="Berlin",
        latitude=52.531,
        longitude=13.384,
        distance_km=0.7,
    )


class FakeAggregator:
    """Records calls and returns deterministic fixtures."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def search(self, **kwargs: Any) -> list[NormalizedProduct]:
        self.calls.append(("search", kwargs))
        return [milk_product("lidl", 1.29), milk_product("rewe", 1.19)]

    async def compare(self, **kwargs: Any) -> list[NormalizedProduct]:
        self.calls.append(("compare", kwargs))
        return [milk_product("rewe", 1.19), milk_product("lidl", 1.29)]

    async def search_stores(self, **kwargs: Any) -> list[StoreBranch]:
        self.calls.append(("search_stores", kwargs))
        return [berlin_branch("lidl")]

    async def search_ranked(self, **kwargs: Any) -> RankedSearchResult:
        self.calls.append(("search_ranked", kwargs))
        product = milk_product("lidl", 1.29)
        return RankedSearchResult(
            query=kwargs["query"],
            postal_code=kwargs.get("postal_code"),
            total_found=2,
            total_returned=1,
            items=[
                RankedItem(
                    product=product,
                    relevance=RelevanceInfo(
                        tier=3,
                        score=1.0,
                        matched_as="exact",
                        matched_terms=["milch"],
                    ),
                    validity=ValidityInfo(
                        state="today", label="Heute gültig", ends="2026-11-07"
                    ),
                )
            ],
            quick_filters=[QuickFilter(term="Buttermilch", count=3)],
            sources={"lidl": 1, "rewe": 1},
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
            savings=0.2,
            baseline_total=1.49,
        )
        return BasketPlan(
            postal_code=kwargs.get("postal_code"),
            items=[
                BasketItemResult(query=item, status="matched")
                for item in kwargs["items"]
            ],
            option_a=option,
            option_b=option.model_copy(update={"label": "Max. 2 Märkte"}),
            unmatched=[],
            errors={},
        )

    def last_call(self, name: str) -> dict[str, Any]:
        for call_name, kwargs in reversed(self.calls):
            if call_name == name:
                return kwargs
        raise AssertionError(f"{name} was not called")


@pytest.fixture
def aggregator() -> FakeAggregator:
    return FakeAggregator()


@pytest.fixture
def client(aggregator: FakeAggregator) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[get_aggregator] = lambda: aggregator
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_health_endpoint(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["version"]


def test_root_endpoint_serves_the_web_ui(client: TestClient) -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "Supermarkt-Preisvergleich" in response.text


def test_swagger_and_redoc_are_available(client: TestClient) -> None:
    swagger = client.get("/docs")
    redoc = client.get("/redoc")

    assert swagger.status_code == 200
    assert "swagger-ui" in swagger.text.lower()
    assert redoc.status_code == 200
    assert "redoc" in redoc.text.lower()


def test_openapi_schema_lists_all_endpoints(client: TestClient) -> None:
    response = client.get("/openapi.json")

    assert response.status_code == 200
    schema = response.json()
    assert set(schema["paths"]) == {
        "/api/v1/admin/database/records",
        "/api/v1/admin/database/records/{table}/{record_id}",
        "/api/v1/receipts",
        "/api/v1/receipts/scan",
        "/api/v1/receipts/export",
        "/api/v1/admin/database/schema",
        "/api/v1/products/search",
        "/api/v1/products/search/ranked",
        "/api/v1/products/compare",
        "/api/v1/products/image",
        "/api/v1/basket/optimize",
        "/api/v1/basket/parse",
        "/api/v1/products/history",
        "/api/v1/products/price-insights",
        "/api/v1/stats/summary",
        "/api/v1/stats/trends",
        "/api/v1/system/backup-db",
        "/api/v1/system/restore-db",
        "/api/v1/crowd/coverage",
        "/api/v1/crowd/prices",
        "/api/v1/crowd/prices/{price_id}/approve",
        "/api/v1/crowd/prices/{price_id}/confirm",
        "/api/v1/crowd/prices/{price_id}/reject",
        "/api/v1/crowd/review",
        "/api/v1/crowd/review/approve-all",
        "/api/v1/crowd/receipts/text",
        "/api/v1/crowd/scouts/{scout_id}",
        "/api/v1/crowd/upload-receipt",
        "/api/v1/stores/search",
        "/api/v1/stores",
        "/health",
    }
    assert schema["info"]["title"] == "DACH Supermarket Price Comparison API"


def test_product_search_forwards_filters(
    client: TestClient, aggregator: FakeAggregator
) -> None:
    response = client.get(
        "/api/v1/products/search",
        params={
            "query": "milch",
            "postal_code": "10115",
            "stores": "lidl, rewe",
            "limit": 5,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert [item["store"] for item in payload] == ["lidl", "rewe"]
    assert payload[0]["name"] == "Bio Vollmilch"
    assert payload[0]["unit_price"] == pytest.approx(1.29)

    assert aggregator.last_call("search") == {
        "query": "milch",
        "postal_code": "10115",
        "stores": ["lidl", "rewe"],
        "limit": 5,
        "precise": True,
        "include_standard": False,
    }


def test_product_search_without_stores_filter(
    client: TestClient, aggregator: FakeAggregator
) -> None:
    response = client.get("/api/v1/products/search", params={"query": "milch"})

    assert response.status_code == 200
    assert aggregator.last_call("search")["stores"] is None


def test_product_search_requires_query(client: TestClient) -> None:
    assert client.get("/api/v1/products/search").status_code == 422


@pytest.mark.parametrize("postal_code", ["101", "101155"])
def test_product_search_validates_postal_code(
    client: TestClient, postal_code: str
) -> None:
    response = client.get(
        "/api/v1/products/search",
        params={"query": "milch", "postal_code": postal_code},
    )

    assert response.status_code == 422


def test_compare_by_ean(client: TestClient, aggregator: FakeAggregator) -> None:
    response = client.get(
        "/api/v1/products/compare",
        params={
            "ean": "4012345678901",
            "postal_code": "10115",
            "stores": "lidl,rewe",
        },
    )

    assert response.status_code == 200
    assert [item["store"] for item in response.json()] == ["rewe", "lidl"]
    assert aggregator.last_call("compare") == {
        "ean": "4012345678901",
        "query": None,
        "postal_code": "10115",
        "stores": ["lidl", "rewe"],
        "limit": 20,
    }


def test_compare_by_query(client: TestClient, aggregator: FakeAggregator) -> None:
    response = client.get("/api/v1/products/compare", params={"query": "milch"})

    assert response.status_code == 200
    assert aggregator.last_call("compare")["query"] == "milch"
    assert aggregator.last_call("compare")["ean"] is None


def test_compare_requires_ean_or_query(client: TestClient) -> None:
    response = client.get("/api/v1/products/compare")

    assert response.status_code == 422
    assert "ean" in response.json()["detail"]


def test_compare_validates_ean_length(client: TestClient) -> None:
    response = client.get("/api/v1/products/compare", params={"ean": "1234"})

    assert response.status_code == 422


@pytest.mark.parametrize("path", ["/api/v1/stores", "/api/v1/stores/search"])
def test_store_search(
    client: TestClient, aggregator: FakeAggregator, path: str
) -> None:
    response = client.get(
        path,
        params={"postal_code": "10115", "store": "lidl", "limit": 10},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload[0]["store"] == "lidl"
    assert payload[0]["postal_code"] == "10115"
    assert payload[0]["distance_km"] == pytest.approx(0.7)
    assert aggregator.last_call("search_stores") == {
        "postal_code": "10115",
        "store": "lidl",
        "limit": 10,
    }


def test_store_search_requires_postal_code(client: TestClient) -> None:
    assert client.get("/api/v1/stores/search").status_code == 422


def test_cors_headers_are_present(client: TestClient) -> None:
    response = client.options(
        "/api/v1/products/search",
        headers={
            "Origin": "https://example.org",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://example.org"
    assert "GET" in response.headers["access-control-allow-methods"]


def test_unknown_endpoint_returns_404(client: TestClient) -> None:
    assert client.get("/api/v1/does-not-exist").status_code == 404


def test_lifespan_closes_injected_aggregator() -> None:
    closed = False

    class ClosingAggregator(FakeAggregator):
        async def aclose(self) -> None:
            nonlocal closed
            closed = True

    app = create_app(aggregator=ClosingAggregator())
    with TestClient(app):
        pass

    assert closed is True


def test_ranked_search_forwards_every_option(
    client: TestClient, aggregator: FakeAggregator
) -> None:
    response = client.get(
        "/api/v1/products/search/ranked",
        params={
            "query": "butter",
            "postal_code": "65618",
            "stores": "lidl,rewe",
            "limit": 8,
            "precise": "false",
            "exclude": "Buttermilch, Butterkekse",
            "today_only": "true",
        },
    )

    assert response.status_code == 200
    assert aggregator.last_call("search_ranked") == {
        "query": "butter",
        "postal_code": "65618",
        "stores": ["lidl", "rewe"],
        "limit": 8,
        "precise": False,
        "exclude": ["Buttermilch", "Butterkekse"],
        "today_only": True,
        "include_standard": False,
        "offers_only": False,
    }


def test_ranked_search_response_shape(
    client: TestClient, aggregator: FakeAggregator
) -> None:
    response = client.get("/api/v1/products/search/ranked", params={"query": "butter"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["query"] == "butter"
    assert payload["postal_code"] is None
    assert payload["total_found"] == 2
    assert payload["total_returned"] == 1
    assert payload["sources"] == {"lidl": 1, "rewe": 1}
    assert payload["errors"] == {}
    assert payload["quick_filters"] == [{"term": "Buttermilch", "count": 3}]

    item = payload["items"][0]
    assert item["product"]["name"] == "Bio Vollmilch"
    assert item["relevance"]["tier"] == 3
    assert item["relevance"]["matched_as"] == "exact"
    assert item["validity"]["state"] == "today"
    assert item["validity"]["label"] == "Heute gültig"


def test_ranked_search_defaults_to_precise(
    client: TestClient, aggregator: FakeAggregator
) -> None:
    client.get("/api/v1/products/search/ranked", params={"query": "butter"})

    call = aggregator.last_call("search_ranked")
    assert call["precise"] is True
    assert call["limit"] == 20
    assert call["exclude"] is None
    assert call["today_only"] is False


def test_ranked_search_requires_query(client: TestClient) -> None:
    assert client.get("/api/v1/products/search/ranked").status_code == 422


def test_plain_search_accepts_precise_and_today_only(
    client: TestClient, aggregator: FakeAggregator
) -> None:
    response = client.get(
        "/api/v1/products/search",
        params={"query": "milch", "precise": "false", "today_only": "false"},
    )

    assert response.status_code == 200
    assert aggregator.last_call("search")["precise"] is False

    today_only = client.get(
        "/api/v1/products/search",
        params={"query": "milch", "today_only": "true"},
    )
    # The fixture has no validity dates, so nothing is valid today.
    assert today_only.status_code == 200
    assert today_only.json() == []


def test_plain_search_applies_exclusions(
    client: TestClient, aggregator: FakeAggregator
) -> None:
    response = client.get(
        "/api/v1/products/search",
        params={"query": "milch", "exclude": "Vollmilch"},
    )

    assert response.status_code == 200
    assert response.json() == []


def test_basket_optimize_accepts_a_valid_body(
    client: TestClient, aggregator: FakeAggregator
) -> None:
    response = client.post(
        "/api/v1/basket/optimize",
        json={
            "items": ["Butter", "Nutella", "Milch", "Kaffee"],
            "postal_code": "65618",
            "stores": None,
            "max_stores": 2,
            "today_only": True,
        },
    )

    assert response.status_code == 200
    assert aggregator.last_call("optimize_basket") == {
        "items": ["Butter", "Nutella", "Milch", "Kaffee"],
        "postal_code": "65618",
        "stores": None,
        "max_stores": 2,
        "today_only": True,
        "include_standard": False,
    }

    payload = response.json()
    assert payload["postal_code"] == "65618"
    assert payload["unmatched"] == []
    assert payload["errors"] == {}
    assert [item["status"] for item in payload["items"]] == ["matched"] * 4
    assert payload["option_a"]["label"] == "Bester Split"
    assert payload["option_a"]["total"] == pytest.approx(1.29)
    assert payload["option_b"]["label"] == "Max. 2 Märkte"
    assert payload["option_b"]["covers_all"] is True


def test_basket_optimize_deduplicates_and_drops_blank_items(
    client: TestClient, aggregator: FakeAggregator
) -> None:
    response = client.post(
        "/api/v1/basket/optimize",
        json={"items": ["Butter", " butter ", "  ", "Milch", "MILCH"]},
    )

    assert response.status_code == 200
    assert aggregator.last_call("optimize_basket")["items"] == ["Butter", "Milch"]


def test_basket_optimize_rejects_empty_or_invalid_bodies(
    client: TestClient,
) -> None:
    assert client.post("/api/v1/basket/optimize", json={}).status_code == 422
    assert client.post("/api/v1/basket/optimize", json={"items": []}).status_code == 422
    assert (
        client.post(
            "/api/v1/basket/optimize", json={"items": ["   ", "\n"]}
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/basket/optimize", json={"items": ["Butter"], "max_stores": 9}
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/basket/optimize", json={"items": ["Butter"], "postal_code": "1"}
        ).status_code
        == 422
    )
    assert (
        client.post("/api/v1/basket/optimize", json={"items": ["x" * 61]}).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/basket/optimize",
            json={"items": [f"item-{index}" for index in range(21)]},
        ).status_code
        == 422
    )
