"""Tests for the cross-store product matcher and deduplication pipeline."""

from __future__ import annotations

import pytest

from supermarket_comparison.models import NormalizedProduct
from supermarket_comparison.normalization.matcher import (
    ProductGroup,
    build_display_title,
    deduplicate,
    filter_by_query,
    group_products,
    match_products,
    normalize_ean,
    normalize_title,
    title_similarity,
)


def product(
    store: str,
    name: str,
    price: float,
    *,
    ean: str | None = None,
    quantity: float = 1.0,
    unit: str = "l",
    brand: str | None = None,
    product_id: str | None = None,
) -> NormalizedProduct:
    return NormalizedProduct(
        id=product_id or f"{store}-{name}".replace(" ", "-").lower(),
        store=store,
        name=name,
        price=price,
        ean=ean,
        quantity=quantity,
        unit=unit,
        brand=brand,
    )


class TestTitleHelpers:
    def test_normalize_title(self) -> None:
        assert normalize_title("  Bio-Vollmilch 3,8%! ") == "bio vollmilch 3 8"

    def test_title_similarity_is_bounded(self) -> None:
        assert title_similarity("Bio Vollmilch", "Bio Vollmilch") == 1.0
        assert 0.0 <= title_similarity("Bio Vollmilch", "Bauernbrot") < 0.5

    def test_normalize_ean(self) -> None:
        assert normalize_ean("4012345678901") == "4012345678901"
        assert normalize_ean("4012 345 678901") == "4012345678901"
        assert normalize_ean(None) is None
        assert normalize_ean("") is None

    def test_build_display_title_prepends_brand(self) -> None:
        assert build_display_title("Bier", "Corona Extra", None) == "Corona Extra Bier"
        assert (
            build_display_title("Original Bier", "Desperados", None)
            == "Desperados Original Bier"
        )

    def test_build_display_title_no_duplication(self) -> None:
        assert (
            build_display_title("Hefe-Weißbier", "Paulaner", None)
            == "Paulaner Hefe-Weißbier"
        )
        assert (
            build_display_title("Bier", "Corona Extra", None)
            != "Corona Extra Corona Extra Bier"
        )

    def test_build_display_title_without_brand(self) -> None:
        assert build_display_title("Bier", None, None) == "Bier"
        assert build_display_title("", None, None) == ""

    def test_build_display_title_extracts_hint_from_description(self) -> None:
        title = build_display_title("Bier", "Beck's", "0,33 l Dose")
        assert "Beck's" in title
        assert "Bier" in title
        assert "Dose" in title


class TestMatchProducts:
    def test_exact_ean_always_groups(self) -> None:
        products = [
            product("lidl", "Bio Vollmilch", 1.29, ean="4012345678901"),
            product("rewe", "REWE Bio Vollmilch", 1.19, ean="4012345678901"),
            product("edeka", "Bauernbrot", 2.49, ean="9876543210987", unit="kg"),
        ]

        groups = match_products(products)

        assert len(groups) == 2
        assert {item.store for item in groups[0]} == {"lidl", "rewe"}

    def test_fuzzy_title_match_without_ean(self) -> None:
        products = [
            product("lidl", "Bio Vollmilch", 1.29),
            product("rewe", "Bio Vollmilch", 1.19),
        ]

        groups = match_products(products)

        assert len(groups) == 1
        assert {item.store for item in groups[0]} == {"lidl", "rewe"}

    def test_different_products_are_not_grouped(self) -> None:
        products = [
            product("lidl", "Bio Vollmilch", 1.29),
            product("rewe", "Bauernbrot", 2.49, unit="kg"),
        ]

        assert len(match_products(products)) == 2

    def test_different_eans_are_not_grouped(self) -> None:
        products = [
            product("lidl", "Bio Vollmilch", 1.29, ean="4012345678901"),
            product("rewe", "Bio Vollmilch", 1.19, ean="4012345678918"),
        ]

        assert len(match_products(products)) == 2

    def test_different_package_sizes_are_not_grouped(self) -> None:
        products = [
            product("lidl", "Bio Vollmilch", 1.29, quantity=1.0),
            product("rewe", "Bio Vollmilch", 2.19, quantity=1.5),
        ]

        assert len(match_products(products)) == 2

    def test_same_amounts_with_different_units_are_not_grouped(self) -> None:
        products = [
            product("lidl", "Bio Vollmilch", 1.29, quantity=1.0, unit="l"),
            product("rewe", "Bio Vollmilch", 1.29, quantity=1.0, unit="kg"),
        ]

        assert len(match_products(products)) == 2

    def test_brand_conflict_prevents_match(self) -> None:
        products = [
            product("lidl", "Vollmilch", 1.29, brand="Weihenstephan"),
            product("rewe", "Vollmilch", 1.19, brand="Alnatura"),
        ]

        assert len(match_products(products)) == 2

    def test_threshold_validation(self) -> None:
        with pytest.raises(ValueError):
            match_products([], threshold=1.5)
        with pytest.raises(ValueError):
            match_products([], threshold=-0.1)

    def test_empty_input(self) -> None:
        assert match_products([]) == []


