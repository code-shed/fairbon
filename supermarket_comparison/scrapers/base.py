"""Shared HTTP plumbing and defensive parsing helpers for all clients.

The supermarket APIs are undocumented and their payloads change frequently.
Instead of hard-coding one exact response shape, the helpers in this module
accept the common aliases used by Lidl, Edeka, Rewe, Marktguru and Open
Prices.  Every scraper therefore only needs to describe *where* a value may
live; :func:`make_product` turns it into a :class:`NormalizedProduct`.
"""

from __future__ import annotations

import hashlib
import math
import re
import unicodedata
from abc import ABC, abstractmethod
from collections.abc import Mapping
from datetime import date, datetime
from typing import Any, ClassVar, Final, Self

import httpx

from ..config import get_settings
from ..models import NormalizedProduct, StoreBranch
from ..normalization.normalizer import parse_decimal, parse_quantity, to_canonical

#: Keys that may hold a numeric price inside a nested object.
_PRICE_KEYS: Final[tuple[str, ...]] = (
    "price",
    "currentPrice",
    "currentRetailPrice",
    "sellingPrice",
    "offerPrice",
    "unitPrice",
    "grossPrice",
    "gross",
    "amount",
    "value",
    "regularPrice",
    "oldPrice",
    "oldRetailPrice",
)

#: Keys that may hold a list of records in an API envelope.
_ITEM_KEYS: Final[tuple[str, ...]] = (
    "items",
    "results",
    "data",
    "content",
    "offers",
    "products",
    "records",
    "hits",
    "entries",
    "markets",
    "stores",
    "branches",
    "categories",
)

_TEXT_KEYS: Final[tuple[str, ...]] = (
    "name",
    "title",
    "text",
    "value",
    "displayName",
    "label",
    "productName",
    "storeName",
    "marketName",
)

_IMAGE_KEYS: Final[tuple[str, ...]] = (
    "url",
    "src",
    "href",
    "image",
    "imageUrl",
    "imageURL",
    "image_url",
    "downloadUrl",
    "path",
)

_EAN_RE: Final = re.compile(r"[\s\-]")
_DIGITS_RE: Final = re.compile(r"^\d+$")
_UMLAUTS: Final[dict[str, str]] = {
    "ä": "ae", "ö": "oe", "ü": "ue",
    "Ä": "Ae", "Ö": "Oe", "Ü": "Ue",
    "ß": "ss",
}
_NON_SLUG_RE: Final = re.compile(r"[^a-z0-9]+")


def slugify(value: Any) -> str:
    """Return a lower-case ASCII slug (``"ALDI SÜD"`` -> ``"aldi-sued"``)."""

    text = as_text(value) or ""
    for umlaut, replacement in _UMLAUTS.items():
        text = text.replace(umlaut, replacement)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(char for char in text if not unicodedata.combining(char))
    return _NON_SLUG_RE.sub("-", text.lower()).strip("-")


_QUANTITY_UNIT_RE: Final = re.compile(
    r"\d\s*(?:st|stk|stck|stueck|stück|pc|pcs|piece|pieces)\b", re.IGNORECASE
)


def dig(data: Any, path: str, default: Any = None) -> Any:
    """Return a nested value using a dotted *path* (``"address.city"``)."""

    current = data
    for part in path.split("."):
        if isinstance(current, Mapping):
            if part not in current:
                return default
            current = current[part]
        elif isinstance(current, (list, tuple)):
            if not part.isdigit():
                return default
            index = int(part)
            if index >= len(current):
                return default
            current = current[index]
        else:
            return default
    return current


def pick_paths(data: Any, *paths: str, default: Any = None) -> Any:
    """Return the first path in *paths* that contains a usable value."""

    for path in paths:
        value = dig(data, path)
        if value is None or value == "":
            continue
        if isinstance(value, (list, tuple, dict)) and not value:
            continue
        return value
    return default


def as_text(value: Any) -> str | None:
    """Coerce a scalar or a ``{"name": ...}`` style object to a string."""

    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str):
        text = value.strip()
        return text or None
    if isinstance(value, (int, float)):
        if isinstance(value, float):
            return f"{value:g}"
        return str(value)
    if isinstance(value, Mapping):
        for key in _TEXT_KEYS:
            if key in value:
                text = as_text(value[key])
                if text:
                    return text
        return None
    if isinstance(value, (list, tuple)):
        for item in value:
            text = as_text(item)
            if text:
                return text
    return None


