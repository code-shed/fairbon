"""Tests for the three-tier relevance engine (Butter vs. Buttermilch)."""

from __future__ import annotations

import pytest

from supermarket_comparison.models import NormalizedProduct
from supermarket_comparison.normalization.relevance import (
    MODIFIER_EXCEPTIONS,
    SCORE_CATEGORY,
    SCORE_COMPOUND,
    SCORE_EXACT,
    SCORE_MODIFIER,
    TIER_CATEGORY,
    TIER_EXACT,
    TIER_MODIFIER,
    apply_exclusions,
    has_token,
    keyword_stats,
    quick_filters,
    rank_products,
    score_product,
)

NAMES = [
    "Butter",
    "Deutsche Markenbutter",
    "Süßrahmbutter",
    "Kerrygold Butter",
    "Buttermilch",
    "Reine Buttermilch",
    "Butterkekse",
    "Leibniz Butterkekse",
    "Erdnussbutter",
    "Buttergemüse",
    "Kakaobutter",
]


def product(name: str, price: float = 1.99, **kwargs: object) -> NormalizedProduct:
    return NormalizedProduct(
        id=f"p-{name}",
        store="lidl",
        name=name,
        price=price,
        **kwargs,
    )


@pytest.fixture
def butter_products() -> list[NormalizedProduct]:
    return [product(name, price=1.0 + index) for index, name in enumerate(NAMES)]


def by_name(scored: list) -> dict[str, int]:
    return {item.product.name: item.tier for item in scored}


def test_exact_and_compound_hits_are_tier_three(
    butter_products: list[NormalizedProduct],
) -> None:
    scored = rank_products(butter_products, "butter", include_imprecise=True)
    tiers = by_name(scored)

    for name in [
        "Butter",
        "Deutsche Markenbutter",
        "Süßrahmbutter",
        "Kerrygold Butter",
    ]:
        assert tiers[name] == TIER_EXACT, name

    assert (
        next(item for item in scored if item.product.name == "Butter").matched_as
        == "exact"
    )
    assert (
        next(item for item in scored if item.product.name == "Süßrahmbutter").matched_as
        == "compound"
    )
    assert (
        next(item for item in scored if item.product.name == "Süßrahmbutter").score
        == SCORE_COMPOUND
    )


def test_modifier_hits_are_tier_one(butter_products: list[NormalizedProduct]) -> None:
    scored = rank_products(butter_products, "butter", include_imprecise=True)
    tiers = by_name(scored)

    for name in [
        "Buttermilch",
        "Reine Buttermilch",
        "Butterkekse",
        "Leibniz Butterkekse",
        "Erdnussbutter",
        "Buttergemüse",
        "Kakaobutter",
    ]:
        assert tiers[name] == TIER_MODIFIER, name

    modifiers = [item for item in scored if item.tier == TIER_MODIFIER]
    assert all(item.matched_as == "modifier" for item in modifiers)
    assert all(item.score == SCORE_MODIFIER for item in modifiers)
    assert all(item.counter_terms for item in modifiers)


def test_exception_compounds_are_penalised() -> None:
    assert "erdnussbutter" in MODIFIER_EXCEPTIONS["butter"]
    for name in ["Erdnussbutter", "Kakaobutter"]:
        scored = score_product(product(name), "butter")
        assert scored.tier == TIER_MODIFIER
        assert scored.counter_terms


def test_precise_filter_keeps_only_tier_two_and_three(
    butter_products: list[NormalizedProduct],
) -> None:
    scored = rank_products(butter_products, "butter")

    assert scored
    assert all(item.tier >= TIER_CATEGORY for item in scored)
    assert "Buttermilch" not in {item.product.name for item in scored}
    assert "Butter" in {item.product.name for item in scored}


def test_imprecise_hits_come_after_every_precise_hit(
    butter_products: list[NormalizedProduct],
) -> None:
    scored = rank_products(butter_products, "butter", include_imprecise=True)

    tiers = [item.tier for item in scored]
    assert tiers == sorted(tiers, reverse=True)
    assert len(scored) == len(NAMES)
    first_modifier = tiers.index(TIER_MODIFIER)
    assert all(tier == TIER_EXACT for tier in tiers[:first_modifier])


def test_quick_filters_collects_compounds_with_counts(
    butter_products: list[NormalizedProduct],
) -> None:
    scored = rank_products(butter_products, "butter", include_imprecise=True)
    filters = {entry["term"]: entry["count"] for entry in quick_filters(scored)}

    assert filters == {
        "Buttermilch": 2,
        "Butterkekse": 2,
        "Erdnussbutter": 1,
        "Buttergemüse": 1,
        "Kakaobutter": 1,
    }


def test_quick_filters_preserves_original_casing(
    butter_products: list[NormalizedProduct],
) -> None:
    scored = rank_products(butter_products, "butter", include_imprecise=True)

    terms = [entry["term"] for entry in quick_filters(scored)]
    assert "Buttermilch" in terms
    assert "buttermilch" not in terms
    # Sorted by count descending.
    counts = [entry["count"] for entry in quick_filters(scored)]
    assert counts == sorted(counts, reverse=True)


def test_quick_filters_ignores_precise_hits() -> None:
    scored = rank_products([product("Markenbutter")], "butter")
    assert quick_filters(scored) == []


def test_apply_exclusions_removes_matching_names(
    butter_products: list[NormalizedProduct],
) -> None:
    kept = apply_exclusions(butter_products, ["Buttermilch"])
    names = {item.name for item in kept}

    assert "Buttermilch" not in names
    assert "Reine Buttermilch" not in names
    assert "Butter" in names
    assert "Deutsche Markenbutter" in names


