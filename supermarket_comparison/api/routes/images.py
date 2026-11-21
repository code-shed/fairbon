"""Product image lookup endpoint.

Only exact EAN matches against Open Food Facts are allowed — never text
lookups that could surface copyright-protected leaflet photos.  A missing
image is a normal, cacheable result (``image_url: null``).
"""

from __future__ import annotations

import re
from typing import Annotated, Any

from fastapi import APIRouter, Query, Request

from ...scrapers.openfoodfacts import OpenFoodFactsScraper

router = APIRouter(prefix="/products", tags=["products"])

_EAN_RE = re.compile(r"[0-9]{8,14}")


async def _openfoodfacts_image(ean: str) -> str | None:
    """Return the front image URL for an exact EAN, or ``None``."""

    scraper = OpenFoodFactsScraper()
    try:
        products = await scraper.fetch_offers(ean=ean)
    except Exception:  # pragma: no cover - upstream failure must not 500 the UI
        return None
    finally:
        await scraper.aclose()
    if not products:
        return None
    return getattr(products[0], "image_url", None) or None


@router.get(
    "/image",
    summary="Resolve a product image by exact EAN (Open Food Facts only)",
)
async def product_image(
    request: Request,
    ean: Annotated[
        str | None,
        Query(description="EAN/GTIN (8-14 digits)"),
    ] = None,
    name: Annotated[
        str | None,
        Query(description="Product name (ignored without a valid EAN)"),
    ] = None,
) -> dict[str, Any]:
    """Return an Open Food Facts image for a product with a valid EAN.

    Text-only lookups are deliberately disabled: images must come from a
    free-licensed source and only when the product is uniquely identified.
    """

    clean_ean = (ean or "").strip()
    if _EAN_RE.fullmatch(clean_ean) is None:
        return {
            "name": (name or "").strip() or None,
            "ean": None,
            "image_url": None,
            "source": "none",
        }

    image_url = await _openfoodfacts_image(clean_ean)
    return {
        "name": (name or "").strip() or None,
        "ean": clean_ean,
        "image_url": image_url,
        "source": "openfoodfacts" if image_url else "none",
    }


__all__ = ["router"]
