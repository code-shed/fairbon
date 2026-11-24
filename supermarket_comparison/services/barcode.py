"""Lightweight Open Food Facts barcode lookup for receipt items.

Small, cached and time-bounded: a failed/offline lookup never blocks
linking an EAN manually.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from ..normalization.matcher import normalize_title

__all__ = ["AMBIGUOUS_TERMS", "is_ambiguous_term", "lookup_barcode"]

OFF_URL = "https://world.openfoodfacts.org/api/v2/product/{ean}.json"
CACHE_TTL_SECONDS = 24 * 60 * 60
TIMEOUT_SECONDS = 3.0

#: Collective receipt headings are not a single product and must not be
#: offered for a 1:1 barcode match in the quick-scan UI.
AMBIGUOUS_TERMS: frozenset[str] = frozenset(
    {
        "angebot",
        "backwaren",
        "obst gemuese",
        "obst gemaese",
        "sonstiges",
        "diverses",
        "aktuell",
        "angebote",
    }
)

_CACHE: dict[str, tuple[float, dict[str, Any] | None]] = {}


def is_ambiguous_term(name: str | None) -> bool:
    """Whether *name* is a collective heading rather than one product."""

    folded = normalize_title(name or "")
    return any(term in folded for term in AMBIGUOUS_TERMS)


async def lookup_barcode(ean: str) -> dict[str, Any] | None:
    """Return ``{name, brand, quantity, unit}`` for *ean*, or ``None``."""

    now = time.monotonic()
    cached = _CACHE.get(ean)
    if cached is not None and now - cached[0] < CACHE_TTL_SECONDS:
        return cached[1]

    result: dict[str, Any] | None = None
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
            response = await client.get(OFF_URL.format(ean=ean))
            response.raise_for_status()
            product = (response.json() or {}).get("product") or {}
            name = str(product.get("product_name") or "").strip()
            if name:
                result = {
                    "name": name,
                    "brand": str(product.get("brands") or "").strip() or None,
                    "quantity": product.get("product_quantity"),
                    "unit": (
                        str(product.get("product_quantity_unit") or "")
                        .strip()
                        .lower()
                    )
                    or None,
                }
    except Exception:  # offline / not found / bad payload -> manual fallback
        result = None

    _CACHE[ean] = (now, result)
    return result
