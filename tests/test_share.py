"""Tests for the WhatsApp / clipboard export of a basket plan."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from supermarket_comparison.api.deps import get_aggregator
from supermarket_comparison.api.main import create_app
from supermarket_comparison.models import (
    BasketItemResult,
    BasketLine,
    BasketOption,
    BasketPlan,
    NormalizedProduct,
    StoreGroup,
)
from supermarket_comparison.services.sharing import (
    format_plan_text,
    format_price,
    whatsapp_url,
)


def product(
    name: str,
    price: float,
    *,
    store: str = "edeka",
    quantity: float = 1.0,
    unit: str = "stueck",
) -> NormalizedProduct:
    return NormalizedProduct(
        id=f"{store}-{name}",
        store=store,
        name=name,
        price=price,
        quantity=quantity,
        unit=unit,
    )


def line(
    item: str, name: str, price: float, store: str = "edeka", **kwargs: Any
) -> BasketLine:
    return BasketLine(
        item=item, product=product(name, price, store=store, **kwargs), store=store
    )


def option(
    stores: list[StoreGroup],
    total: float,
    *,
    savings: float = 0.0,
    baseline_total: float | None = None,
    baseline_partial: bool = False,
    merchants: int | None = None,
    label: str = "Bester Split",
) -> BasketOption:
    return BasketOption(
        label=label,
        stores=stores,
        total=total,
        merchants=merchants if merchants is not None else len(stores),
        covers_all=True,
        savings=savings,
        baseline_total=baseline_total,
        baseline_partial=baseline_partial,
    )


def plan(option_a: BasketOption, option_b: BasketOption | None = None) -> BasketPlan:
    return BasketPlan(
        postal_code="65189",
        items=[BasketItemResult(query="Spaghetti", status="matched")],
        option_a=option_a,
        option_b=option_b or option_a,
    )


# -- price formatting -------------------------------------------------------


def test_format_price_uses_german_decimal_comma() -> None:
    assert format_price(2.5) == "2,50 €"
    assert format_price(0.99) == "0,99 €"
    assert format_price(12.0) == "12,00 €"
    assert format_price(None) == "–"


# -- plan text --------------------------------------------------------------


def test_share_text_lists_stores_products_and_total() -> None:
    edeka = StoreGroup(
        store="edeka",
        subtotal=2.15,
        lines=[
            line("Milch", "Fettarme Milch", 0.66, quantity=1.0, unit="l"),
            line("Nudeln", "Mie-Nudeln", 1.49),
        ],
    )
    netto = StoreGroup(
        store="netto", subtotal=0.99, lines=[line("Butter", "Butter", 0.99)]
    )
    text = format_plan_text(
        plan(
            option(stores=[edeka, netto], total=3.14, savings=0.3, baseline_total=3.44)
        )
    )

    assert "Smart Basket" in text
    assert "PLZ 65189" in text
    assert "Edeka – 2,15 €" in text
    assert "Netto – 0,99 €" in text
    assert "• Milch: Fettarme Milch (1000 ml) – 0,66 €" in text
    assert "Gesamt: 3,14 €" in text
    assert "Ersparnis: 0,30 €" in text
    assert "Supermarkt-Preisvergleich" in text


def test_share_text_marks_partial_baseline_without_savings() -> None:
    store = StoreGroup(
        store="lidl", subtotal=1.39, lines=[line("Butter", "Butter", 1.39)]
    )
    text = format_plan_text(
        plan(option(stores=[store], total=1.39, savings=0.0, baseline_partial=True))
    )

    assert "Kein Einzelmarkt deckt alle Artikel ab" in text
    assert "Ersparnis" not in text


def test_share_text_mentions_missing_items() -> None:
    store = StoreGroup(
        store="lidl", subtotal=1.39, lines=[line("Butter", "Butter", 1.39)]
    )
    blueprint = plan(option(stores=[store], total=1.39))
    blueprint.unmatched = ["Kaffee"]
    text = format_plan_text(blueprint)

    assert "Nicht gefunden: Kaffee" in text


def test_share_text_mentions_alternative_option() -> None:
    store = StoreGroup(
        store="lidl", subtotal=1.39, lines=[line("Butter", "Butter", 1.39)]
    )
    a = option(stores=[store], total=1.39, savings=0.4, baseline_total=1.79)
    b = option(stores=[store], total=1.59, merchants=2, label="Max. 2 Märkte")
    text = format_plan_text(plan(a, b))

    assert "Alternative mit max. 2 Märkten: 1,59 €" in text


def test_share_text_falls_back_to_option_b_when_a_is_empty() -> None:
    store = StoreGroup(store="rewe", subtotal=2.49, lines=[line("Brot", "Brot", 2.49)])
    empty = option(stores=[], total=0)
    b = option(stores=[store], total=2.49, label="Max. 2 Märkte")
    text = format_plan_text(plan(empty, b))

    assert "Rewe – 2,49 €" in text
    assert "Gesamt: 2,49 €" in text


def test_share_text_without_any_offer() -> None:
    empty = option(stores=[], total=0)
    text = format_plan_text(plan(empty))

    assert "Keine passenden Angebote" in text


def test_whatsapp_url_is_encoded() -> None:
    text = "🛒 Smart Basket · PLZ 65189\nGesamt: 3,14 €"
    url = whatsapp_url(text)

    assert url.startswith("https://wa.me/?text=")
    assert " " not in url.split("text=", 1)[1]
    assert "%0A" in url  # newlines encoded
    assert "%E2%82%AC" in url  # euro sign encoded


# -- API integration --------------------------------------------------------


class _FakeAggregator:
    """Returns a plan with the share fields the real aggregator would build."""

    async def optimize_basket(self, **kwargs: Any) -> BasketPlan:
        store = StoreGroup(
            store="lidl", subtotal=1.39, lines=[line("Butter", "Butter", 1.39)]
        )
        option_a = option(stores=[store], total=1.39)
        plan_obj = plan(option_a)
        plan_obj.postal_code = kwargs.get("postal_code")
        text = format_plan_text(plan_obj)
        plan_obj.share_text = text
        plan_obj.whatsapp_url = whatsapp_url(text)
        return plan_obj


def test_optimize_returns_share_fields() -> None:
    app = create_app()
    app.dependency_overrides[get_aggregator] = lambda: _FakeAggregator()
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/basket/optimize",
            json={"items": ["Butter"], "postal_code": "65618"},
        )
    app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["share_text"]
    assert payload["whatsapp_url"].startswith("https://wa.me/?text=")
    assert "Smart Basket" in payload["share_text"]
    assert "Lidl – 1,39 €" in payload["share_text"]


def test_recipes_endpoint_is_gone() -> None:
    """The budget-recipe feature was removed in iteration 9."""

    with TestClient(create_app()) as client:
        assert client.get("/api/v1/recipes").status_code == 404
        assert client.get("/api/v1/recipes/spaghetti-bolognese").status_code == 404
