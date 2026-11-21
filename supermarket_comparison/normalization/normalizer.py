"""Unit/quantity parsing and price normalisation.

The functions in this module are intentionally free of any dependency on the
Pydantic models so scrapers, tests and future batch jobs can reuse them in
isolation.

Canonical representation
------------------------
* mass is converted to **kilograms** (``kg``)
* volume is converted to **litres** (``l``)
* countable goods use the pseudo unit ``stueck``

``ParsedQuantity.quantity``/``ParsedQuantity.unit`` therefore always describe
the *total* amount of a package in canonical form, while
``raw_quantity``/``raw_unit``/``pack_count`` preserve what was written on the
shelf label (e.g. ``6 x 0,33 l`` -> total ``1.98 l``, single pack ``0.33 l``).
"""

from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Final

MASS: Final = "mass"
VOLUME: Final = "volume"
COUNT: Final = "count"
UNKNOWN: Final = "unknown"

UNIT_KG: Final = "kg"
UNIT_L: Final = "l"
UNIT_STUECK: Final = "stueck"

CANONICAL_UNITS: Final[tuple[str, ...]] = (UNIT_KG, UNIT_L, UNIT_STUECK)

#: alias -> (family, canonical symbol, factor to the family base unit)
#: mass base unit = gram, volume base unit = millilitre, count base = piece.
_UNITS: Final[dict[str, tuple[str, str, float]]] = {
    # --- mass -------------------------------------------------------------
    "mg": (MASS, "mg", 0.001),
    "milligramm": (MASS, "mg", 0.001),
    "milligram": (MASS, "mg", 0.001),
    "g": (MASS, "g", 1.0),
    "gr": (MASS, "g", 1.0),
    "gramm": (MASS, "g", 1.0),
    "gram": (MASS, "g", 1.0),
    "grams": (MASS, "g", 1.0),
    "kg": (MASS, "kg", 1000.0),
    "kilo": (MASS, "kg", 1000.0),
    "kilogramm": (MASS, "kg", 1000.0),
    "kilogram": (MASS, "kg", 1000.0),
    "kilograms": (MASS, "kg", 1000.0),
    "pfund": (MASS, "pfund", 500.0),
    "pfunde": (MASS, "pfund", 500.0),
    "t": (MASS, "t", 1_000_000.0),
    "tonne": (MASS, "t", 1_000_000.0),
    "tonnen": (MASS, "t", 1_000_000.0),
    # --- volume -----------------------------------------------------------
    "ml": (VOLUME, "ml", 1.0),
    "milliliter": (VOLUME, "ml", 1.0),
    "millilitre": (VOLUME, "ml", 1.0),
    "millilitres": (VOLUME, "ml", 1.0),
    "cl": (VOLUME, "cl", 10.0),
    "zentiliter": (VOLUME, "cl", 10.0),
    "centiliter": (VOLUME, "cl", 10.0),
    "dl": (VOLUME, "dl", 100.0),
    "deziliter": (VOLUME, "dl", 100.0),
    "decilitre": (VOLUME, "dl", 100.0),
    "l": (VOLUME, "l", 1000.0),
    "lt": (VOLUME, "l", 1000.0),
    "ltr": (VOLUME, "l", 1000.0),
    "liter": (VOLUME, "l", 1000.0),
    "litre": (VOLUME, "l", 1000.0),
    "liters": (VOLUME, "l", 1000.0),
    "litres": (VOLUME, "l", 1000.0),
    # --- count ------------------------------------------------------------
    "st": (COUNT, UNIT_STUECK, 1.0),
    "stk": (COUNT, UNIT_STUECK, 1.0),
    "stck": (COUNT, UNIT_STUECK, 1.0),
    "stueck": (COUNT, UNIT_STUECK, 1.0),
    "stuecke": (COUNT, UNIT_STUECK, 1.0),
    "stuecks": (COUNT, UNIT_STUECK, 1.0),
    "stück": (COUNT, UNIT_STUECK, 1.0),
    "stücke": (COUNT, UNIT_STUECK, 1.0),
    "stücks": (COUNT, UNIT_STUECK, 1.0),
    "pc": (COUNT, UNIT_STUECK, 1.0),
    "pcs": (COUNT, UNIT_STUECK, 1.0),
    "piece": (COUNT, UNIT_STUECK, 1.0),
    "pieces": (COUNT, UNIT_STUECK, 1.0),
}

_UNIT_ALTERNATION: Final = "|".join(
    re.escape(alias) for alias in sorted(_UNITS, key=len, reverse=True)
)

# One number token, German (``1,5``), English (``1.5``) or grouped (``1.000``).
_NUM: Final = r"\d+(?:[.,]\d+)*"

# A unit must not be followed by another letter (so ``g`` does not match in
# ``gramm``; the longer alternatives are tried first anyway).
_UNIT_SUFFIX: Final = rf"(?P<unit>{_UNIT_ALTERNATION})\.?(?![a-zA-ZäöüÄÖÜß])"

