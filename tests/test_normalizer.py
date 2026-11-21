"""Tests for the quantity/unit normalisation engine and derived model fields."""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from supermarket_comparison.models import NormalizedProduct, StoreBranch
from supermarket_comparison.normalization.normalizer import (
    COUNT,
    MASS,
    UNKNOWN,
    VOLUME,
    calculate_discount_percent,
    calculate_unit_price,
    normalize_unit,
    parse_decimal,
    parse_quantity,
    to_canonical,
    unit_family,
)


class TestParseQuantity:
    @pytest.mark.parametrize(
        ("text", "quantity", "unit", "raw_quantity", "raw_unit", "pack_count"),
        [
            ("500g", 0.5, "kg", 500.0, "g", 1),
            ("500 g", 0.5, "kg", 500.0, "g", 1),
            ("250 G", 0.25, "kg", 250.0, "g", 1),
            ("1 kg", 1.0, "kg", 1.0, "kg", 1),
            ("1,5kg", 1.5, "kg", 1.5, "kg", 1),
            ("1.000 g", 1.0, "kg", 1000.0, "g", 1),
            ("1,234.5 g", 1.2345, "kg", 1234.5, "g", 1),
            ("750 ml", 0.75, "l", 750.0, "ml", 1),
            ("500 ml", 0.5, "l", 500.0, "ml", 1),
            ("1,5 l", 1.5, "l", 1.5, "l", 1),
            ("1.5 L", 1.5, "l", 1.5, "l", 1),
            ("1 Liter", 1.0, "l", 1.0, "l", 1),
            ("6 x 0,33 l", 1.98, "l", 0.33, "l", 6),
            ("6x0,33l", 1.98, "l", 0.33, "l", 6),
            ("2 × 250 ml", 0.5, "l", 250.0, "ml", 2),
            ("2er Pack 0,5 l", 1.0, "l", 0.5, "l", 2),
            ("6er 200g", 1.2, "kg", 200.0, "g", 6),
            ("10 Stück", 10.0, "stueck", 10.0, "stueck", 1),
            ("3 stk.", 3.0, "stueck", 3.0, "stueck", 1),
            ("ca. 500 g", 0.5, "kg", 500.0, "g", 1),
            ("500 g Abtropfgewicht", 0.5, "kg", 500.0, "g", 1),
            ("1,5-l-Flasche", 1.5, "l", 1.5, "l", 1),
            ("500-g-Packung", 0.5, "kg", 500.0, "g", 1),
            ("1 Pfund", 0.5, "kg", 1.0, "pfund", 1),
            ("Milch 3,5% 1 l", 1.0, "l", 1.0, "l", 1),
            ("6", 6.0, "stueck", 6.0, "stueck", 1),
            ("6er", 6.0, "stueck", 6.0, "stueck", 1),
        ],
    )
    def test_parses_common_labels(
        self,
        text: str,
        quantity: float,
        unit: str,
        raw_quantity: float,
        raw_unit: str,
        pack_count: int,
    ) -> None:
        parsed = parse_quantity(text)

        assert parsed is not None, f"failed to parse {text!r}"
        assert parsed.quantity == pytest.approx(quantity)
        assert parsed.unit == unit
        assert parsed.raw_quantity == pytest.approx(raw_quantity)
        assert parsed.raw_unit == raw_unit
        assert parsed.pack_count == pack_count

    def test_multipack_total_and_single_pack(self) -> None:
        parsed = parse_quantity("6 x 0,33 l")

        assert parsed is not None
        assert parsed.total_raw_quantity == pytest.approx(1.98)
        assert parsed.is_piece is False
        assert str(parsed) == "6 x 0.33 l"

    @pytest.mark.parametrize("value", [None, "", "   ", "keine Angabe", "3,5%"])
    def test_returns_none_for_missing_quantity(self, value: str | None) -> None:
        assert parse_quantity(value) is None

    def test_accepts_numeric_piece_count(self) -> None:
        parsed = parse_quantity(6)

        assert parsed is not None
        assert parsed.quantity == 6.0
        assert parsed.unit == "stueck"


