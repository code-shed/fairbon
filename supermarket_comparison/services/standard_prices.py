"""Standard prices (permanent assortment) via Open Food Facts.

Why this module exists
----------------------
The leaflet aggregator (Marktguru) only knows *promotional* prices.  The
permanent shelf price — and with it the private labels the leaflets rarely
mention (*Milbona*, *Milsani*, *Gut & Günstig*, *Balea*, *Cien*) — has to come
from another source.

Reachable sources, verified live from this environment:

===========================  ==========================================
Source                       Status
===========================  ==========================================
Rewe ``/api/v3/products``     404, shop pages behind Cloudflare 403
Edeka ``/api/products``       Akamai 403
Lidl ``/q/api/search``        401 (signed client required)
Kaufland / Netto / Aldi       Cloudflare 403
Open Prices REST API          works
OFF product search API        works
===========================  ==========================================

So the chain implemented here is:

1. **OFF search** (``search.openfoodfacts.org``) resolves a free-text query to
   real products with an EAN — private labels included.
2. **Open Prices** (``prices.openfoodfacts.org``) looks that EAN up and returns
   crowd-sourced observations with a date and a store name.

Only *observed* prices become :class:`NormalizedProduct` entries.  When Open
Prices has no price for an EAN the catalogue hit is dropped — a standard price
is never estimated or invented.  That is why German coverage is thin today:
the schema, the API and the UI are ready, the data is not (yet).
"""

from __future__ import annotations

import asyncio
import re
import time
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

import httpx

from ..config import get_settings
from ..models import NormalizedProduct
from ..normalization.normalizer import parse_quantity
from ..scrapers.base import as_float, as_text

__all__ = ["CatalogProduct", "StandardPriceService"]

#: Units accepted by Open Food Facts quantity fields.
_UNIT_ALIASES: Final[dict[str, str]] = {
    "g": "g",
    "gr": "g",
    "kg": "kg",
    "ml": "ml",
    "cl": "cl",
    "l": "l",
    "lt": "l",
}

_CATALOG_FIELDS: Final = "code,product_name,brands,quantity,categories_tags,image_url"


def _humanize(tag: str) -> str:
    """Turn ``"en:dairy-desserts"`` into ``"Dairy desserts"``."""

    text = tag.split(":", 1)[-1] if ":" in tag else tag
    words = text.replace("-", " ").replace("_", " ").strip()
    return words[:1].upper() + words[1:] if words else ""