# Number/unit separator: whitespace or hyphen (``1,5-l-Flasche``).
_SEP: Final = r"[\s-]*"

_X_MULTI_RE: Final = re.compile(
    rf"(?P<count>\d{{1,3}}){_SEP}(?:x|×|\*){_SEP}(?P<value>{_NUM}){_SEP}{_UNIT_SUFFIX}",
    re.IGNORECASE,
)
# ``2er Pack 0,5 l`` / ``6er 200 g``
_ER_MULTI_RE: Final = re.compile(
    rf"(?P<count>\d{{1,3}})\s*er[-\s]*(?:pack(?:ung|ungen)?\s*)?"
    rf"(?:je\s+)?(?P<value>{_NUM}){_SEP}{_UNIT_SUFFIX}",
    re.IGNORECASE,
)
_SINGLE_RE: Final = re.compile(
    rf"(?P<value>{_NUM}){_SEP}{_UNIT_SUFFIX}",
    re.IGNORECASE,
)
_BARE_RE: Final = re.compile(rf"(?P<value>{_NUM})\.?", re.IGNORECASE)
_BARE_ER_RE: Final = re.compile(r"(?P<count>\d{1,3})\s*er", re.IGNORECASE)
_DECIMAL_RE: Final = re.compile(r"-?\d[\d.,]*")

_THOUSANDS_RE: Final = re.compile(r"[1-9]\d{0,2}(?:\.\d{3})+")


@dataclass(frozen=True, slots=True)
class ParsedQuantity:
    """Result of :func:`parse_quantity`."""

    #: Total amount in the canonical unit (``kg``, ``l`` or ``stueck``).
    quantity: float
    #: Canonical unit of :attr:`quantity`.
    unit: str
    #: Amount of a single pack as printed on the label.
    raw_quantity: float
    #: Normalised symbol of the unit as printed on the label.
    raw_unit: str
    #: Number of identical packs (1 unless the label says e.g. ``6 x``).
    pack_count: int = 1

    @property
    def total_raw_quantity(self) -> float:
        """Raw amount multiplied by the pack count."""

        return round(self.raw_quantity * self.pack_count, 6)

    @property
    def is_piece(self) -> bool:
        """Whether the quantity is expressed in pieces."""

        return self.unit == UNIT_STUECK

    def __str__(self) -> str:
        label = f"{self.raw_quantity:g} {self.raw_unit}"
        if self.pack_count > 1:
            return f"{self.pack_count} x {label}"
        return label


def _prepare(text: str) -> str:
    """Unicode-normalise a label (NFKC also turns ``㎏`` into ``kg``)."""

    return (
        unicodedata.normalize("NFKC", text)
        .replace("\u00a0", " ")
        .replace("\u202f", " ")
    )


def _clean_unit(unit: str) -> str:
    return _prepare(str(unit)).strip().lower().replace(".", "").replace(" ", "")


def normalize_unit(unit: str | None) -> str:
    """Map a unit alias to its canonical symbol.

    Known aliases are translated (``Gramm`` -> ``g``, ``Stück`` ->
    ``stueck``). Unknown units are returned cleaned (lower case, without
    dots/whitespace) so callers can still display them.
    """

    if not unit:
        return ""
    key = _clean_unit(unit)
    entry = _UNITS.get(key)
    return entry[1] if entry is not None else key


def unit_family(unit: str | None) -> str:
    """Return ``mass``, ``volume``, ``count`` or ``unknown`` for *unit*."""

    if not unit:
        return UNKNOWN
    entry = _UNITS.get(_clean_unit(unit))
    return entry[0] if entry is not None else UNKNOWN


def to_canonical(quantity: float, unit: str) -> tuple[float, str]:
    """Convert *quantity* of *unit* to ``(value, 'kg' | 'l' | 'stueck')``."""

    value = float(quantity)
    entry = _UNITS.get(_clean_unit(unit))
    if entry is None:
        return value, _clean_unit(unit)

    family, _symbol, factor = entry
    if family == MASS:
        return value * factor / 1000.0, UNIT_KG
    if family == VOLUME:
        return value * factor / 1000.0, UNIT_L
    return value * factor, UNIT_STUECK


def _parse_number_token(token: str) -> float:
    """Parse ``1,5`` / ``1.5`` / ``1.000`` / ``1.234,56`` into a float."""

    text = token.strip()
    if not text:
        raise ValueError("empty number")

    negative = text.startswith("-")
    text = text.lstrip("+-")

    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            # German grouping: 1.234,56
            text = text.replace(".", "").replace(",", ".")
        else:
            # English grouping: 1,234.56
            text = text.replace(",", "")
    elif "," in text:
        # A single comma is the decimal separator; repeated commas are
        # thousands separators (e.g. 1,234,567).
        text = text.replace(",", ".") if text.count(",") == 1 else text.replace(",", "")
    elif "." in text and _THOUSANDS_RE.fullmatch(text):
        text = text.replace(".", "")

    value = float(text)
    return -value if negative else value