def as_float(value: Any) -> float | None:
    """Coerce a scalar to a finite float (``None`` on failure)."""

    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    if isinstance(value, str):
        return parse_decimal(value)
    return None


def as_price(value: Any, _depth: int = 0) -> float | None:
    """Extract a price from a number, a German price string or nested object."""

    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    if isinstance(value, str):
        return parse_decimal(value)
    if _depth >= 4:
        return None
    if isinstance(value, Mapping):
        for key in _PRICE_KEYS:
            if key in value:
                parsed = as_price(value[key], _depth + 1)
                if parsed is not None:
                    return parsed
        for nested in value.values():
            parsed = as_price(nested, _depth + 1)
            if parsed is not None:
                return parsed
        return None
    if isinstance(value, (list, tuple)):
        for item in value:
            parsed = as_price(item, _depth + 1)
            if parsed is not None:
                return parsed
    return None


def as_ean(value: Any) -> str | None:
    """Normalise an EAN/GTIN by stripping whitespace and hyphens."""

    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    text = as_text(value)
    if not text:
        return None
    cleaned = _EAN_RE.sub("", text)
    return cleaned or None


def looks_like_ean(value: Any) -> bool:
    """Return ``True`` for an 8-14 digit GTIN/EAN string."""

    ean = as_ean(value)
    return bool(ean and _DIGITS_RE.match(ean) and 8 <= len(ean) <= 14)


def as_image_url(value: Any) -> str | None:
    """Extract an image URL from a string, list or image object."""

    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str):
        text = value.strip()
        return text or None
    if isinstance(value, Mapping):
        for key in _IMAGE_KEYS:
            if key in value:
                text = as_image_url(value[key])
                if text:
                    return text
        return None
    if isinstance(value, (list, tuple)):
        for item in value:
            text = as_image_url(item)
            if text:
                return text
    return None


def as_date(value: Any) -> str | None:
    """Return an ISO date/datetime string from common API representations."""

    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, (int, float)):
        timestamp = float(value)
        if timestamp > 1e11:  # milliseconds since epoch
            timestamp /= 1000.0
        if timestamp > 0:
            try:
                return datetime.fromtimestamp(timestamp).isoformat()
            except (OverflowError, OSError, ValueError):
                return None
        return None
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, Mapping):
        return as_date(pick_paths(value, "date", "value", "startDate", "endDate"))
    return None


def extract_items(payload: Any, *keys: str, _depth: int = 0) -> list[Any]:
    """Find the list of records in an API envelope.

    Recursively looks through the explicit *keys* first and then through the
    common envelope keys (``data``, ``items``, ``results``, ...).  The
    ``_embedded`` container used by HAL-style APIs is supported as well.
    """

    if isinstance(payload, list):
        return payload
    if not isinstance(payload, Mapping) or _depth >= 4:
        return []

    for key in (*keys, *_ITEM_KEYS):
        if key not in payload:
            continue
        value = payload[key]
        if isinstance(value, list):
            return value
        if isinstance(value, Mapping):
            nested = extract_items(value, *keys, _depth=_depth + 1)
            if nested:
                return nested

    embedded = payload.get("_embedded")
    if isinstance(embedded, Mapping):
        for value in embedded.values():
            if isinstance(value, list):
                return value
            if isinstance(value, Mapping):
                nested = extract_items(value, *keys, _depth=_depth + 1)
                if nested:
                    return nested

    return []