class TestUnitNormalisation:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("G", "g"),
            ("Gramm", "g"),
            ("gr.", "g"),
            ("KG", "kg"),
            ("Kilogramm", "kg"),
            ("Liter", "l"),
            ("LTR", "l"),
            ("milliliter", "ml"),
            ("Stück", "stueck"),
            ("Stk.", "stueck"),
            ("STCK", "stueck"),
            ("Pieces", "stueck"),
            ("  kg.  ", "kg"),
            ("Bund", "bund"),
            ("", ""),
        ],
    )
    def test_normalize_unit(self, raw: str, expected: str) -> None:
        assert normalize_unit(raw) == expected

    @pytest.mark.parametrize(
        ("unit", "family"),
        [
            ("g", MASS),
            ("kg", MASS),
            ("mg", MASS),
            ("l", VOLUME),
            ("ml", VOLUME),
            ("cl", VOLUME),
            ("stueck", COUNT),
            ("Stück", COUNT),
            ("bund", UNKNOWN),
            ("", UNKNOWN),
        ],
    )
    def test_unit_family(self, unit: str, family: str) -> None:
        assert unit_family(unit) == family

    @pytest.mark.parametrize(
        ("quantity", "unit", "expected_quantity", "expected_unit"),
        [
            (500, "g", 0.5, "kg"),
            (1, "kg", 1.0, "kg"),
            (750, "ml", 0.75, "l"),
            (1.5, "l", 1.5, "l"),
            (6, "stueck", 6.0, "stueck"),
            (2, "Bund", 2.0, "bund"),
        ],
    )
    def test_to_canonical(
        self,
        quantity: float,
        unit: str,
        expected_quantity: float,
        expected_unit: str,
    ) -> None:
        value, canonical_unit = to_canonical(quantity, unit)

        assert value == pytest.approx(expected_quantity)
        assert canonical_unit == expected_unit


class TestUnitPrice:
    @pytest.mark.parametrize(
        ("price", "quantity", "unit", "expected"),
        [
            (2.49, 500, "g", 4.98),
            (2.49, 0.5, "kg", 4.98),
            (1.49, 1, "kg", 1.49),
            (1.99, 750, "ml", 2.6533),
            (1.99, 0.75, "l", 2.6533),
            (3.99, 1.98, "l", 2.0152),
            (1.0, 10, "stueck", None),
            (1.0, 0, "kg", None),
            (1.0, -1, "kg", None),
            (-1.0, 1, "kg", None),
            (None, 1, "kg", None),
        ],
    )
    def test_calculate_unit_price(
        self,
        price: float | None,
        quantity: float,
        unit: str,
        expected: float | None,
    ) -> None:
        result = calculate_unit_price(price, quantity, unit)

        if expected is None:
            assert result is None
        else:
            assert result == pytest.approx(expected)

    def test_unit_price_for_multipack(self) -> None:
        parsed = parse_quantity("6 x 0,33 l")
        assert parsed is not None

        assert calculate_unit_price(
            3.99, parsed.quantity, parsed.unit
        ) == pytest.approx(2.0152)


class TestDiscount:
    @pytest.mark.parametrize(
        ("price", "old_price", "expected"),
        [
            (2.0, 4.0, 50.0),
            (1.99, 2.49, 20.08),
            (1.0, 3.0, 66.67),
            (2.49, 2.49, 0.0),
            (3.0, 2.0, 0.0),
            (2.49, None, None),
            (2.49, 0, None),
            (None, 2.49, None),
        ],
    )
    def test_calculate_discount_percent(
        self, price: float | None, old_price: float | None, expected: float | None
    ) -> None:
        assert calculate_discount_percent(price, old_price) == expected


class TestParseDecimal:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("1,99", 1.99),
            ("2.49", 2.49),
            ("€ 1,99", 1.99),
            ("1.234,56 €", 1234.56),
            ("1,234.56", 1234.56),
            ("1.000", 1000.0),
            ("0.500", 0.5),
            ("-1,50", -1.5),
            (3, 3.0),
            (None, None),
            ("keine Angabe", None),
        ],
    )
    def test_parse_decimal(self, value: object, expected: float | None) -> None:
        assert parse_decimal(value) == expected


