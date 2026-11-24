"""Canonical store slugs for receipts and price-comparison filters."""

from __future__ import annotations

from typing import Final

__all__ = ["normalize_store"]

#: Slugs used by the frontend's NS.STORES (own badges, no brand logos).
CANONICAL_STORES: Final[tuple[str, ...]] = (
    "lidl", "rewe", "edeka", "aldi", "penny", "netto",
    "kaufland", "rossmann", "dm", "globus",
)

_ALIASES: Final[dict[str, str]] = {
    "rewe markt": "rewe",
    "penny markt": "penny",
    "dm drogerie markt": "dm",
    "dm-drogerie markt": "dm",
    "kaufland marken-discount": "kaufland",
    "netto marken-discount": "netto",
    "media markt": "mediamarkt",
}


def normalize_store(value: str | None) -> str:
    """Return a canonical slug for known chains, else a trimmed title."""

    text = " ".join(str(value or "").split())
    if not text:
        return "Sonstiges"
    folded = text.casefold().replace("ä", "ae").replace("ö", "oe").replace("ü", "ue")
    alias = _ALIASES.get(folded)
    if alias:
        return alias
    if folded in CANONICAL_STORES:
        return folded
    if folded.replace("-", "").replace(" ", "") in {
        slug.replace("-", "") for slug in CANONICAL_STORES
    }:
        return next(
            slug for slug in CANONICAL_STORES
            if slug.replace("-", "") == folded.replace("-", "").replace(" ", "")
        )
    return text
