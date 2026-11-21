"""Normalisation helpers (quantity/unit parsing, pricing, matching)."""

from __future__ import annotations

from .matcher import (
    ProductGroup,
    deduplicate,
    filter_by_query,
    group_products,
    match_products,
    normalize_ean,
    normalize_title,
    title_similarity,
)
from .normalizer import (
    CANONICAL_UNITS,
    COUNT,
    MASS,
    UNIT_KG,
    UNIT_L,
    UNIT_STUECK,
    UNKNOWN,
    VOLUME,
    ParsedQuantity,
    calculate_discount_percent,
    calculate_unit_price,
    normalize_unit,
    parse_decimal,
    parse_quantity,
    to_canonical,
    unit_family,
)

__all__ = [
    "CANONICAL_UNITS",
    "COUNT",
    "MASS",
    "UNIT_KG",
    "UNIT_L",
    "UNIT_STUECK",
    "UNKNOWN",
    "VOLUME",
    "ParsedQuantity",
    "ProductGroup",
    "calculate_discount_percent",
    "calculate_unit_price",
    "deduplicate",
    "filter_by_query",
    "group_products",
    "match_products",
    "normalize_ean",
    "normalize_title",
    "normalize_unit",
    "parse_decimal",
    "parse_quantity",
    "title_similarity",
    "to_canonical",
    "unit_family",
]
