"""Kassenbon (receipt) parsing for community price contributions.

Why rule-based?
---------------
The project runs without mandatory API keys.  OCR/LLM extraction is therefore
an *optional* provider:

* ``text``  – plain text / eBon paste (always available, deterministic)
* ``pdf``   – text layer of a PDF (``pypdf``, pure Python)
* ``ocr``   – Tesseract, only if ``pytesseract`` **and** the binary exist
* ``llm``   – Gemini/OpenAI-compatible endpoint, only with a key

The parser below turns German receipt text into structured items.  It is
deliberately conservative: a line becomes an item only when it ends in a
plausible price and is not a total/tax/payment line.  Nothing is invented.
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, field
from typing import Any, Final

from ..normalization.normalizer import parse_decimal, parse_quantity

__all__ = [
    "ParsedItem",
    "ParsedReceipt",
    "detect_postal_code",
    "detect_store",
    "parse_receipt_text",
]

#: Store detection by header/footer keywords (the receipt brand).
STORE_PATTERNS: Final[dict[str, tuple[str, ...]]] = {
    "lidl": ("lidl",),
    "rewe": ("rewe", "rewe-markt", "rewe center"),
    "edeka": ("edeka", "edeka-center", "marktkauf"),
    "aldi": ("aldi", "aldi süd", "aldi sued", "aldi nord"),
    "penny": ("penny",),
    "netto": ("netto", "netto marken-discount"),
    "kaufland": ("kaufland",),
    "dm": ("dm-drogerie", "dm drogerie", "dm markt"),
    "rossmann": ("rossmann",),
}

#: Lines that must never become products.
_IGNORE_RE: Final = re.compile(
    r"(summe|gesa\w*tbetrag|zwischensumme|mwst|ust\.?|steuer|bar\b|gegeben|rückgeld|"
    r"rueckgeld|ec-?karte|kartenzahlung|visa|mastercard|girocard|payback|lidl plus|"
    r"deutschland card|trinkgeld|rabatt\s*-|gutschein|punkte|"
    r"datum|uhrzeit|kasse|bon-?nr|beleg-?nr|filiale|tel\.|www\.|"
    r"öffnungszeiten|oeffnungszeiten|vielen dank|auf wiedersehen|"
    r"netto\s*[-–]\s*summe|zu zahlen|zahlbetrag|endsumme|"
    r"^\s*[a-z]\s*=\s*\d+[,.]\d+\s*%)",
    re.IGNORECASE,
)

#: A price at the end of a line: 1,49 / 1.49 / 12,99 with optional tax letter.
_PRICE_END_RE: Final = re.compile(
    r"(?P<price>-?\d{1,4}[.,]\d{2})\s*(?:[A-Z]{1,2}\*?|\*)?\s*$"
)

#: Multiplier forms: "2 x 1,49", "3 Stk x 0,99", "2x1,49".
_MULTIPLIER_RE: Final = re.compile(
    r"^(?P<count>\d{1,2})\s*(?:stk\.?|stück|stueck|x|×)\s*(?:x|×)?\s*"
    r"(?P<unit_price>\d{1,4}[.,]\d{2})",
    re.IGNORECASE,
)

#: A standalone quantity line such as "  2 Stk x 1,49".
_EAN_RE: Final = re.compile(r"\b(\d{8,14})\b")
_POSTCODE_RE: Final = re.compile(r"\b(\d{5})\b")
_TOTAL_RE: Final = re.compile(
    r"(summe|gesamt|zu zahlen|zahlbetrag|endsumme)\D{0,20}(\d{1,4}[.,]\d{2})",
    re.IGNORECASE,
)


@dataclass
class ParsedItem:
    """One receipt line interpreted as a product."""

    name: str
    price: float
    quantity: float = 1.0
    unit: str = "stueck"
    unit_price: float | None = None
    ean: str | None = None
    raw_line: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "price": self.price,
            "quantity": self.quantity,
            "unit": self.unit,
            "unit_price": self.unit_price,
            "ean": self.ean,
        }


@dataclass
class ParsedReceipt:
    """Result of :func:`parse_receipt_text`."""

    store: str | None
    postal_code: str | None
    items: list[ParsedItem] = field(default_factory=list)
    total: float | None = None
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "store": self.store,
            "postal_code": self.postal_code,
            "total": self.total,
            "items": [item.as_dict() for item in self.items],
            "warnings": list(self.warnings),
        }


#: Printer and signature metadata that can mention another store's name.
_STORE_METADATA_RE: Final = re.compile(
    r"(tse|signatur|seriennummer|kasse\s*:|bon-?nr|beleg-?nr|uid|www\.|tel\.)",
    re.IGNORECASE,
)


def detect_store(text: str) -> str | None:
    """Return the store with the strongest heading-like mention in *text*."""

    scores: dict[str, int] = {}
    for line in text.splitlines():
        if _STORE_METADATA_RE.search(line):
            continue
        lowered = line.lower()
        for store, patterns in STORE_PATTERNS.items():
            for pattern in patterns:
                if pattern in lowered:
                    weight = 3 if lowered.strip().startswith(pattern) else 1
                    scores[store] = scores.get(store, 0) + weight
    if not scores:
        return None
    return max(scores, key=lambda store: scores[store])


def detect_postal_code(text: str) -> str | None:
    """Find a German postal code (prefers the one near a city line)."""

    for line in text.splitlines():
        if not _POSTCODE_RE.search(line):
            continue
        # A city line looks like "65618 Münster" and contains letters.
        if re.search(r"[A-Za-zÄÖÜäöüß]{3,}", line):
            match = _POSTCODE_RE.search(line)
            if match:
                return match.group(1)
    match = _POSTCODE_RE.search(text)
    return match.group(1) if match else None


def _clean_name(line: str) -> str:
    name = re.sub(r"\s{2,}", " ", line).strip(" .*·-")
    # Drop a trailing tax class letter that survived the price match.
    return re.sub(r"\s+[A-Z]$", "", name).strip()


def _unit_from_name(name: str) -> tuple[float, str]:
    parsed = parse_quantity(name)
    if parsed is None:
        return 1.0, "stueck"
    return parsed.quantity, parsed.unit


def _is_price_line(line: str) -> bool:
    return bool(_PRICE_END_RE.search(line))


def parse_receipt_text(text: str) -> ParsedReceipt:
    """Parse a German receipt text into products, prices and metadata.

    Unknown lines are skipped; totals are matched separately so the receipt
    total is never mistaken for a product price.
    """

    raw = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    store = detect_store(raw)
    postal_code = detect_postal_code(raw)

    total_match = _TOTAL_RE.search(raw)
    total = parse_decimal(total_match.group(2)) if total_match else None

    items: list[ParsedItem] = []
    warnings: list[str] = []
    last_item: ParsedItem | None = None
    pending_multiplier: tuple[int, float] | None = None
    pending_name: str | None = None

    lines = [line.strip() for line in raw.splitlines()]
    index = 0
    while index < len(lines):
        line = lines[index]
        index += 1
        if not line:
            continue

        # A pure EAN line belongs to the product above it.
        if re.fullmatch(r"\d{8,14}", line) and last_item is not None:
            last_item.ean = line
            continue

        if _IGNORE_RE.search(line):
            pending_multiplier = None
            pending_name = None
            continue

        multiplier = _MULTIPLIER_RE.match(line)
        if multiplier and not _PRICE_END_RE.search(line[multiplier.end() :]):
            count = int(multiplier.group("count"))
            unit_price = parse_decimal(multiplier.group("unit_price"))
            if unit_price is not None:
                pending_multiplier = (count, unit_price)
            continue

        # "GUT & GÜNSTIG MEHL 1KG" followed by a bare "1,49" line (eBon/PDF).
        if (
            not _PRICE_END_RE.search(line)
            and re.search(r"[A-Za-zÄÖÜäöüß]{3,}", line)
            and index < len(lines)
            and re.fullmatch(r"(?:\d{1,4}[.,]\d{2})\s*[A-Z]{0,2}\*?", lines[index])
        ):
            pending_name = line
            continue

        if re.fullmatch(r"\d{1,2}[.,]\d{2}\s*[A-Z]{0,2}\*?", line) and pending_name:
            price = parse_decimal(re.match(r"\d{1,2}[.,]\d{2}", line).group(0))  # type: ignore[union-attr]
            name = _clean_name(pending_name)
            pending_name = None
            if price is not None and price > 0 and name:
                quantity, unit = _unit_from_name(name)
                items.append(
                    ParsedItem(
                        name=name,
                        price=price,
                        quantity=quantity,
                        unit=unit,
                        unit_price=(
                            round(price / quantity, 2)
                            if unit in {"kg", "l"} and quantity
                            else None
                        ),
                        raw_line=f"{name} {line}",
                    )
                )
                last_item = items[-1]
                pending_multiplier = None
            continue

        match = _PRICE_END_RE.search(line)
        if not match:
            continue

        price = parse_decimal(match.group("price"))
        if price is None or price <= 0:
            continue

        name = _clean_name(line[: match.start()])
        if not name or len(name) < 2:
            continue
        # Amounts on their own ("1,49" or "EUR 1,49") are not products.
        if re.fullmatch(r"(eur|€)?\s*\d{1,4}[.,]\d{2}", name, re.IGNORECASE):
            continue

        quantity, unit = _unit_from_name(name)
        unit_price = None
        if quantity and unit in {"kg", "l"}:
            unit_price = round(price / quantity, 2)

        item = ParsedItem(
            name=name,
            price=price,
            quantity=quantity,
            unit=unit,
            unit_price=unit_price,
            raw_line=line,
        )

        if pending_multiplier is not None:
            count, single_price = pending_multiplier
            # "2 x 1,49" belongs to the *next* named line in most layouts.
            if abs(price - round(count * single_price, 2)) < 0.02:
                item.price = round(count * single_price, 2)
                item.quantity = quantity * count
                item.unit_price = (
                    round(item.price / item.quantity, 2)
                    if unit in {"kg", "l"} and item.quantity
                    else None
                )
            pending_multiplier = None

        items.append(item)
        last_item = item

    # Sanity check: if the parsed sum wildly exceeds the printed total, the
    # text probably contains subtotals we could not classify.
    if total and items:
        parsed_sum = sum(item.price for item in items)
        if parsed_sum > total * 1.35:
            warnings.append(
                "Die Summe der Positionen weicht stark vom Bon-Gesamtbetrag ab – "
                "bitte vor dem Speichern prüfen."
            )

    if not items:
        warnings.append(
            "Keine Produktzeilen erkannt. Tipp: Text einfügen (eBon) oder ein "
            "Foto mit klarer Schrift verwenden."
        )

    return ParsedReceipt(
        store=store,
        postal_code=postal_code,
        items=items,
        total=total,
        warnings=warnings,
    )


def median_price(values: list[float]) -> float | None:
    """Median helper used by the aggregation tests."""

    if not values:
        return None
    return round(statistics.median(values), 2)
