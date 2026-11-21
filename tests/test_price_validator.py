"""Tests for the deterministic community price validator."""

from __future__ import annotations

import pytest

from supermarket_comparison.services.price_validator import (
    PriceContext,
    validate_price,
)


def butter(price: float = 2.49) -> PriceContext:
    return PriceContext(
        name="Bio Butter 250g",
        price=price,
        unit="kg",
        quantity=0.25,
        unit_price=round(price / 0.25, 2),
        brand="Weihenstephan",
    )


def test_absurd_price_is_flagged() -> None:
    result = validate_price(
        PriceContext(
            name="Milch",
            price=999.99,
            unit="l",
            quantity=1.0,
            unit_price=999.99,
        )
    )

    assert result.status == "pending_review"
    assert any("Grenze" in reason or "Band" in reason for reason in result.reasons)


def test_zero_price_is_flagged() -> None:
    result = validate_price(PriceContext(name="Milch", price=0.01))

    assert result.status == "pending_review"
    assert result.reasons


def test_plausible_butter_is_pending() -> None:
    result = validate_price(butter())

    assert result.status == "pending"
    assert result.reasons == []


def test_unit_price_outside_band_is_flagged() -> None:
    result = validate_price(
        PriceContext(
            name="Butter",
            price=0.01,
            unit="kg",
            quantity=1.0,
            unit_price=0.01,
        )
    )

    assert result.status == "pending_review"
    assert any("Band" in reason for reason in result.reasons)


def test_relative_deviation_from_history_is_flagged() -> None:
    # 5.49 € / 250 g = 21.96 €/kg — inside the dairy band, but 2.4× the median.
    result = validate_price(butter(5.49), history=[2.19, 2.29, 2.39])

    assert result.status == "pending_review"
    assert any("Median" in reason for reason in result.reasons)


def test_history_below_three_is_ignored() -> None:
    result = validate_price(butter(5.49), history=[2.19, 2.29])

    assert result.status == "pending"
    assert result.reasons == []


def test_piece_products_skip_the_unit_price_band() -> None:
    result = validate_price(
        PriceContext(name="Shampoo", price=2.99, unit="stueck", quantity=1.0)
    )

    assert result.status == "pending"


def test_non_positive_quantity_is_flagged() -> None:
    result = validate_price(
        PriceContext(name="Butter", price=2.49, unit="kg", quantity=0.0)
    )

    assert result.status == "pending_review"


def test_very_cheap_history_outlier_is_flagged() -> None:
    result = validate_price(butter(0.99), history=[2.19, 2.29, 2.39])

    assert result.status == "pending_review"
    assert any("Median" in reason for reason in result.reasons)


@pytest.mark.parametrize("price", [0.09, 200.01, 5000.0])
def test_hard_price_caps(price: float) -> None:
    assert validate_price(PriceContext(name="Butter", price=price)).status == (
        "pending_review"
    )
