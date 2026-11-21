"""Product category buckets and their plausible unit-price bands.

Used by the community price validator (and available to the UI later).  The
classifier is keyword based on purpose: deterministic, explainable and
testable without any training data.
"""

from __future__ import annotations

from typing import Final

from ..normalization.matcher import fold_umlauts

__all__ = [
    "CATEGORY_KEYWORDS",
    "DEFAULT_GROUP",
    "UNIT_PRICE_BANDS",
    "classify_product",
    "unit_price_band",
]

DEFAULT_GROUP: Final = "other"

#: Keyword buckets, checked in this order.  First match wins.
CATEGORY_KEYWORDS: Final[dict[str, tuple[str, ...]]] = {
    "dairy": (
        "milch",
        "butter",
        "kaese",
        "quark",
        "joghurt",
        "sahne",
        "schmand",
        "frischkaese",
        "gouda",
        "mozzarella",
        "feta",
        "skyr",
        "kefir",
        "rahm",
    ),
    "meat": (
        "fleisch",
        "hack",
        "haehnchen",
        "huhn",
        "wurst",
        "salami",
        "schinken",
        "lachs",
        "fisch",
        "thunfisch",
        "sardine",
        "forelle",
        "garnelen",
        "steak",
        "bratwurst",
    ),
    "produce": (
        "ingwer",
        "banane",
        "apfel",
        "aepfel",
        "kartoffel",
        "zwiebel",
        "tomate",
        "gurke",
        "paprika",
        "salat",
        "karotte",
        "moehre",
        "zucchini",
        "avocado",
        "zitrone",
        "orange",
        "birne",
        "traube",
        "champignon",
        "pilz",
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
    ),
    "drinks": (
        "bier",
        "wein",
        "wasser",
        "cola",
        "saft",
        "limonade",
        "kaffee",
        "tee",
        "sekt",
        "energy",
        "mate",
        "schorle",
        "getraenk",
    ),
    "bakery": (
        "brot",
        "toast",
        "broetchen",
        "baguette",
        "kuchen",
        "croissant",
        "stollen",
        "waffel",
        "brezel",
    ),
    "pantry": (
        "nudel",
        "spaghetti",
        "penne",
        "reis",
        "mehl",
        "zucker",
        "oel",
        "essig",
        "sauce",
        "sosse",
        "passierte",
        "konserve",
        "bruehe",
        "gewuerz",
        "salz",
        "ketchup",
        "senf",
        "mayonnaise",
        "haferflocken",
        "muesli",
        "linsen",
        "bohnen",
        "kichererbsen",
    ),
    "sweets": (
        "schokolade",
        "chips",
        "keks",
        "eis",
        "nutella",
        "marmelade",
        "honig",
        "gummi",
        "praline",
        "suess",
        "bonbon",
        "waffel",
    ),
    "drugstore": (
        "shampoo",
        "duschgel",
        "zahnpasta",
        "deo",
        "seife",
        "waschmittel",
        "toilettenpapier",
        "spuelmittel",
        "putz",
        "lotion",
        "windel",
        "tabs",
        "weichspueler",
    ),
}

#: Plausible unit-price bands (EUR per kg or litre; per piece for drugstore).
#: Deliberately wide — the validator only catches gross outliers.
UNIT_PRICE_BANDS: Final[dict[str, tuple[float, float]]] = {
    "dairy": (0.30, 25.0),
    "meat": (2.0, 80.0),
    "produce": (0.20, 20.0),
    "drinks": (0.15, 15.0),
    "bakery": (0.50, 20.0),
    "pantry": (0.30, 30.0),
    "sweets": (1.0, 60.0),
    "drugstore": (0.50, 300.0),
    "other": (0.05, 500.0),
}


def _words(text: str) -> list[str]:
    folded = fold_umlauts(text or "").casefold()
    for separator in ("-", "/", ",", ".", "(", ")"):
        folded = folded.replace(separator, " ")
    return [word for word in folded.split() if word]


def _is_head_match(word: str, keyword: str) -> bool:
    """German compounds end in the head noun: ``vollkornbrot`` → ``brot``."""

    return word == keyword or word.endswith(keyword)


def _is_loose_match(word: str, keyword: str) -> bool:
    return word.startswith(keyword) or (len(keyword) >= 5 and keyword in word)


def classify_product(name: str, brand: str | None = None) -> str:
    """Return the category bucket for a product name (and optional brand).

    Head matches (compound suffix) win over loose prefix matches, so
    ``Kartoffelchips`` is *sweets* (head: chips), not *produce*.
    """

    words = _words(f"{name or ''} {brand or ''}")
    if not words:
        return DEFAULT_GROUP

    for matcher in (_is_head_match, _is_loose_match):
        for group, keywords in CATEGORY_KEYWORDS.items():
            for keyword in keywords:
                folded = fold_umlauts(keyword).casefold()
                if any(matcher(word, folded) for word in words):
                    return group
    return DEFAULT_GROUP


def unit_price_band(group: str) -> tuple[float, float]:
    """Return the plausible unit-price band for a category."""

    return UNIT_PRICE_BANDS.get(group, UNIT_PRICE_BANDS[DEFAULT_GROUP])