class TestGroupProducts:
    def test_group_metadata(self) -> None:
        products = [
            product("lidl", "Bio Vollmilch", 1.29, ean="4012345678901"),
            product("rewe", "Bio Vollmilch", 1.19, ean="4012345678901"),
            product("edeka", "Bio Vollmilch", 1.49, ean="4012345678901"),
        ]

        groups = group_products(products)

        assert len(groups) == 1
        group = groups[0]
        assert isinstance(group, ProductGroup)
        assert group.ean == "4012345678901"
        assert group.stores == ["edeka", "lidl", "rewe"]
        assert group.best_offer.store == "rewe"
        assert group.min_price == pytest.approx(1.19)
        assert group.max_price == pytest.approx(1.49)
        assert group.price_spread == pytest.approx(0.30)

    def test_groups_sorted_by_price(self) -> None:
        products = [
            product("lidl", "Bauernbrot", 2.49, unit="kg"),
            product("rewe", "Bio Vollmilch", 1.19),
        ]

        groups = group_products(products)

        assert [group.name for group in groups] == ["Bio Vollmilch", "Bauernbrot"]


class TestDeduplicate:
    def test_removes_exact_duplicates(self) -> None:
        products = [
            product("lidl", "Bio Vollmilch", 1.29, ean="4012345678901"),
            product("lidl", "Bio Vollmilch", 1.29, ean="4012345678901"),
            product("rewe", "Bio Vollmilch", 1.19, ean="4012345678901"),
        ]

        result = deduplicate(products)

        assert len(result) == 2
        assert [item.store for item in result] == ["lidl", "rewe"]

    def test_keeps_same_product_in_different_stores(self) -> None:
        products = [
            product("lidl", "Bio Vollmilch", 1.29, ean="4012345678901"),
            product("rewe", "Bio Vollmilch", 1.29, ean="4012345678901"),
        ]

        assert len(deduplicate(products)) == 2

    def test_keeps_cheapest_when_same_store_lists_product_twice(self) -> None:
        products = [
            product("lidl", "Bio Vollmilch", 1.29, ean="4012345678901"),
            product("lidl", "Bio Vollmilch", 0.99, ean="4012345678901"),
        ]

        result = deduplicate(products)

        assert len(result) == 1
        assert result[0].price == pytest.approx(0.99)

    def test_keeps_different_products_from_same_store(self) -> None:
        products = [
            product("lidl", "Bio Vollmilch", 1.29, ean="4012345678901"),
            product("lidl", "Laktosefreie Milch", 1.49, ean="9876543210987"),
        ]

        assert len(deduplicate(products)) == 2


class TestFilterByQuery:
    def test_matches_substring(self) -> None:
        products = [
            product("lidl", "Bio Vollmilch", 1.29),
            product("rewe", "Bauernbrot", 2.49, unit="kg"),
        ]

        result = filter_by_query(products, "milch")

        assert [item.name for item in result] == ["Bio Vollmilch"]

    def test_matches_any_query_token(self) -> None:
        products = [
            product("lidl", "Bio Vollmilch", 1.29),
            product("rewe", "H-Milch", 0.99),
        ]

        # Tolerant matching: any token of the query is enough.
        assert len(filter_by_query(products, "bio milch")) == 2

    @pytest.mark.parametrize(
        "name",
        ["Feine Butter", "Kaergarden Butter", "Butter-Schmalz", "MEGGLE BUTTER"],
    )
    def test_single_keyword_matches_compound_names(self, name: str) -> None:
        products = [product("lidl", name, 1.49, unit="kg", quantity=0.25)]

        assert filter_by_query(products, "butter") == products

    def test_matches_brand_without_umlauts(self) -> None:
        products = [
            product("rewe", "Streichfett", 1.99, brand="Kärgarden"),
            product("lidl", "Bauernbrot", 2.49, unit="kg", quantity=0.75),
        ]

        result = filter_by_query(products, "kaergarden")

        assert [item.name for item in result] == ["Streichfett"]

    def test_umlauts_are_folded(self) -> None:
        products = [product("lidl", "Käseaufschnitt", 1.99, unit="kg", quantity=0.2)]

        assert filter_by_query(products, "kaese") == products

    def test_fuzzy_ratio_matches_word_order_changes(self) -> None:
        products = [product("lidl", "Butter Feine Markenbutter", 1.49, unit="kg")]

        assert filter_by_query(products, "feine butter") == products

    def test_empty_query_keeps_everything(self) -> None:
        products = [product("lidl", "Bio Vollmilch", 1.29)]

        assert filter_by_query(products, "  ") == products

    def test_case_and_punctuation_insensitive(self) -> None:
        products = [product("lidl", "BIO-VOLLMILCH", 1.29)]

        assert len(filter_by_query(products, "bio vollmilch")) == 1
