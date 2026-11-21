"""Pydantic v2 models for the unified DACH supermarket product schema."""

from __future__ import annotations

import math
import re
from datetime import date, datetime
from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    computed_field,
    field_validator,
    model_validator,
)

from ..normalization.brands import clean_brand
from ..normalization.matcher import build_display_title
from ..normalization.normalizer import (
    calculate_discount_percent,
    calculate_unit_price,
    normalize_unit,
    parse_decimal,
    to_canonical,
)

_EAN_SEPARATOR_RE = re.compile(r"[\s\-]")

_NUMERIC_FIELDS = ("price", "old_price", "unit_price", "discount_percent")


def _as_number(value: Any) -> float | None:
    """Coerce ints/floats/price strings (``"1,99 €"``) to a finite float."""

    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    if isinstance(value, str):
        return parse_decimal(value)
    return None


class NormalizedProduct(BaseModel):
    """A single product offer in a store-independent representation.

    ``quantity``/``unit`` are always stored in canonical form (``kg``, ``l``
    or ``stueck``); passing ``quantity=500, unit="g"`` is accepted and
    converted to ``0.5 kg``. ``unit_price`` (EUR per kg/l) and
    ``discount_percent`` are derived automatically when missing.
    """

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    id: str = Field(min_length=1, description="Stable, source-specific product id")
    store: str = Field(
        min_length=1, description="lidl, edeka, rewe, marktguru, openfoodfacts"
    )
    name: str = Field(min_length=1, description="Product display name")
    brand: str | None = None
    description: str | None = None
    ean: str | None = Field(default=None, description="EAN/GTIN if known")
    price: float = Field(ge=0, description="Current price in EUR")
    old_price: float | None = Field(
        default=None, ge=0, description="Regular price before discount"
    )
    discount_percent: float | None = Field(default=None, ge=0, le=100)
    unit: str = Field(default="stueck", description="Canonical unit: kg, l or stueck")
    quantity: float = Field(
        default=1.0, ge=0, description="Amount in the canonical unit"
    )
    unit_price: float | None = Field(
        default=None, ge=0, description="EUR per kg or litre"
    )
    category: str | None = None
    valid_from: str | None = None
    valid_to: str | None = None
    image_url: str | None = None
    store_branch_id: str | None = None
    #: ``prospect`` = time-limited leaflet offer, ``standard`` = regular shelf
    #: price from the permanent assortment (no validity window).
    offer_type: str = Field(
        default="prospect",
        description="prospect (Prospekt-Angebot) or standard (Dauersortiment)",
    )
    #: Upstream provider slug (``marktguru``, ``openprices``, ...).
    source: str | None = None
    #: Deep link to the leaflet page of this offer, when the provider exposes
    #: one.  Never synthesised for providers that do not.
    leaflet_url: str | None = None
    #: Postal code of the shop the price was observed at (when known).
    postal_code: str | None = None

    @field_validator("offer_type", mode="before")
    @classmethod
    def _normalize_offer_type(cls, value: Any) -> str:
        if value is None:
            return "prospect"
        text = str(value).strip().lower()
        if text in {
            "standard",
            "regular",
            "shelf",
            "normal",
            "dauer",
            "dauersortiment",
        }:
            return "standard"
        return "prospect"

    @property
    def is_standard_price(self) -> bool:
        """Whether this offer is a permanent shelf price, not a leaflet deal."""

        return self.offer_type == "standard"

    @computed_field  # type: ignore[misc]
    @property
    def display_title(self) -> str:
        """Enriched display title (brand + sort/package hints)."""

        return build_display_title(self.name, self.brand, self.description)

    @field_validator("store", mode="before")
    @classmethod
    def _normalise_store(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.strip().lower()
        return value

    @field_validator("brand", mode="before")
    @classmethod
    def _clean_brand(cls, value: Any) -> str | None:
        """Drop placeholder brands such as ``thisisnobrand123``."""

        return clean_brand(value)

    @field_validator("ean", mode="before")
    @classmethod
    def _clean_ean(cls, value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, float) and value.is_integer():
            value = int(value)
        text = _EAN_SEPARATOR_RE.sub("", str(value).strip())
        return text or None

    @field_validator(*_NUMERIC_FIELDS, mode="before")
    @classmethod
    def _parse_numeric(cls, value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, str):
            return parse_decimal(value)
        return value

    @field_validator("valid_from", "valid_to", mode="before")
    @classmethod
    def _normalise_date(cls, value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, (date, datetime)):
            return value.isoformat()
        if isinstance(value, str):
            return value.strip() or None
        return str(value)

    @model_validator(mode="before")
    @classmethod
    def _canonicalise_and_derive(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        data = dict(data)

        unit = data.get("unit")
        quantity = _as_number(data.get("quantity"))
        if isinstance(unit, str) and unit.strip():
            if quantity is not None:
                canonical_quantity, canonical_unit = to_canonical(quantity, unit)
                data["quantity"] = round(canonical_quantity, 6)
                data["unit"] = canonical_unit
            else:
                data["unit"] = normalize_unit(unit)

        price = _as_number(data.get("price"))
        old_price = _as_number(data.get("old_price"))

        if data.get("discount_percent") is None:
            discount = calculate_discount_percent(price, old_price)
            if discount is not None:
                data["discount_percent"] = discount

        if data.get("unit_price") is None:
            unit_price = calculate_unit_price(
                price, _as_number(data.get("quantity")), str(data.get("unit") or "")
            )
            if unit_price is not None:
                data["unit_price"] = unit_price

        return data


class StoreBranch(BaseModel):
    """A physical supermarket branch."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    store: str = Field(min_length=1)
    branch_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    address: str
    postal_code: str
    city: str = Field(min_length=1)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    distance_km: float | None = Field(default=None, ge=0)

    @field_validator("store", mode="before")
    @classmethod
    def _normalise_store(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.strip().lower()
        return value

    @field_validator("postal_code", mode="before")
    @classmethod
    def _normalise_postal_code(cls, value: Any) -> Any:
        if isinstance(value, bool):
            return value
        if isinstance(value, int):
            return str(value)
        if isinstance(value, float):
            return str(int(value)) if value.is_integer() else str(value)
        if isinstance(value, str):
            return value.strip()
        return value

    @property
    def full_address(self) -> str:
        """Single-line address for display purposes."""

        return f"{self.address}, {self.postal_code} {self.city}"


__all__ = ["NormalizedProduct", "StoreBranch"]