def parse_size(value: Any, unit: Any = None) -> tuple[float, str]:
    """Return ``(quantity, canonical_unit)`` for a package size.

    Strings are parsed with :func:`parse_quantity` so multipacks such as
    ``"6 x 0,33 l"`` are handled correctly.  When the caller supplies a unit
    and the value is only a bare number, the caller's unit wins.
    """

    if isinstance(value, Mapping):
        inner_unit = pick_paths(
            value, "unit", "unitOfMeasure", "quantityUnit", "value.unit"
        )
        inner_value = pick_paths(value, "value", "amount", "quantity", "size")
        return parse_size(inner_value, inner_unit if inner_unit is not None else unit)

    if isinstance(value, (list, tuple)):
        if not value:
            return 1.0, "stueck"
        return parse_size(value[0], unit)

    unit_text = as_text(unit)

    if isinstance(value, str):
        parsed = parse_quantity(value)
        if parsed is not None:
            # ``"1,5"`` + caller unit ``"l"`` must not become 1.5 pieces.
            if (
                unit_text
                and parsed.unit == "stueck"
                and not _QUANTITY_UNIT_RE.search(value)
            ):
                number = parse_decimal(value)
                if number is not None and number > 0:
                    canonical, canonical_unit = to_canonical(number, unit_text)
                    return round(canonical, 6), canonical_unit
            if parsed.quantity > 0:
                return parsed.quantity, parsed.unit

    number = parse_decimal(value)
    if number is not None and number > 0:
        if unit_text:
            canonical, canonical_unit = to_canonical(number, unit_text)
            return round(canonical, 6), canonical_unit
        return round(number, 6), "stueck"

    if unit_text and value is not None:
        canonical, canonical_unit = to_canonical(1.0, unit_text)
        return round(canonical, 6), canonical_unit

    return 1.0, "stueck"


def _stable_id(store: str, *parts: Any) -> str:
    """Build a deterministic, store-prefixed product id."""

    for part in parts:
        text = as_text(part)
        if text:
            return text if text.startswith(f"{store}-") else f"{store}-{text}"
    digest = hashlib.sha1(
        "|".join(str(part) for part in parts if part is not None).encode("utf-8")
    ).hexdigest()[:16]
    return f"{store}-{digest}"


def make_product(
    store: str,
    raw: Mapping[str, Any],
    *,
    name: Any = None,
    price: Any = None,
    old_price: Any = None,
    quantity: Any = None,
    unit: Any = None,
    ean: Any = None,
    brand: Any = None,
    category: Any = None,
    image_url: Any = None,
    valid_from: Any = None,
    valid_to: Any = None,
    branch_id: Any = None,
    product_id: Any = None,
    fallback_name: str | None = None,
) -> NormalizedProduct | None:
    """Build a :class:`NormalizedProduct` from a loosely typed API record.

    Returns ``None`` when the record lacks a usable name or price.
    """

    if not isinstance(raw, Mapping):
        return None

    display_name = as_text(name) or as_text(
        pick_paths(
            raw,
            "name",
            "title",
            "productName",
            "displayName",
            "product.name",
            "product.title",
            "product.product_name",
        )
    )
    if not display_name:
        display_name = fallback_name
    if not display_name:
        return None

    price_value = as_price(
        price
        if price is not None
        else pick_paths(
            raw,
            "price",
            "currentPrice",
            "offerPrice",
            "sellingPrice",
            "listing.currentRetailPrice",
            "product.price",
        )
    )
    if price_value is None or price_value < 0:
        return None

    old_price_value = as_price(
        old_price
        if old_price is not None
        else pick_paths(
            raw,
            "oldPrice",
            "old_price",
            "regularPrice",
            "listing.oldRetailPrice",
            "product.oldPrice",
            "price.oldPrice",
        )
    )
    if old_price_value is not None and old_price_value <= price_value:
        old_price_value = None

    quantity_value = (
        quantity
        if quantity is not None
        else pick_paths(
            raw,
            "quantity",
            "size",
            "content",
            "subtitle",
            "amount",
            "product.quantity",
            "product.size",
            "product.product_quantity",
        )
    )
    unit_value = (
        unit
        if unit is not None
        else pick_paths(
            raw,
            "unit",
            "quantityUnit",
            "unitOfMeasure",
            "amount.unit",
            "product.unit",
            "product.quantity_unit",
        )
    )
    quantity_value, unit_value = parse_size(quantity_value, unit_value)

    ean_value = as_ean(
        ean
        if ean is not None
        else pick_paths(
            raw,
            "ean",
            "gtin",
            "productCode",
            "product.ean",
            "product.gtin",
            "product.product_code",
        )
    )

    raw_id = as_text(product_id) or as_text(
        pick_paths(
            raw,
            "id",
            "itemId",
            "offerId",
            "productId",
            "sku",
            "code",
            "product.id",
        )
    )

    return NormalizedProduct(
        id=_stable_id(store, raw_id, ean_value, display_name),
        store=store,
        name=display_name,
        brand=as_text(
            brand
            if brand is not None
            else pick_paths(raw, "brand", "brandName", "product.brand")
        ),
        ean=ean_value,
        price=price_value,
        old_price=old_price_value,
        unit=unit_value,
        quantity=quantity_value,
        category=as_text(
            category
            if category is not None
            else pick_paths(
                raw, "category", "categoryName", "product.category", "categories"
            )
        ),
        valid_from=as_date(
            valid_from
            if valid_from is not None
            else pick_paths(
                raw, "validFrom", "startDate", "offerStartDate", "valid_from"
            )
        ),
        valid_to=as_date(
            valid_to
            if valid_to is not None
            else pick_paths(raw, "validTo", "endDate", "offerEndDate", "valid_to")
        ),
        image_url=as_image_url(
            image_url
            if image_url is not None
            else pick_paths(
                raw,
                "image",
                "imageUrl",
                "imageURL",
                "image_url",
                "picture",
                "product.image",
            )
        ),
        store_branch_id=as_text(
            branch_id
            if branch_id is not None
            else pick_paths(raw, "storeId", "marketId", "branchId", "store.id")
        ),
    )


