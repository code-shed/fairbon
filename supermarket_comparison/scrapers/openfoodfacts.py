"""Open Food Facts — Open Prices client.

``https://prices.openfoodfacts.org`` is a *crowd-sourced* price database: users
upload receipts/photos and the products are linked to Open Food Facts by
EAN/GTIN.  Coverage for Germany is sparse and skewed towards whatever the
community happened to photograph — a search can legitimately return zero
prices.

Because Open Prices has **no full-text name search**, this client only answers
EAN lookups (``?product_code={ean}&size=20``).  Free-text queries return an
empty list so text search results are not polluted with unrelated products.

Verified endpoint::

    GET https://prices.openfoodfacts.org/api/v1/prices?product_code=4075600000000
    -> {"items": [...], "page": 1, "pages": 1, "size": 20, "total": 3}
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, ClassVar, Final

from ..models import NormalizedProduct
from .base import BaseScraper, as_float, as_text, extract_items, looks_like_ean, slugify

#: Open Prices units mapped to the units understood by the normalizer.
_UNIT_ALIASES: Final[dict[str, str]] = {
    "g": "g",
    "gr": "g",
    "gramm": "g",
    "kg": "kg",
    "kilogramm": "kg",
    "ml": "ml",
    "milliliter": "ml",
    "cl": "cl",
    "l": "l",
    "lt": "l",
    "liter": "l",
    "litre": "l",
}


def _humanize_tag(tag: str) -> str:
    """Turn ``"en:dairy-desserts"`` into ``"Dairy desserts"``."""

    text = tag.split(":", 1)[-1] if ":" in tag else tag
    words = text.replace("-", " ").replace("_", " ").strip()
    return words[:1].upper() + words[1:] if words else ""


class OpenFoodFactsScraper(BaseScraper):
    """Client for the crowd-sourced Open Prices database (EAN lookups only)."""

    store = "openfoodfacts"
    base_url: ClassVar[str] = "https://prices.openfoodfacts.org"

    prices_path: ClassVar[str] = "/api/v1/prices"
    page_size: ClassVar[int] = 20

    def _headers(self) -> dict[str, str]:
        return {
            "Accept": "application/json",
            "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
        }

    @classmethod
    def _store_of(cls, raw: Mapping[str, Any]) -> str:
        location = raw.get("location")
        osm_name = (
            as_text(location.get("osm_name")) if isinstance(location, Mapping) else None
        )
        return slugify(osm_name) if osm_name else cls.store

    @staticmethod
    def _category_of(product: Mapping[str, Any]) -> str | None:
        tags = product.get("categories_tags")
        if isinstance(tags, list):
            for tag in tags:
                if isinstance(tag, str) and tag.strip():
                    return _humanize_tag(tag.strip())
        return as_text(product.get("categories"))

    @staticmethod
    def _unit_of(product: Mapping[str, Any]) -> str | None:
        unit = as_text(product.get("product_quantity_unit"))
        if not unit:
            return None
        return _UNIT_ALIASES.get(unit.strip().lower(), unit.strip().lower())

    @classmethod
    def parse_price(cls, raw: Any) -> NormalizedProduct | None:
        """Map one Open Prices record to :class:`NormalizedProduct`."""

        if not isinstance(raw, Mapping):
            return None

        product = raw.get("product")
        product = product if isinstance(product, Mapping) else {}

        name = as_text(product.get("product_name")) or as_text(raw.get("product_name"))
        price = as_float(raw.get("price"))
        price_id = as_text(raw.get("id"))
        if not name or price is None or price < 0 or not price_id:
            return None

        unit = cls._unit_of(product)
        quantity = as_float(product.get("product_quantity"))
        if quantity is None:
            quantity = as_float(raw.get("product_quantity"))

        unit_price = as_float(raw.get("price_per_unit"))
        date = as_text(raw.get("date")) or as_text(raw.get("created"))

        return NormalizedProduct(
            id=f"off-{price_id}",
            store=cls._store_of(raw),
            name=name,
            brand=as_text(product.get("brands")) or as_text(raw.get("brands")),
            ean=as_text(product.get("code")) or as_text(raw.get("product_code")),
            price=price,
            old_price=as_float(raw.get("price_without_discount"))
            if raw.get("price_is_discounted")
            else None,
            quantity=quantity if quantity is not None else 1.0,
            unit=unit or "stueck",
            # ``price_per_unit`` is optional; the model derives it otherwise.
            unit_price=unit_price,
            category=cls._category_of(product),
            valid_from=date,
            valid_to=date,
            image_url=as_text(product.get("image_url")),
            store_branch_id=as_text(raw.get("location_id")),
        )

    async def fetch_offers(
        self,
        *,
        postal_code: str | None = None,
        query: str | None = None,
        ean: str | None = None,
    ) -> list[NormalizedProduct]:
        """Return Open Prices entries for *ean* (never for free text)."""

        code = ean or (query if query and looks_like_ean(query) else None)
        if not code:
            # Open Prices has no name search: do not pollute text results.
            return []

        payload = await self.get_json(
            self.prices_path,
            params={"product_code": code, "size": self.page_size},
            headers=self._headers(),
        )
        items = extract_items(payload, "items", "results")
        return [
            product
            for product in (self.parse_price(item) for item in items)
            if product is not None
        ]


__all__ = ["OpenFoodFactsScraper"]