def parse_decimal(value: Any) -> float | None:
    """Best-effort extraction of a number from prices such as ``"1.234,56 €"``."""

    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    if not isinstance(value, str):
        return None

    match = _DECIMAL_RE.search(_prepare(value))
    if match is None:
        return None
    try:
        number = _parse_number_token(match.group(0))
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def _number(value: str) -> float | None:
    try:
        return _parse_number_token(value)
    except ValueError:
        return None


def _from_multipack(match: re.Match[str]) -> ParsedQuantity | None:
    count = int(match.group("count"))
    value = _number(match.group("value"))
    if value is None or count <= 0:
        return None
    raw_unit = normalize_unit(match.group("unit"))
    if not raw_unit:
        return None
    total, canonical_unit = to_canonical(value * count, raw_unit)
    return ParsedQuantity(
        quantity=round(total, 6),
        unit=canonical_unit,
        raw_quantity=value,
        raw_unit=raw_unit,
        pack_count=count,
    )


def _from_single(match: re.Match[str]) -> ParsedQuantity | None:
    value = _number(match.group("value"))
    if value is None:
        return None
    raw_unit = normalize_unit(match.group("unit"))
    if not raw_unit:
        return None
    total, canonical_unit = to_canonical(value, raw_unit)
    return ParsedQuantity(
        quantity=round(total, 6),
        unit=canonical_unit,
        raw_quantity=value,
        raw_unit=raw_unit,
    )


def parse_quantity(value: str | float | None) -> ParsedQuantity | None:
    """Parse a package size into a :class:`ParsedQuantity`.

    Examples::

        >>> parse_quantity("500g").quantity, parse_quantity("500g").unit
        (0.5, 'kg')
        >>> parsed = parse_quantity("6 x 0,33 l")
        >>> parsed.quantity, parsed.unit, parsed.pack_count
        (1.98, 'l', 6)

    Returns ``None`` when no quantity can be recognised. Bare numbers are
    treated as piece counts (``"6"`` -> 6 pieces).
    """

    if value is None or isinstance(value, bool):
        return None

    if isinstance(value, (int, float)):
        amount = float(value)
        if not math.isfinite(amount) or amount < 0:
            return None
        return ParsedQuantity(
            quantity=amount,
            unit=UNIT_STUECK,
            raw_quantity=amount,
            raw_unit=UNIT_STUECK,
        )

    if not isinstance(value, str):
        return None

    text = _prepare(value)
    if not text.strip():
        return None

    for pattern in (_X_MULTI_RE, _ER_MULTI_RE):
        match = pattern.search(text)
        if match is not None:
            parsed = _from_multipack(match)
            if parsed is not None:
                return parsed

    match = _SINGLE_RE.search(text)
    if match is not None:
        parsed = _from_single(match)
        if parsed is not None:
            return parsed

    bare = _BARE_RE.fullmatch(text.strip())
    if bare is not None:
        amount = _number(bare.group("value"))
        if amount is not None and amount >= 0:
            return ParsedQuantity(
                quantity=amount,
                unit=UNIT_STUECK,
                raw_quantity=amount,
                raw_unit=UNIT_STUECK,
            )

    bare_er = _BARE_ER_RE.fullmatch(text.strip())
    if bare_er is not None:
        count = int(bare_er.group("count"))
        return ParsedQuantity(
            quantity=float(count),
            unit=UNIT_STUECK,
            raw_quantity=float(count),
            raw_unit=UNIT_STUECK,
        )

    return None


def _as_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    if isinstance(value, str):
        return parse_decimal(value)
    return None


def calculate_unit_price(
    price: float | str | None, quantity: float | str | None, unit: str
) -> float | None:
    """Return the price per kilogram or litre.

    ``quantity``/``unit`` may be given in any supported unit (``500, "g"`` or
    ``0.5, "kg"``); piece quantities have no comparable unit price and yield
    ``None``.
    """

    amount = _as_float(price)
    size = _as_float(quantity)
    if amount is None or size is None or amount < 0 or size <= 0:
        return None

    total, canonical_unit = to_canonical(size, unit)
    if canonical_unit not in (UNIT_KG, UNIT_L) or total <= 0:
        return None
    return round(amount / total, 4)


def calculate_discount_percent(
    price: float | str | None, old_price: float | str | None
) -> float | None:
    """Return the discount in percent, or ``None`` without a usable old price."""

    current = _as_float(price)
    previous = _as_float(old_price)
    if current is None or previous is None or current < 0 or previous <= 0:
        return None
    if current >= previous:
        return 0.0
    return round((previous - current) / previous * 100.0, 2)


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
    "calculate_discount_percent",
    "calculate_unit_price",
    "normalize_unit",
    "parse_decimal",
    "parse_quantity",
    "to_canonical",
    "unit_family",
]
