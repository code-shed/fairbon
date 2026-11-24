"""Category heuristics shared by the image resolver, cleanup and the UI."""

from __future__ import annotations

from typing import Final

from .matcher import fold_umlauts

__all__ = [
    "LOOSE_PRODUCE_WORDS",
    "RECEIPT_CATEGORIES",
    "is_loose_produce",
    "normalize_category",
]

#: Canonical display categories of receipt items (also used by the UI).
RECEIPT_CATEGORIES: Final[tuple[str, ...]] = (
    "Lebensmittel",
    "Getränke",
    "Drogerie",
    "Haushalt",
    "Bäcker/Gastronomie",
    "Technik/Non-Food",
    "Pfand",
    "Sonstiges",
)

#: Extra spellings that do not fold onto a canonical name.
_CATEGORY_ALIASES: Final[dict[str, str]] = {
    "getraenk": "Getränke",
    "getraenke": "Getränke",
    "drinks": "Getränke",
    "bäcker": "Bäcker/Gastronomie",
    "baecker": "Bäcker/Gastronomie",
    "technik": "Technik/Non-Food",
    "non-food": "Technik/Non-Food",
    "pfand": "Pfand",
}

_FOLDED_CATEGORIES: Final[dict[str, str]] = {
    fold_umlauts(name).casefold(): name for name in RECEIPT_CATEGORIES
}


def normalize_category(value: str | None) -> str:
    """Return the canonical category for *value* (``Sonstiges`` if unknown)."""

    folded = fold_umlauts(str(value or "").strip()).casefold()
    if not folded:
        return "Sonstiges"
    canonical = _FOLDED_CATEGORIES.get(folded)
    if canonical is not None:
        return canonical
    return _CATEGORY_ALIASES.get(folded, "Sonstiges")


#: Loose fruit and vegetables: a catalogue photo is usually the wrong product
#: (a ginger *shot* instead of ginger root), so they get the category icon.
LOOSE_PRODUCE_WORDS: Final[frozenset[str]] = frozenset(
    {
        "ingwer",
        "banane",
        "bananen",
        "apfel",
        "aepfel",
        "kartoffel",
        "kartoffeln",
        "zwiebel",
        "zwiebeln",
        "tomate",
        "tomaten",
        "gurke",
        "gurken",
        "paprika",
        "salat",
        "karotte",
        "karotten",
        "moehre",
        "moehren",
        "zucchini",
        "avocado",
        "zitrone",
        "zitronen",
        "orange",
        "orangen",
        "birne",
        "birnen",
        "traube",
        "trauben",
        "champignon",
        "pilze",
        "obst",
        "gemuese",
        "spinat",
        "brokkoli",
        "blumenkohl",
        "lauch",
        "porree",
        "radieschen",
        "kohlrabi",
        "kuerbis",
    }
)


def is_loose_produce(name: str) -> bool:
    """Whether *name* describes loose fruit/vegetables."""

    folded = fold_umlauts(name or "").casefold()
    words = set(folded.replace("-", " ").split())
    return bool(words & LOOSE_PRODUCE_WORDS)
