"""Brand sanitising.

Marketplace and community sources sometimes carry placeholder brands such as
``thisisnobrand123`` (Marktguru), ``nobrand`` or ``unknown``.  They must never
reach the UI, so they are normalised to ``None`` at ingestion time.
"""

from __future__ import annotations

import re
from typing import Final

__all__ = ["clean_brand", "is_junk_brand"]

#: Case-insensitive placeholders that carry no information.
_JUNK_EXACT: Final[frozenset[str]] = frozenset(
    {
        "nobrand",
        "no brand",
        "no-brand",
        "none",
        "null",
        "nil",
        "n/a",
        "na",
        "unknown",
        "unbekannt",
        "keine marke",
        "ohne marke",
        "marke unbekannt",
        "diverse",
        "-",
        "--",
        ".",
        "?",
    }
)

_JUNK_RE: Final = re.compile(
    r"^(?:this\s*is\s*no\s*brand\d*|no[\s_-]?brand\d*|nobrand\d*)$",
    re.IGNORECASE,
)

_WS_RE: Final = re.compile(r"\s+")


def is_junk_brand(value: str | None) -> bool:
    """Whether *value* is a placeholder rather than a real brand."""

    if value is None:
        return True
    text = _WS_RE.sub(" ", str(value)).strip()
    if not text:
        return True
    folded = text.casefold()
    if folded in _JUNK_EXACT:
        return True
    if _JUNK_RE.match(folded):
        return True
    # Pure numbers / punctuation carry no brand information either.
    if text.isdigit():
        return True
    return not any(character.isalpha() for character in text)


def clean_brand(value: str | None) -> str | None:
    """Return the brand or ``None`` when it is a placeholder."""

    if value is None:
        return None
    text = _WS_RE.sub(" ", str(value)).strip()
    if is_junk_brand(text):
        return None
    return text