class TestNormalizedProduct:
    def test_derived_quantity_unit_price_and_discount(self) -> None:
        product = NormalizedProduct(
            id="lidl-1",
            store="LIDL",
            name="Bio Vollmilch",
            price=2.49,
            old_price=4.98,
            unit="g",
            quantity=500,
        )

        assert product.store == "lidl"
        assert product.unit == "kg"
        assert product.quantity == pytest.approx(0.5)
        assert product.unit_price == pytest.approx(4.98)
        assert product.discount_percent == pytest.approx(50.0)

    def test_parses_string_prices_and_quantities(self) -> None:
        product = NormalizedProduct(
            id="rewe-1",
            store="rewe",
            name="Mineralwasser",
            price="1,99 €",
            unit="l",
            quantity="1,5",
        )

        assert product.price == pytest.approx(1.99)
        assert product.quantity == pytest.approx(1.5)
        assert product.unit_price == pytest.approx(1.3267)

    def test_piece_products_have_no_unit_price(self) -> None:
        product = NormalizedProduct(
            id="edeka-1",
            store="edeka",
            name="Gurke",
            price=0.99,
            unit="Stück",
            quantity=1,
        )

        assert product.unit == "stueck"
        assert product.unit_price is None

    def test_display_title_enriches_generic_title(self) -> None:
        product = NormalizedProduct(
            id="mg-1",
            store="netto",
            name="Bier",
            brand="Corona Extra",
            price=1.49,
        )

        assert product.display_title == "Corona Extra Bier"
        dumped = product.model_dump()
        assert dumped["display_title"] == "Corona Extra Bier"

    def test_display_title_no_duplication(self) -> None:
        product = NormalizedProduct(
            id="mg-2",
            store="netto",
            name="Hefe-Weißbier",
            brand="Paulaner",
            price=1.99,
        )

        assert product.display_title == "Paulaner Hefe-Weißbier"

    def test_explicit_derived_values_are_preserved(self) -> None:
        product = NormalizedProduct(
            id="lidl-2",
            store="lidl",
            name="Kaffee",
            price=5.0,
            old_price=10.0,
            discount_percent=49.0,
            unit="kg",
            quantity=1,
            unit_price=5.0,
        )

        assert product.discount_percent == 49.0
        assert product.unit_price == 5.0

    def test_ean_and_dates_are_cleaned(self) -> None:
        product = NormalizedProduct(
            id="lidl-3",
            store="lidl",
            name="Schokolade",
            ean="4 012345 678901",
            price=1.29,
            unit="g",
            quantity=100,
            valid_from=date(2026, 11, 1),
            valid_to="2026-11-30",
        )

        assert product.ean == "4012345678901"
        assert product.valid_from == "2026-11-01"
        assert product.valid_to == "2026-11-30"
        assert product.unit == "kg"
        assert product.quantity == pytest.approx(0.1)
        assert product.unit_price == pytest.approx(12.9)

    @pytest.mark.parametrize(
        "payload",
        [
            {"name": ""},
            {"price": -1},
            {"quantity": -5},
            {"discount_percent": 150},
        ],
    )
    def test_rejects_invalid_values(self, payload: dict[str, object]) -> None:
        data: dict[str, object] = {
            "id": "x",
            "store": "lidl",
            "name": "Test",
            "price": 1.0,
            "unit": "kg",
            "quantity": 1.0,
        }
        data.update(payload)

        with pytest.raises(ValidationError):
            NormalizedProduct(**data)


class TestStoreBranch:
    def test_normalises_fields(self) -> None:
        branch = StoreBranch(
            store="LIDL",
            branch_id="1234",
            name="Lidl Berlin Mitte",
            address="Invalidenstraße 1",
            postal_code=10115,
            city="Berlin",
        )

        assert branch.store == "lidl"
        assert branch.postal_code == "10115"
        assert branch.full_address == "Invalidenstraße 1, 10115 Berlin"

    def test_requires_core_fields(self) -> None:
        with pytest.raises(ValidationError):
            StoreBranch(
                store="lidl",
                branch_id="1",
                name="",
                address="Str. 1",
                postal_code="10115",
                city="Berlin",
            )