def _postal_text(value: Any) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else str(value)
    return as_text(value)


def make_branch(
    store: str,
    raw: Mapping[str, Any],
    *,
    branch_id: Any = None,
    name: Any = None,
    address: Any = None,
    postal_code: Any = None,
    city: Any = None,
    latitude: Any = None,
    longitude: Any = None,
    distance_km: Any = None,
) -> StoreBranch | None:
    """Build a :class:`StoreBranch` from a loosely typed store record."""

    if not isinstance(raw, Mapping):
        return None

    branch_id_value = as_text(branch_id) or as_text(
        pick_paths(
            raw,
            "id",
            "storeId",
            "store_id",
            "marketId",
            "market_id",
            "branchId",
            "branch_id",
            "wcsStoreId",
            "storeNumber",
            "number",
        )
    )
    display_name = as_text(name) or as_text(
        pick_paths(
            raw,
            "name",
            "storeName",
            "marketName",
            "displayName",
            "title",
            "companyName",
        )
    )
    if not branch_id_value or not display_name:
        return None

    address_value = (
        address
        if address is not None
        else pick_paths(
            raw,
            "address",
            "street",
            "streetAddress",
            "addressLine",
            "addressLine1",
            "formattedAddress",
        )
    )

    street = ""
    if isinstance(address_value, Mapping):
        street = (
            as_text(
                pick_paths(
                    address_value,
                    "street",
                    "streetName",
                    "addressLine",
                    "addressLine1",
                    "line1",
                    "name",
                )
            )
            or ""
        )
        house_number = as_text(
            pick_paths(address_value, "houseNumber", "house_number", "number")
        )
        if house_number and street and house_number not in street:
            street = f"{street} {house_number}".strip()
        if not street:
            street = (
                as_text(
                    pick_paths(
                        address_value,
                        "formatted",
                        "displayAddress",
                        "fullAddress",
                        "label",
                    )
                )
                or ""
            )
    else:
        street = as_text(address_value) or ""

    postal_value = (
        postal_code
        if postal_code is not None
        else pick_paths(
            raw,
            "postalCode",
            "postal_code",
            "zip",
            "zipCode",
            "plz",
            "postcode",
            "address.postalCode",
            "address.zip",
            "address.zipCode",
        )
    )
    city_value = (
        city
        if city is not None
        else pick_paths(
            raw,
            "city",
            "town",
            "place",
            "address.city",
            "address.town",
            "address.place",
        )
    )
    if not city_value and isinstance(address_value, str):
        match = re.search(r"\b\d{4,5}\s+([^,]+)$", address_value)
        if match is not None:
            city_value = match.group(1).strip()

    postal_text = _postal_text(postal_value)
    if not postal_text and isinstance(address_value, str):
        match = re.search(r"\b(\d{4,5})\b", address_value)
        if match is not None:
            postal_text = match.group(1)
    city_text = as_text(city_value)
    if not postal_text or not city_text:
        return None

    latitude_value = as_float(
        latitude
        if latitude is not None
        else pick_paths(
            raw,
            "latitude",
            "lat",
            "location.lat",
            "location.latitude",
            "coordinates.lat",
            "coordinates.latitude",
            "geo.lat",
        )
    )
    longitude_value = as_float(
        longitude
        if longitude is not None
        else pick_paths(
            raw,
            "longitude",
            "lon",
            "lng",
            "location.lon",
            "location.lng",
            "location.longitude",
            "coordinates.lon",
            "coordinates.lng",
            "coordinates.longitude",
            "geo.lon",
        )
    )
    distance_value = as_float(
        distance_km
        if distance_km is not None
        else pick_paths(raw, "distance", "distanceKm", "distance_km", "distanceInKm")
    )

    try:
        return StoreBranch(
            store=store,
            branch_id=branch_id_value,
            name=display_name,
            address=street,
            postal_code=postal_text,
            city=city_text,
            latitude=latitude_value,
            longitude=longitude_value,
            distance_km=distance_value,
        )
    except ValueError:
        # Invalid coordinates or a malformed branch record: skip it rather
        # than aborting the whole store lookup.
        return None


