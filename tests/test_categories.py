"""Tests for the product category classifier used by price validation."""

from __future__ import annotations

import pytest

from supermarket_comparison.services.categories import (
    classify_product,
    unit_price_band,
)


@pytest.mark.parametrize(
    ("name", "group"),
    [
        ("Bio Butter 250g", "dairy"),
        ("Fettarme Milch", "dairy"),
        ("Gouda jung", "dairy"),
        ("Hähnchenschenkel", "meat"),
        ("Rinderhackfleisch", "meat"),
        ("Bio Ingwer", "produce"),
        ("Bananen", "produce"),
        ("Cola XXL", "drinks"),
        ("Mineralwasser", "drinks"),
        ("Vollkornbrot", "bakery"),
        ("Toastbrot", "bakery"),
        ("Spaghetti", "pantry"),
        ("Sonnenblumenöl", "pantry"),
        ("Schokolade", "sweets"),
        ("Kartoffelchips", "sweets"),
        ("Shampoo", "drugstore"),
        ("Toilettenpapier", "drugstore"),
        ("Batterien AA", "other"),
        ("", "other"),
    ],
)
def test_classify_product(name: str, group: str) -> None:
    assert classify_product(name) == group


def test_brand_helps_classification() -> None:
    assert classify_product("Original", brand="Coca-Cola") == "drinks"


def test_band_for_known_group() -> None:
    low, high = unit_price_band("dairy")
    assert low == pytest.approx(0.30)
    assert high == pytest.approx(25.0)


def test_band_for_other_group_is_wide() -> None:
    low, high = unit_price_band("other")
    assert low <= 0.05
    assert high >= 500.0


def test_band_for_unknown_group_falls_back() -> None:
    assert unit_price_band("does-not-exist") == unit_price_band("other")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Getraenke", "Getränke"),
        ("getränke", "Getränke"),
        ("GETRÄNKE", "Getränke"),
        ("Baecker/Gastronomie", "Bäcker/Gastronomie"),
        ("Technik/Non-Food", "Technik/Non-Food"),
        ("Lebensmittel", "Lebensmittel"),
        ("Sonstiges", "Sonstiges"),
        ("unbekannt", "Sonstiges"),
        (None, "Sonstiges"),
    ],
)
def test_normalize_receipt_category(raw: str | None, expected: str) -> None:
    from supermarket_comparison.normalization.categories import normalize_category

    assert normalize_category(raw) == expected
