"""Product search, ranked search and comparison endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from ...models import NormalizedProduct, RankedSearchResult
from ...normalization.relevance import apply_exclusions
from ...services.aggregator import Aggregator
from ...services.validity import is_today
from ..deps import get_aggregator

router = APIRouter(prefix="/products", tags=["products"])


def _split_stores(stores: str | None) -> list[str] | None:
    if not stores:
        return None
    selected = [part.strip().lower() for part in stores.split(",") if part.strip()]
    return selected or None


def _split_terms(value: str | None) -> list[str] | None:
    if not value:
        return None
    terms = [part.strip() for part in value.split(",") if part.strip()]
    return terms or None


@router.get(
    "/search/ranked",
    response_model=RankedSearchResult,
    summary="Search offers with three-tier relevance ranking",
)
async def search_products_ranked(
    aggregator: Annotated[Aggregator, Depends(get_aggregator)],
    query: Annotated[str, Query(min_length=1, description="Free-text search")],
    postal_code: Annotated[
        str | None,
        Query(
            min_length=4,
            max_length=5,
            description="German/Austrian/Swiss postal code",
        ),
    ] = None,
    stores: Annotated[
        str | None,
        Query(description="Comma-separated stores to query, e.g. ``lidl,rewe``"),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 20,
    precise: Annotated[
        bool,
        Query(
            description=(
                "Drop modifier hits (Buttermilch for Butter) when true. "
                "Set false to include them after the precise hits."
            )
        ),
    ] = True,
    exclude: Annotated[
        str | None,
        Query(
            description=(
                "Comma-separated terms to exclude, e.g. ``Buttermilch,Butterkekse``"
            )
        ),
    ] = None,
    today_only: Annotated[
        bool,
        Query(description="Only return offers valid today in Europe/Berlin"),
    ] = False,
    include_standard: Annotated[
        bool,
        Query(
            description=(
                "Merge permanent shelf prices (Dauersortiment) from "
                "Open Food Facts / Open Prices"
            )
        ),
    ] = False,
    offers_only: Annotated[
        bool,
        Query(description="Drop standard prices and keep leaflet offers only"),
    ] = False,
) -> RankedSearchResult:
    """Return ranked offers plus quick filters and source diagnostics.

    Each item carries its relevance tier (3 = exact/compound, 2 = category,
    1 = modifier) and a validity badge for the Europe/Berlin timezone.
    """

    return await aggregator.search_ranked(
        query=query,
        postal_code=postal_code,
        stores=_split_stores(stores),
        limit=limit,
        precise=precise,
        exclude=_split_terms(exclude),
        today_only=today_only,
        include_standard=include_standard,
        offers_only=offers_only,
    )


@router.get(
    "/search",
    response_model=list[NormalizedProduct],
    summary="Search product offers across all stores",
)
async def search_products(
    aggregator: Annotated[Aggregator, Depends(get_aggregator)],
    query: Annotated[str, Query(min_length=1, description="Free-text search")],
    postal_code: Annotated[
        str | None,
        Query(
            min_length=4,
            max_length=5,
            description="German/Austrian/Swiss postal code",
        ),
    ] = None,
    stores: Annotated[
        str | None,
        Query(
            description="Comma-separated stores to query, e.g. ``lidl,rewe``",
        ),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 20,
    precise: Annotated[
        bool,
        Query(description="Only return precise (tier 2/3) hits"),
    ] = True,
    today_only: Annotated[
        bool,
        Query(description="Only return offers valid today in Europe/Berlin"),
    ] = False,
    exclude: Annotated[
        str | None,
        Query(description="Comma-separated terms to exclude"),
    ] = None,
    include_standard: Annotated[
        bool,
        Query(description="Merge permanent shelf prices from Open Prices"),
    ] = False,
    offers_only: Annotated[
        bool,
        Query(description="Drop standard prices and keep leaflet offers only"),
    ] = False,
) -> list[NormalizedProduct]:
    """Return matching offers from the selected supermarkets.

    Results are ranked by relevance and deduplicated across sources.  A source
    that fails to respond is skipped instead of failing the whole request.
    """

    products = await aggregator.search(
        query=query,
        postal_code=postal_code,
        stores=_split_stores(stores),
        limit=limit,
        precise=precise,
        include_standard=include_standard,
    )

    exclusions = _split_terms(exclude)
    if exclusions:
        products = apply_exclusions(products, exclusions)
    if offers_only:
        products = [p for p in products if p.offer_type != "standard"]
    if today_only:
        products = [
            product
            for product in products
            if is_today(product.valid_from, product.valid_to)
        ]
    return products[:limit]


@router.get(
    "/compare",
    response_model=list[NormalizedProduct],
    summary="Compare one product across stores",
)
async def compare_products(
    aggregator: Annotated[Aggregator, Depends(get_aggregator)],
    ean: Annotated[
        str | None,
        Query(
            min_length=8,
            max_length=14,
            description="EAN/GTIN of the product",
        ),
    ] = None,
    query: Annotated[
        str | None,
        Query(min_length=1, description="Product name (alternative to ean)"),
    ] = None,
    postal_code: Annotated[
        str | None,
        Query(
            min_length=4,
            max_length=5,
            description="German/Austrian/Swiss postal code",
        ),
    ] = None,
    stores: Annotated[
        str | None,
        Query(description="Comma-separated stores, e.g. ``lidl,rewe``"),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> list[NormalizedProduct]:
    """Return the cheapest offer per store for one product.

    Either ``ean`` or ``query`` must be supplied.
    """

    if not ean and not query:
        raise HTTPException(status_code=422, detail="Provide either 'ean' or 'query'.")

    return await aggregator.compare(
        ean=ean,
        query=query,
        postal_code=postal_code,
        stores=_split_stores(stores),
        limit=limit,
    )


__all__ = ["router"]
