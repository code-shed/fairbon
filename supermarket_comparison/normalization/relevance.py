"""Three-tier relevance ranking for German product names.

German noun compounds put the semantic head (*Grundwort*) **last**:
``Markenbutter`` is butter while ``Buttermilch`` is milk with butter as the
modifier (*Bestimmungswort*).  A plain substring search cannot tell those
apart, therefore this module scores every offer on three tiers:

==============  ==========================================================
Tier            Meaning
==============  ==========================================================
3 ``exact``     the query is a whole word or a compound suffix
                (``Butter``, ``Markenbutter``, ``Süßrahmbutter``)
3 ``compound``  synonym for the suffix case (score 0.95)
2 ``category``  the query matches the category or brand
1 ``modifier``  the query is only a prefix or an unrelated substring
                (``Buttermilch``, ``Butterkekse``, ``Erdnussbutter``)
0 ``none``      no token hit and fuzzy similarity below 70 %
==============  ==========================================================

The public entry point is :func:`rank_products`; :func:`quick_filters`
derives the "exclude this compound" chips shown by the web UI.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Final

from rapidfuzz import fuzz

from .matcher import normalize_title

TIER_EXACT: Final = 3
TIER_CATEGORY: Final = 2
TIER_MODIFIER: Final = 1
TIER_NONE: Final = 0

SCORE_EXACT: Final = 1.0
SCORE_COMPOUND: Final = 0.95
SCORE_CATEGORY: Final = 0.7
SCORE_MODIFIER: Final = 0.4
SCORE_NONE: Final = 0.0

#: Minimum fuzzy similarity accepted as an imprecise (tier 1) hit.
FUZZY_THRESHOLD: Final = 70

#: Capitalised measure/container nouns that follow the query without changing
#: what the product is (``Butter Stück``, ``Milch Becher``, ``Butter Kilo``).
_MEASURE_HEADS: Final = frozenset(
    {
        "stuck",
        "stueck",
        "stuecke",
        "kilo",
        "kilogramm",
        "gramm",
        "pfund",
        "liter",
        "packung",
        "pack",
        "paeckchen",
        "becher",
        "glas",
        "flasche",
        "dose",
        "tafel",
        "kasten",
        "stange",
        "beutel",
        "schale",
        "tray",
        "riegel",
        "portion",
        "inhalt",
        "menge",
        "grosspackung",
        "kleinpackung",
    }
)

#: Tokens that never carry product meaning on their own (numbers are filtered
#: separately) – they must not hide a following head noun.
_NON_CONTENT_TOKENS: Final = frozenset(
    {
        "g",
        "gr",
        "kg",
        "mg",
        "ml",
        "l",
        "cl",
        "dl",
        "stk",
        "st",
        "stueck",
        "stuecks",
        "x",
        "je",
        "ca",
        "pack",
        "pck",
        "pkg",
        "er",
        "und",
        "mit",
        "in",
        "im",
    }
)

#: Compounds whose head word is *not* semantically the query even though the
#: query appears as a prefix or suffix.  ``Erdnussbutter`` is nut butter, not
#: dairy butter; ``Kokosmilch`` is plant milk, not dairy milk; ``Weinbrand`` is
#: brandy, not wine.  The mapping is generic: any query token can register
#: false friends without touching the scoring code.
MODIFIER_EXCEPTIONS: Final[dict[str, frozenset[str]]] = {
    "butter": frozenset(
        {
            "buttermilch",
            "erdaumnuss",
            "erndussbutter",
            "erdnussbutter",
            "nussbutter",
            "kokosbutter",
            "kakaobutter",
            "sheabutter",
            "bodybutter",
        }
    ),
    "milch": frozenset(
        {
            "buttermilch",
            "kokosmilch",
            "sojamilch",
            "mandelmilch",
            "hafermilch",
            "reismilch",
        }
    ),
    "wein": frozenset({"weinbrand", "weinessig", "weintrauben"}),
}

# Fuzzy comparison fold: umlauts become their base vowel so a user typing
# ``kase`` still matches ``Käse``.  ``ß`` becomes ``ss``.
_LOOSE_MAP: Final = str.maketrans(
    {
        "ä": "a",
        "ö": "o",
        "ü": "u",
        "Ä": "A",
        "Ö": "O",
        "Ü": "U",
        "ß": "ss",
    }
)

_RAW_WORD_RE: Final = re.compile(r"[0-9A-Za-zÀ-ÖØ-öø-ÿĀ-ž]+")


def normalize_loose(text: str) -> str:
    """Lower-case, base-vowel-fold and strip punctuation from *text*."""

    prepared = unicodedata.normalize("NFKC", str(text)).translate(_LOOSE_MAP)
    return normalize_title(prepared)


def _tokens(text: str) -> list[str]:
    return [token for token in normalize_loose(text).split() if token]


def _raw_words(text: str) -> list[str]:
    return _RAW_WORD_RE.findall(str(text))


def _fuzzy(left: str, right: str) -> float:
    """Similarity 0..100 on the loose (base vowel) representation."""

    return fuzz.token_set_ratio(normalize_loose(left), normalize_loose(right))


def _is_content_word(word: str) -> bool:
    """Whether *word* can be a product head noun (no numbers, units, fillers)."""

    stripped = word.strip()
    if not stripped or stripped.isdigit():
        return False
    return normalize_loose(stripped) not in _NON_CONTENT_TOKENS


def _modifier_head_noun(name: str, query_token: str) -> str | None:
    """Return the head noun if *query_token* only modifies a spaced compound.

    ``Butter-Mandel-Stollen`` is a stollen in which butter is an ingredient,
    exactly like ``Buttermilch`` is milk – the query token is the modifier,
    not the head.  German orthography capitalises nouns, which distinguishes
    the compound from an adjective such as ``Butter, gesalzen``.
    """

    words = _raw_words(name)
    for index, word in enumerate(words):
        if normalize_loose(word) != query_token:
            continue
        heads = [
            candidate
            for candidate in words[index + 1 :]
            if _is_content_word(candidate)
            and candidate[:1].isupper()
            and candidate[1:].islower()
            and normalize_loose(candidate) not in _MEASURE_HEADS
        ]
        # German compounds end in the head noun: ``Butter-Mandel-Stollen``
        # is a stollen.  Lowercase followers are adjectives ("Butter, gesalzen")
        # and measure nouns ("Butter Stück") keep the query as the head.
        return heads[-1] if heads else None
    return None


def has_token(text: str, token: str) -> bool:
    """Whether *token* occurs as a whole word in *text* (umlaut tolerant)."""

    wanted = normalize_loose(token)
    return bool(wanted) and wanted in _tokens(text)


def contains_token(text: str, token: str) -> bool:
    """Whether *token* occurs anywhere in *text* (umlaut tolerant)."""

    wanted = normalize_loose(token)
    return bool(wanted) and wanted in normalize_loose(text)


def _exception_set(query_token: str) -> frozenset[str]:
    exceptions = MODIFIER_EXCEPTIONS.get(query_token, frozenset())
    return frozenset(normalize_loose(item) for item in exceptions)


@dataclass
class ScoredProduct:
    """A product plus its relevance assessment for one query."""

    product: object
    score: float = SCORE_NONE
    tier: int = TIER_NONE
    matched_as: str = "none"
    matched_terms: list[str] = field(default_factory=list)
    counter_terms: list[str] = field(default_factory=list)

    @property
    def is_precise(self) -> bool:
        """Tier 2/3 hits are precise enough for the default result list."""

        return self.tier >= TIER_CATEGORY

    @property
    def price_key(self) -> float:
        """Comparable price used for tie-breaking (unit price when present)."""

        unit_price = getattr(self.product, "unit_price", None)
        price = getattr(self.product, "price", 0.0) or 0.0
        return float(unit_price) if unit_price is not None else float(price)


@dataclass(frozen=True)
class _NameHit:
    tier: int
    matched_as: str
    score: float
    matched_term: str
    counter_term: str | None


def _classify_name_token(
    token: str, query_token: str, *, name: str = ""
) -> _NameHit | None:
    """Classify one name token against one query token."""

    exceptions = _exception_set(query_token)

    if token == query_token:
        head = _modifier_head_noun(name, query_token) if name else None
        if head is not None:
            return _NameHit(TIER_MODIFIER, "modifier", SCORE_MODIFIER, "", head)
        return _NameHit(TIER_EXACT, "exact", SCORE_EXACT, query_token, None)

    if len(token) > len(query_token) and token.endswith(query_token):
        if token in exceptions:
            return _NameHit(TIER_MODIFIER, "modifier", SCORE_MODIFIER, "", token)
        return _NameHit(TIER_EXACT, "compound", SCORE_COMPOUND, token, None)

    if len(token) > len(query_token) and token.startswith(query_token):
        return _NameHit(TIER_MODIFIER, "modifier", SCORE_MODIFIER, "", token)

    # Plain substring that is not aligned to a word boundary.
    if query_token in token:
        return _NameHit(TIER_MODIFIER, "modifier", SCORE_MODIFIER, "", token)

    return None


def _name_hit(name: str, query_token: str) -> _NameHit | None:
    best: _NameHit | None = None
    for token in _tokens(name):
        hit = _classify_name_token(token, query_token, name=name)
        if hit is None:
            continue
        if best is None or hit.tier > best.tier:
            best = hit
            if best.tier == TIER_EXACT and best.matched_as == "exact":
                break
    return best


def _side_hit(text: str | None, query_token: str) -> _NameHit | None:
    """Category/brand tier: whole word or compound suffix only."""

    if not text:
        return None
    for token in _tokens(text):
        if token == query_token:
            return _NameHit(
                TIER_CATEGORY, "category", SCORE_CATEGORY, query_token, None
            )
        if len(token) > len(query_token) and token.endswith(query_token):
            return _NameHit(TIER_CATEGORY, "category", SCORE_CATEGORY, token, None)
    return None


def score_product(product: object, query: str) -> ScoredProduct:
    """Score one product against *query*."""

    query_tokens = _tokens(query)
    if not query_tokens:
        return ScoredProduct(product=product)

    name = str(getattr(product, "name", "") or "")
    category = getattr(product, "category", None)
    brand = getattr(product, "brand", None)

    best: ScoredProduct | None = None

    for query_token in query_tokens:
        hit = _name_hit(name, query_token)
        if hit is None:
            # Only let category/brand promote products that do not already
            # have a (modifier) name hit: "Buttermilch" in category "Butter"
            # must stay imprecise.
            hit = _side_hit(category, query_token) or _side_hit(brand, query_token)

        if hit is None:
            similarity = max(_fuzzy(name, query_token), _fuzzy(name, query))
            if similarity >= FUZZY_THRESHOLD:
                hit = _NameHit(
                    TIER_MODIFIER, "modifier", SCORE_MODIFIER, "", query_token
                )

        if hit is None:
            continue

        scored = ScoredProduct(
            product=product,
            score=hit.score,
            tier=hit.tier,
            matched_as=hit.matched_as,
            matched_terms=[hit.matched_term] if hit.matched_term else [],
            counter_terms=[hit.counter_term] if hit.counter_term else [],
        )
        if (
            best is None
            or scored.tier > best.tier
            or (scored.tier == best.tier and scored.score > best.score)
        ):
            best = scored

    return best or ScoredProduct(product=product)


def _sort_key(scored: ScoredProduct) -> tuple[float, int, float, float, str, str]:
    return (
        -scored.tier,
        0 if scored.is_precise else 1,
        scored.price_key,
        float(getattr(scored.product, "price", 0.0) or 0.0),
        str(getattr(scored.product, "store", "") or ""),
        str(getattr(scored.product, "name", "") or ""),
    )


def rank_products(
    products: Iterable[object],
    query: str,
    *,
    include_imprecise: bool = False,
) -> list[ScoredProduct]:
    """Score and sort *products*; drop modifier hits unless requested.

    Products without any token hit and below the fuzzy threshold (tier 0)
    are never returned.
    """

    scored = [score_product(product, query) for product in products]
    scored = [item for item in scored if item.tier > TIER_NONE]
    if not include_imprecise:
        scored = [item for item in scored if item.is_precise]
    scored.sort(key=_sort_key)
    return scored


def _original_term(name: str, normalized: str) -> str:
    """Find the original spelling of *normalized* inside *name*."""

    for word in _raw_words(name):
        if normalize_loose(word) == normalized:
            return word
    return normalized


def quick_filters(scored: Iterable[ScoredProduct]) -> list[dict[str, object]]:
    """Aggregate the offending compounds of tier-1 hits.

    Returns entries like ``{"term": "Buttermilch", "count": 6}`` sorted by
    descending frequency.
    """

    counts: Counter[str] = Counter()
    display: dict[str, str] = {}

    for item in scored:
        if item.tier != TIER_MODIFIER:
            continue
        name = str(getattr(item.product, "name", "") or "")
        for term in item.counter_terms:
            normalized = normalize_loose(term)
            if not normalized:
                continue
            counts[normalized] += 1
            if normalized not in display:
                original = _original_term(name, normalized)
                display[normalized] = original[:1].upper() + original[1:]

    return [
        {"term": display[normalized], "count": count}
        for normalized, count in sorted(
            counts.items(), key=lambda pair: (-pair[1], pair[0])
        )
    ]


def keyword_stats(scored: Iterable[ScoredProduct]) -> dict[str, int]:
    """Return the number of precise vs. imprecise hits (task 8.1)."""

    precise = 0
    imprecise = 0
    for item in scored:
        if item.tier >= TIER_CATEGORY:
            precise += 1
        elif item.tier == TIER_MODIFIER:
            imprecise += 1
    return {"precise": precise, "imprecise": imprecise}


def apply_exclusions(
    products: Sequence[object], exclude: Iterable[str] | None
) -> list[object]:
    """Drop products whose normalised name contains an exclusion term."""

    if not exclude:
        return list(products)

    terms = [normalize_loose(term) for term in exclude if str(term).strip()]
    terms = [term for term in terms if term]
    if not terms:
        return list(products)

    return [
        product
        for product in products
        if not any(
            term in normalize_loose(str(getattr(product, "name", "") or ""))
            for term in terms
        )
    ]


__all__ = [
    "FUZZY_THRESHOLD",
    "MODIFIER_EXCEPTIONS",
    "SCORE_CATEGORY",
    "SCORE_COMPOUND",
    "SCORE_EXACT",
    "SCORE_MODIFIER",
    "TIER_CATEGORY",
    "TIER_EXACT",
    "TIER_MODIFIER",
    "TIER_NONE",
    "ScoredProduct",
    "apply_exclusions",
    "contains_token",
    "has_token",
    "keyword_stats",
    "normalize_loose",
    "quick_filters",
    "rank_products",
    "score_product",
]
