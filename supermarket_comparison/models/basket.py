"""Response models for ranked search results and the basket optimiser."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from .product import NormalizedProduct


class RelevanceInfo(BaseModel):
    """How well one offer matched the search query."""

    tier: int
    score: float
    matched_as: str
    matched_terms: list[str] = []
    counter_terms: list[str] = []


class ValidityInfo(BaseModel):
    """Validity badge data (dates as ISO strings)."""

    state: str = "unknown"
    label: str = ""
    starts: str | None = None
    ends: str | None = None


class RankedItem(BaseModel):
    """One offer with relevance and validity metadata."""

    product: NormalizedProduct
    relevance: RelevanceInfo
    validity: ValidityInfo


class QuickFilter(BaseModel):
    """Suggested exclusion chip (e.g. ``Buttermilch``)."""

    term: str
    count: int


class RankedSearchResult(BaseModel):
    """Payload of ``GET /api/v1/products/search/ranked``."""

    query: str
    postal_code: str | None = None
    total_found: int
    total_returned: int
    items: list[RankedItem]
    quick_filters: list[QuickFilter]
    sources: dict[str, int]
    errors: dict[str, str]


class BasketLine(BaseModel):
    """One item of a store group inside a basket option."""

    item: str
    product: NormalizedProduct
    store: str


class StoreGroup(BaseModel):
    """All basket lines bought at one store."""

    store: str
    lines: list[BasketLine]
    subtotal: float


class BasketOption(BaseModel):
    """A complete purchase plan (option A or B)."""

    model_config = ConfigDict(extra="ignore")

    label: str
    stores: list[StoreGroup]
    total: float
    merchants: int
    covers_all: bool
    missing_items: list[str] = []
    savings: float = 0.0
    baseline_total: float | None = None
    #: True when no single store covers every item and ``baseline_total`` is
    #: only the best partial single-store basket (so ``savings`` is 0).
    baseline_partial: bool = False


class BasketItemResult(BaseModel):
    """Resolution status of one shopping-list item."""

    query: str
    status: str  # matched | unmatched


class BasketPlan(BaseModel):
    """Payload of ``POST /api/v1/basket/optimize``."""

    postal_code: str | None = None
    items: list[BasketItemResult]
    option_a: BasketOption
    option_b: BasketOption
    unmatched: list[str] = []
    errors: dict[str, str] = {}
    #: Ready-to-share text for WhatsApp / clipboard.
    share_text: str | None = None
    #: ``https://wa.me/?text=…`` deep link for the same text.
    whatsapp_url: str | None = None


__all__ = [
    "BasketItemResult",
    "BasketLine",
    "BasketOption",
    "BasketPlan",
    "QuickFilter",
    "RankedItem",
    "RankedSearchResult",
    "RelevanceInfo",
    "StoreGroup",
    "ValidityInfo",
]