class BaseScraper(ABC):
    """Common HTTP plumbing for the store-specific scrapers.

    Parameters
    ----------
    client:
        Optional injected :class:`httpx.AsyncClient` (useful for tests). An
        injected client is never closed by the scraper.
    timeout:
        Request timeout in seconds; defaults to ``settings.http_timeout``.
    user_agent:
        Override for the default browser-like user agent.
    headers:
        Additional default headers merged into every request.
    """

    store: ClassVar[str] = "unknown"
    base_url: ClassVar[str] = ""

    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        timeout: float | None = None,
        user_agent: str | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        settings = get_settings()
        self._owns_client = client is None
        self._default_headers: dict[str, str] = {
            "User-Agent": user_agent or settings.http_user_agent,
            "Accept": "application/json, text/html;q=0.9,*/*;q=0.8",
            "Accept-Language": f"{settings.default_language},en;q=0.8",
        }
        if headers:
            self._default_headers.update(headers)
        self._client = client or httpx.AsyncClient(
            timeout=timeout if timeout is not None else settings.http_timeout,
            follow_redirects=True,
        )

    @property
    def client(self) -> httpx.AsyncClient:
        """The underlying HTTP client."""

        return self._client

    @property
    def default_headers(self) -> dict[str, str]:
        """A copy of the headers sent with every request."""

        return dict(self._default_headers)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """Close the HTTP client if the scraper owns it."""

        if self._owns_client and not self._client.is_closed:
            await self._client.aclose()

    def url_for(self, path: str) -> str:
        """Resolve *path* against :attr:`base_url` (absolute URLs pass through)."""

        if path.startswith(("http://", "https://")):
            return path
        return f"{self.base_url.rstrip('/')}/{path.lstrip('/')}"

    async def request_json(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        json: Any = None,
    ) -> Any:
        """Send a request and decode the JSON response, raising on errors."""

        request_headers = {**self._default_headers, **(headers or {})}
        response = await self._client.request(
            method,
            self.url_for(path),
            params=dict(params) if params is not None else None,
            headers=request_headers,
            json=json,
        )
        response.raise_for_status()
        return response.json()

    async def get_json(
        self,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Any:
        """GET *path* and decode the JSON response."""

        return await self.request_json("GET", path, params=params, headers=headers)

    async def get_text(
        self,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> str:
        """GET *path* and return the response body as text."""

        response = await self._client.get(
            self.url_for(path),
            params=dict(params) if params is not None else None,
            headers={**self._default_headers, **(headers or {})},
        )
        response.raise_for_status()
        return response.text

    @abstractmethod
    async def fetch_offers(
        self,
        *,
        postal_code: str | None = None,
        query: str | None = None,
        ean: str | None = None,
    ) -> list[NormalizedProduct]:
        """Return the current offers for this store."""

    async def fetch_stores(
        self,
        *,
        postal_code: str | None = None,
        limit: int = 50,
    ) -> list[StoreBranch]:
        """Return physical branches near *postal_code* (if supported)."""

        return []


__all__ = [
    "BaseScraper",
    "as_date",
    "as_ean",
    "as_float",
    "as_image_url",
    "as_price",
    "as_text",
    "dig",
    "extract_items",
    "looks_like_ean",
    "make_branch",
    "make_product",
    "parse_size",
    "pick_paths",
    "slugify",
]