def _slugify(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")
    return slug or "offen"


@dataclass(frozen=True)
class CatalogProduct:
    """One Open Food Facts catalogue entry."""

    ean: str
    name: str
    brand: str | None
    quantity: float | None
    unit: str | None
    category: str | None
    image_url: str | None


class _TTLCache:
    """Minimal TTL cache (successful responses only)."""

    def __init__(self) -> None:
        self._data: dict[str, tuple[float, Any]] = {}

    def get(self, key: str) -> Any | None:
        entry = self._data.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if expires_at < time.monotonic():
            self._data.pop(key, None)
            return None
        return value

    def set(self, key: str, value: Any, ttl: float) -> None:
        if ttl > 0:
            self._data[key] = (time.monotonic() + ttl, value)

    def clear(self) -> None:
        self._data.clear()


class StandardPriceService:
    """Resolve free-text queries to catalogue products and their shelf prices."""

    def __init__(
        self,
        *,
        cache_ttl: float | None = None,
        limit: int | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        settings = get_settings()
        self.search_url = settings.openfoodfacts_search_url.rstrip("/")
        self.prices_url = settings.openprices_base_url.rstrip("/")
        self.cache_ttl = (
            float(settings.standard_price_cache_ttl)
            if cache_ttl is None
            else float(cache_ttl)
        )
        self.limit = int(limit or settings.standard_price_limit)
        self._client = client
        self._owns_client = client is None
        self._cache = _TTLCache()
        self._headers = {
            "Accept": "application/json",
            "User-Agent": settings.http_user_agent,
        }

    # -- plumbing ---------------------------------------------------------
    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                headers=self._headers,
                timeout=get_settings().http_timeout,
                follow_redirects=True,
            )
        return self._client

    async def aclose(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    close = aclose

    def clear_cache(self) -> None:
        self._cache.clear()

    # -- catalogue --------------------------------------------------------
    async def search_catalog(
        self, query: str, *, limit: int | None = None
    ) -> list[CatalogProduct]:
        """Resolve *query* to catalogue products with an EAN."""

        term = (query or "").strip()
        if not term:
            return []

        size = max(1, int(limit or self.limit))
        key = f"catalog:{term.lower()}:{size}"
        cached = self._cache.get(key)
        if cached is not None:
            return cached

        response = await self._http().get(
            f"{self.search_url}/search",
            params={"q": term, "page_size": size, "fields": _CATALOG_FIELDS},
        )
        response.raise_for_status()
        payload = response.json()
        hits = payload.get("hits") if isinstance(payload, Mapping) else None

        products = [
            product
            for product in (self._parse_hit(hit) for hit in (hits or []))
            if product is not None
        ]
        self._cache.set(key, products, self.cache_ttl)
        return products

    @classmethod
    def _parse_hit(cls, hit: Any) -> CatalogProduct | None:
        if not isinstance(hit, Mapping):
            return None
        ean = as_text(hit.get("code"))
        name = as_text(hit.get("product_name"))
        if not ean or not name:
            return None

        brands = hit.get("brands")
        if isinstance(brands, list):
            brand = ", ".join(str(item) for item in brands if item) or None
        else:
            brand = as_text(brands)

        quantity: float | None = None
        unit: str | None = None
        parsed = parse_quantity(as_text(hit.get("quantity")) or "")
        if parsed is not None:
            quantity, unit = parsed.quantity, parsed.unit

        categories = hit.get("categories_tags")
        category = None
        if isinstance(categories, list):
            for tag in categories:
                if isinstance(tag, str) and tag.strip():
                    category = _humanize(tag.strip())
                    break

        return CatalogProduct(
            ean=ean,
            name=name,
            brand=brand,
            quantity=quantity,
            unit=unit,
            category=category,
            image_url=as_text(hit.get("image_url")),
        )

    # -- prices -----------------------------------------------------------
    async def prices_for_ean(
        self,
        ean: str,
        *,
        postal_code: str | None = None,
        country: str = "DE",
    ) -> list[NormalizedProduct]:
        """Return observed Open Prices rows for *ean*, filtered to one country.

        Open Prices has no server-side country filter, but every observation
        carries the OSM address of the shop including ``osm_address_country_code``
        and ``osm_address_postcode``.  Observations from the same postal-code
        region are preferred; otherwise the newest national observation per
        store is used.
        """

        code = (ean or "").strip()
        if not code:
            return []

        key = f"prices:{code}:{country}:{postal_code or ''}"
        cached = self._cache.get(key)
        if cached is not None:
            return cached

        response = await self._http().get(
            f"{self.prices_url}/api/v1/prices",
            params={"product_code": code, "size": 50, "order_by": "-date"},
        )
        response.raise_for_status()
        payload = response.json()
        items = payload.get("items") if isinstance(payload, Mapping) else None

        parsed = [
            product
            for product in (
                self._parse_price(item, country=country) for item in (items or [])
            )
            if product is not None
        ]
        products = _select_observations(parsed, postal_code=postal_code)
        self._cache.set(key, products, self.cache_ttl)
        return products

    @classmethod
    def _parse_price(cls, raw: Any, *, country: str = "DE") -> NormalizedProduct | None:
        if not isinstance(raw, Mapping):
            return None

        location = (
            raw.get("location") if isinstance(raw.get("location"), Mapping) else {}
        )
        if country:
            code_of_country = as_text(location.get("osm_address_country_code"))
            if code_of_country and code_of_country.upper() != country.upper():
                return None

        product = raw.get("product") if isinstance(raw.get("product"), Mapping) else {}
        name = as_text(product.get("product_name"))
        price = as_float(raw.get("price"))
        price_id = as_text(raw.get("id"))
        if not name or price is None or price < 0 or not price_id:
            return None

        store = _slugify(as_text(location.get("osm_name")) or "offen")

        unit_raw = as_text(product.get("product_quantity_unit"))
        unit = _UNIT_ALIASES.get((unit_raw or "").lower(), unit_raw)
        observed = as_text(raw.get("date")) or as_text(raw.get("created"))

        categories = product.get("categories_tags")
        category = None
        if isinstance(categories, list):
            for tag in categories:
                if isinstance(tag, str) and tag.strip():
                    category = _humanize(tag.strip())
                    break

        return NormalizedProduct(
            id=f"std-{price_id}",
            store=store,
            name=name,
            brand=as_text(product.get("brands")),
            ean=as_text(product.get("code")) or as_text(raw.get("product_code")),
            price=price,
            old_price=None,
            quantity=as_float(product.get("product_quantity")) or 1.0,
            unit=unit or "stueck",
            unit_price=as_float(raw.get("price_per_unit")),
            category=category,
            # Standard prices have no leaflet window; the observation date is
            # kept so the UI can show how old the price is.
            valid_from=observed,
            valid_to=None,
            image_url=as_text(product.get("image_url")),
            store_branch_id=as_text(raw.get("location_id")),
            postal_code=as_text(location.get("osm_address_postcode")),
            offer_type="standard",
            source="openprices",
        )

    # -- combined ---------------------------------------------------------
    async def search(
        self,
        query: str,
        *,
        limit: int | None = None,
        postal_code: str | None = None,
    ) -> list[NormalizedProduct]:
        """Return priced standard-assortment products for *query*.

        Catalogue hits without a price observation are dropped: the result set
        only ever contains real, observed prices.
        """

        catalog = await self.search_catalog(query, limit=limit)
        if not catalog:
            return []

        semaphore = asyncio.Semaphore(5)

        async def resolve(item: CatalogProduct) -> list[NormalizedProduct]:
            async with semaphore:
                try:
                    return await self.prices_for_ean(item.ean, postal_code=postal_code)
                except (httpx.HTTPError, ValueError):
                    return []

        batches = await asyncio.gather(*(resolve(item) for item in catalog))
        return [offer for batch in batches for offer in batch]


def _select_observations(
    offers: list[NormalizedProduct], *, postal_code: str | None = None
) -> list[NormalizedProduct]:
    """Pick the newest observation per store, preferring the local PLZ region.

    Open Prices returns worldwide observations for an EAN.  For a German
    postal code we prefer shops in the same two-digit region, then any other
    German shop, and finally whatever is left (never mixed across stores).
    """

    if not offers:
        return []

    region = (postal_code or "").strip()[:2]
    by_store: dict[str, list[NormalizedProduct]] = {}
    for offer in offers:
        by_store.setdefault(offer.store, []).append(offer)

    selected: list[NormalizedProduct] = []
    for store_offers in by_store.values():
        local = [
            offer
            for offer in store_offers
            if region and _postcode_of(offer).startswith(region)
        ]
        pool = local or store_offers
        selected.append(max(pool, key=_observed_key))
    return selected


def _postcode_of(offer: NormalizedProduct) -> str:
    """Postal code of the shop the observation belongs to (may be empty)."""

    return (offer.postal_code or "").strip()


def _observed_key(offer: NormalizedProduct) -> tuple[str, str]:
    return (offer.valid_from or "", _postcode_of(offer))
