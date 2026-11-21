"""Deterministic plausibility check for community-submitted prices.

The rules are intentionally blunt and explainable: we would rather hide a
correct price until an admin approves it than show a wrong one (strict mode).

Layers, in order (first hit wins and adds a reason):

1. **Hard limits** — price 0.10–200.00 EUR, positive quantity.
2. **Category band** — the unit price (EUR/kg or EUR/l) must sit inside the
   band of the inferred product category.
3. **Relative check** — once three confirmed prices exist for the same
   product/store, a deviation beyond 1.8× / below 0.55× of their median is
   suspicious.

No I/O here: the caller supplies the confirmed history.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Sequence
from dataclasses import dataclass, field

from .categories import classify_product, unit_price_band

__all__ = [
    "MAX_PRICE",
    "MIN_PRICE",
    "RELATIVE_HIGH",
    "RELATIVE_LOW",
    "PriceContext",
    "ValidationResult",
    "validate_price",
]

#: Absolute price limits in EUR.
MIN_PRICE = 0.10
MAX_PRICE = 200.00

#: Allowed deviation from the confirmed median.
RELATIVE_HIGH = 1.8
RELATIVE_LOW = 0.55

#: Minimum number of confirmed observations before the relative check runs.
MIN_HISTORY = 3


@dataclass(frozen=True)
class PriceContext:
    """Everything the validator may look at."""

    name: str
    price: float
    unit: str | None = None
    quantity: float | None = None
    unit_price: float | None = None
    brand: str | None = None


@dataclass(frozen=True)
class ValidationResult:
    """``pending`` (plausible) or ``pending_review`` (needs a human)."""

    status: str
    reasons: list[str] = field(default_factory=list)

    @property
    def needs_review(self) -> bool:
        return self.status == "pending_review"


def _eur(value: float) -> str:
    return f"{value:.2f}".replace(".", ",") + " €"


def validate_price(
    ctx: PriceContext, *, history: Sequence[float] = ()
) -> ValidationResult:
    """Return the review status for one submitted price."""

    reasons: list[str] = []

    if not math.isfinite(float(ctx.price)):
        reasons.append("Preis ist keine gültige Zahl.")
    elif ctx.price < MIN_PRICE or ctx.price > MAX_PRICE:
        reasons.append(
            f"Preis {_eur(ctx.price)} außerhalb der Grenze "
            f"{_eur(MIN_PRICE)}–{_eur(MAX_PRICE)}."
        )

    if ctx.quantity is not None and (
        not math.isfinite(float(ctx.quantity)) or ctx.quantity <= 0
    ):
        reasons.append("Menge ist nicht positiv.")

    unit = (ctx.unit or "").strip().lower()
    if ctx.unit_price is not None and not math.isfinite(float(ctx.unit_price)):
        reasons.append("Grundpreis ist keine gültige Zahl.")
    elif ctx.unit_price is not None and unit in {"kg", "l"}:
        group = classify_product(ctx.name, ctx.brand)
        low, high = unit_price_band(group)
        if ctx.unit_price < low or ctx.unit_price > high:
            reasons.append(
                f"Grundpreis {_eur(ctx.unit_price)}/{unit} außerhalb des "
                f"Warengruppen-Bands {_eur(low)}–{_eur(high)}/{unit} "
                f"({group})."
            )

    confirmed = [float(value) for value in history if value > 0]
    if len(confirmed) >= MIN_HISTORY:
        median = statistics.median(confirmed)
        if median > 0:
            ratio = ctx.price / median
            if ratio > RELATIVE_HIGH or ratio < RELATIVE_LOW:
                reasons.append(
                    f"Preis weicht stark vom Median {_eur(median)} ab "
                    f"(Faktor {ratio:.2f}; erlaubt "
                    f"{RELATIVE_LOW:.2f}–{RELATIVE_HIGH:.2f})."
                )

    status = "pending_review" if reasons else "pending"
    return ValidationResult(status=status, reasons=reasons)