def test_apply_exclusions_is_umlaut_tolerant() -> None:
    products = [product("Buttergemüse"), product("Butter")]
    kept = apply_exclusions(products, ["buttergemuse"])
    assert [item.name for item in kept] == ["Butter"]


def test_apply_exclusions_with_no_terms_is_a_noop() -> None:
    products = [product("Butter")]
    assert apply_exclusions(products, None) == products
    assert apply_exclusions(products, []) == products


def test_category_and_brand_hits_are_tier_two() -> None:
    category_product = product("Molkereiprodukt", category="Butter")
    brand_product = product("Molkereiprodukt", brand="Markenbutter")
    name_modifier = product("Buttermilch", category="Butter")

    assert score_product(category_product, "butter").tier == TIER_CATEGORY
    assert score_product(category_product, "butter").score == SCORE_CATEGORY
    assert score_product(brand_product, "butter").tier == TIER_CATEGORY
    # A modifier in the name must not be upgraded by a broad category.
    assert score_product(name_modifier, "butter").tier == TIER_MODIFIER


def test_umlaut_folding_matches_suessrahmbutter(
    butter_products: list[NormalizedProduct],
) -> None:
    scored = rank_products(butter_products, "butter")
    assert "Süßrahmbutter" in {item.product.name for item in scored}

    cheese = product("Käse")
    scored_cheese = rank_products([cheese], "kase")
    assert scored_cheese
    assert scored_cheese[0].product.name == "Käse"
    assert scored_cheese[0].tier == TIER_EXACT


def test_has_token_helper() -> None:
    assert has_token("Deutsche Markenbutter", "markenbutter")
    assert has_token("Käse", "kase")
    assert not has_token("Deutsche Markenbutter", "butter")
    assert not has_token("Buttermilch", "butter")


def test_no_match_is_tier_zero_and_dropped() -> None:
    scored = score_product(product("Bauernbrot"), "schokolade")
    assert scored.tier == 0
    assert scored.matched_as == "none"
    assert rank_products([product("Bauernbrot")], "schokolade") == []


def test_empty_query_returns_nothing() -> None:
    assert rank_products([product("Butter")], "   ") == []


def test_sorting_uses_unit_price_within_a_tier() -> None:
    cheap_unit = product("Butter A", price=4.00, quantity=1.0, unit="kg")
    expensive_unit = product("Butter B", price=1.50, quantity=0.25, unit="kg")

    scored = rank_products([expensive_unit, cheap_unit], "butter")

    assert [item.product.name for item in scored] == ["Butter A", "Butter B"]
    assert scored[0].score == SCORE_EXACT


def test_keyword_stats() -> None:
    scored = rank_products(
        [product("Butter"), product("Buttermilch")],
        "butter",
        include_imprecise=True,
    )
    assert keyword_stats(scored) == {"precise": 1, "imprecise": 1}


def test_modifier_exceptions_are_generic_for_milch_and_wein() -> None:
    assert {"butter", "milch", "wein"} <= set(MODIFIER_EXCEPTIONS)

    assert score_product(product("Milch"), "milch").tier == TIER_EXACT
    # Plant milks look like dairy milk but are a different product.
    for name in ["Kokosmilch", "Sojamilch", "Mandelmilch", "Hafermilch"]:
        scored = score_product(product(name), "milch")
        assert scored.tier == TIER_MODIFIER, name
        assert scored.counter_terms

    assert score_product(product("Rotwein"), "wein").tier == TIER_EXACT
    for name in ["Weinbrand", "Weinessig"]:
        assert score_product(product(name), "wein").tier == TIER_MODIFIER, name

    # ``Buttermilch`` is also an explicit false friend of ``butter``.
    assert "buttermilch" in MODIFIER_EXCEPTIONS["butter"]


def test_quick_filters_counts_the_full_offending_token() -> None:
    products = [
        product("Buttermilch"),
        product("Buttermilch"),
        product("Leibniz Butterkekse"),
        product("Butter"),
    ]
    scored = rank_products(products, "butter", include_imprecise=True)

    assert quick_filters(scored) == [
        {"term": "Buttermilch", "count": 2},
        {"term": "Butterkekse", "count": 1},
    ]


@pytest.mark.parametrize(
    ("name", "query"),
    [
        ("Butter-Mandel-Stollen", "butter"),
        ("Butter-Karamell-Waffeln XXL", "butter"),
        ("Butter Croissant", "butter"),
        ("Milch Reis", "milch"),
        ("Milch Schokolade", "milch"),
    ],
)
def test_spaced_compound_modifier_is_imprecise(name: str, query: str) -> None:
    """A capitalised head noun after the query turns it into a modifier.

    ``Butter-Mandel-Stollen`` is a stollen and ``Milch Reis`` is rice pudding,
    even though the query is a standalone token.  German orthography marks the
    real head noun with a capital letter, so it must not outrank real butter or
    milk.
    """

    scored = score_product(product(name), query)

    assert scored.tier == TIER_MODIFIER, name
    assert scored.counter_terms, name


@pytest.mark.parametrize(
    ("name", "query"),
    [
        ("Butter", "butter"),
        ("Beste Butter", "butter"),
        ("Kerrygold Butter 250 g", "butter"),
        ("Butter 250 g", "butter"),
        ("Butter, gesalzen", "butter"),
        ("Butter Stück", "butter"),
        ("Butter Kilo", "butter"),
        ("Fettarme Milch", "milch"),
        ("Milch 1,5 %", "milch"),
    ],
)
def test_query_stays_precise_when_it_is_the_head_noun(name: str, query: str) -> None:
    """Adjectives, units and container nouns must not demote a real hit."""

    scored = score_product(product(name), query)

    assert scored.tier >= TIER_CATEGORY, name
