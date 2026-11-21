"""Product matching, deduplication and relevance filtering.

Products are clustered in two passes:

1. an exact pass on the EAN/GTIN (authoritative identity), followed by
2. a fuzzy pass on the normalised title using :mod:`rapidfuzz`.

Fuzzy matches additionally require a compatible package size so a 500 g pack
is not merged with a 1 kg pack of the same product line.  Two different,
non-empty EANs are never merged.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final

from rapidfuzz import fuzz

if TYPE_CHECKING:  # pragma: no cover - imported only for type checkers
    from ..models import NormalizedProduct

_WHITESPACE_RE = re.compile(r"\s+")
_NON_WORD_RE = re.compile(r"[^\w\s]+")
_EAN_RE = re.compile(r"[\s\-]")

#: German umlauts are transliterated before comparing, so ``"Kaergarden"``
#: matches ``"Kärgarden"`` and vice versa.
_UMLAUT_MAP: Final = str.maketrans(
    {
        "ä": "ae",
        "ö": "oe",
        "ü": "ue",
        "Ä": "Ae",
        "Ö": "Oe",
        "Ü": "Ue",
        "ß": "ss",
    }
)

#: Minimum fuzzy score (0..100) accepted by :func:`filter_by_query`.
QUERY_FUZZY_THRESHOLD = 70

#: Query tokens shorter than this are ignored for the substring match.
MIN_TOKEN_LENGTH = 3

#: Relative tolerance for package sizes during fuzzy matching.
AMOUNT_TOLERANCE = 0.10


def fold_umlauts(text: str) -> str:
    """Transliterate German umlauts/``ß`` to their ASCII digraphs."""

    return text.translate(_UMLAUT_MAP)


def normalize_title(title: str) -> str:
    """Lower-case a title and collapse punctuation/whitespace for matching."""

    text = unicodedata.normalize("NFKC", fold_umlauts(title)).lower()
    text = _NON_WORD_RE.sub(" ", text)
    return _WHITESPACE_RE.sub(" ", text).strip()
    return _WHITESPACE_RE.sub(" ", text).strip()

_DISPLAY_HINTS: Final = frozenset(
    {
        "pils", "pilsner", "gold", "helles", "dunkles", "weizen",
        "weissbier", "weißbier", "hefe", "alkoholfrei", "alkoholfreies",
        "radler", "kasten", "sixpack", "dose", "flasche", "karton",
        "beutel", "pack", "packung",
    }
)


def _fold_for_match(text: str) -> str:
    return unicodedata.normalize("NFKC", fold_umlauts(text)).lower()


def build_display_title(
    title: str | None, brand: str | None = None, description: str | None = None
) -> str:
    """Build an enriched display title from raw title, brand and description."""

    base_title = (title or "").strip()

    clean = None
    try:
        from .brands import clean_brand as _clean_brand

        clean = _clean_brand(brand)
    except Exception:  # pragma: no cover - defensive
        clean = (brand or "").strip() or None

    brand_text = clean if clean is not None else ((brand or "").strip() or None)

    folded_title = _fold_for_match(base_title)

    if brand_text and _fold_for_match(brand_text) not in folded_title:
        base_title = f"{brand_text} {base_title}".strip()
        folded_title = _fold_for_match(base_title)

    if description:
        seen: set[str] = set(folded_title.split())
        for token in re.split(r"[^\w]+", description):
            token = token.strip()
            if not token:
                continue
            folded_token = _fold_for_match(token)
            if folded_token not in _DISPLAY_HINTS:
                continue
            if folded_token in seen:
                continue
            base_title = f"{base_title} {token}".strip()
            seen.add(folded_token)

    tokens = base_title.split()
    collapsed: list[str] = []
    for token in tokens:
        if collapsed and _fold_for_match(collapsed[-1]) == _fold_for_match(token):
            continue
        collapsed.append(token)
    return " ".join(collapsed).strip() or (title or "").strip() or ""




def normalize_ean(ean: str | None) -> str | None:
    """Return a canonical EAN string or ``None``."""

    if not ean:
        return None
    cleaned = _EAN_RE.sub("", str(ean).strip())
    return cleaned or None


def title_similarity(left: str, right: str) -> float:
    """Return a 0..1 similarity score between two product titles."""

    return fuzz.token_set_ratio(normalize_title(left), normalize_title(right)) / 100.0


@dataclass
class ProductGroup:
    """A cluster of offers describing the same product across stores."""

    key: str
    name: str
    ean: str | None = None
    offers: list[NormalizedProduct] = field(default_factory=list)

    @property
    def best_offer(self) -> NormalizedProduct:
        """The cheapest offer in the group."""

        return min(self.offers, key=lambda offer: (offer.price, offer.store))

    @property
    def min_price(self) -> float:
        """Lowest price in the group."""

        return self.best_offer.price

    @property
    def max_price(self) -> float:
        """Highest price in the group."""

        return max(offer.price for offer in self.offers)

    @property
    def stores(self) -> list[str]:
        """Distinct store identifiers present in the group (sorted)."""

        return sorted({offer.store for offer in self.offers})

    @property
    def price_spread(self) -> float:
        """Difference between the most and least expensive offer."""

        return round(self.max_price - self.min_price, 2)


@dataclass
class _Cluster:
    members: list[NormalizedProduct] = field(default_factory=list)
    ean: str | None = None


def _validate_threshold(threshold: float) -> None:
    if not 0.0 <= threshold <= 1.0:
        raise ValueError("threshold must be between 0 and 1")


def _brands_conflict(left: NormalizedProduct, right: NormalizedProduct) -> bool:
    if not left.brand or not right.brand:
        return False
    return title_similarity(left.brand, right.brand) < 0.5


def _amounts_compatible(left: NormalizedProduct, right: NormalizedProduct) -> bool:
    """Whether two package sizes are close enough to describe the same offer."""

    if left.unit != right.unit:
        return False
    if left.quantity <= 0 or right.quantity <= 0:
        return True
    largest = max(left.quantity, right.quantity)
    return abs(left.quantity - right.quantity) / largest <= AMOUNT_TOLERANCE


def _similar(
    cluster: _Cluster,
    candidate: NormalizedProduct,
    *,
    threshold: float,
    same_amount: bool,
) -> bool:
    best_member: NormalizedProduct | None = None
    best_score = 0.0
    for member in cluster.members:
        score = title_similarity(member.name, candidate.name)
        if score > best_score:
            best_score = score
            best_member = member

    if best_member is None or best_score < threshold:
        return False
    if _brands_conflict(best_member, candidate):
        return False
    return not same_amount or _amounts_compatible(best_member, candidate)


def _cluster_products(
    products: Sequence[NormalizedProduct],
    *,
    threshold: float,
    same_amount: bool,
) -> list[_Cluster]:
    clusters: list[_Cluster] = []
    ean_index: dict[str, _Cluster] = {}

    for product in products:
        ean = normalize_ean(product.ean)

        if ean and ean in ean_index:
            cluster = ean_index[ean]
            cluster.members.append(product)
            continue

        target: _Cluster | None = None
        for cluster in clusters:
            if ean and cluster.ean and cluster.ean != ean:
                continue
            if _similar(
                cluster,
                product,
                threshold=threshold,
                same_amount=same_amount,
            ):
                target = cluster
                break

        if target is None:
            target = _Cluster(members=[product], ean=ean)
            clusters.append(target)
        else:
            target.members.append(product)
            if ean and target.ean is None:
                target.ean = ean

        if ean:
            ean_index[ean] = target

    return clusters


def match_products(
    products: Sequence[NormalizedProduct],
    *,
    threshold: float = 0.85,
    same_amount: bool = True,
) -> list[list[NormalizedProduct]]:
    """Group equivalent products across stores.

    Exact EAN matches are always grouped.  Products without an EAN (or with
    the same EAN) are additionally clustered by title similarity.  When
    *same_amount* is true the package size must match within
    :data:`AMOUNT_TOLERANCE`.
    """

    _validate_threshold(threshold)
    clusters = _cluster_products(products, threshold=threshold, same_amount=same_amount)
    return [cluster.members for cluster in clusters]


def group_products(
    products: Sequence[NormalizedProduct],
    *,
    threshold: float = 0.85,
    same_amount: bool = True,
) -> list[ProductGroup]:
    """Return :class:`ProductGroup` objects sorted by lowest price."""

    groups: list[ProductGroup] = []
    for members in match_products(
        products, threshold=threshold, same_amount=same_amount
    ):
        ean = normalize_ean(members[0].ean) if members[0].ean else None
        key = ean or f"{members[0].store}:{normalize_title(members[0].name)}"
        groups.append(
            ProductGroup(
                key=key,
                name=members[0].name,
                ean=ean,
                offers=list(members),
            )
        )
    groups.sort(key=lambda group: group.min_price)
    return groups


def deduplicate(
    products: Sequence[NormalizedProduct],
    *,
    threshold: float = 0.9,
    same_amount: bool = True,
) -> list[NormalizedProduct]:
    """Drop duplicate offers while keeping store diversity.

    Offers are clustered with :func:`match_products`.  Within a cluster the
    cheapest offer per store and product identity (EAN or normalised title)
    is kept, so a product listed twice by the same store does not appear
    twice while all stores remain comparable.
    """

    _validate_threshold(threshold)
    clusters = _cluster_products(products, threshold=threshold, same_amount=same_amount)

    result: list[NormalizedProduct] = []
    for cluster in clusters:
        best_by_identity: dict[tuple[str, str], NormalizedProduct] = {}
        for product in cluster.members:
            identity = normalize_ean(product.ean) or normalize_title(product.name)
            key = (product.store, identity)
            current = best_by_identity.get(key)
            if current is None or (product.price, product.name) < (
                current.price,
                current.name,
            ):
                best_by_identity[key] = product
        result.extend(best_by_identity.values())
    return result


def filter_by_query(
    products: Iterable[NormalizedProduct],
    query: str,
    *,
    threshold: float = 0.85,
) -> list[NormalizedProduct]:
    """Keep offers that are relevant to *query*.

    A product is relevant when

    * any query token of at least :data:`MIN_TOKEN_LENGTH` characters occurs
      in its name or brand (case-insensitive, umlaut-normalised), or
    * the fuzzy title similarity reaches ``max(threshold, 0.70)``.

    The tolerant substring rule is what makes ``"butter"`` match
    ``"Feine Butter"``, ``"Kaergarden Butter"`` and ``"Butter-Schmalz"``.
    """

    normalized_query = normalize_title(query)
    if not normalized_query:
        return list(products)

    query_tokens = [token for token in normalized_query.split() if token]
    long_tokens = [
        token for token in query_tokens if len(token) >= MIN_TOKEN_LENGTH
    ] or query_tokens
    fuzzy_threshold = max(threshold, QUERY_FUZZY_THRESHOLD / 100.0)

    relevant: list[NormalizedProduct] = []
    for product in products:
        haystack = normalize_title(f"{product.name} {product.brand or ''}")
        if any(token in haystack for token in long_tokens):
            relevant.append(product)
            continue
        if title_similarity(product.name, query) >= fuzzy_threshold:
            relevant.append(product)
    return relevant


__all__ = [
    "AMOUNT_TOLERANCE",
    "MIN_TOKEN_LENGTH",
    "QUERY_FUZZY_THRESHOLD",
    "ProductGroup",
    "build_display_title",
    "deduplicate",
    "filter_by_query",
    "fold_umlauts",
    "group_products",
    "match_products",
    "normalize_ean",
    "normalize_title",
    "title_similarity",
]
