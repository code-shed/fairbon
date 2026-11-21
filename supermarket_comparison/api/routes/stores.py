"""Store lookup endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from ...models import StoreBranch
from ...services.aggregator import Aggregator
from ..deps import get_aggregator

router = APIRouter(prefix="/stores", tags=["stores"])


@router.get(
    "",
    response_model=list[StoreBranch],
    summary="List stores for a postal code",
)
@router.get(
    "/search",
    response_model=list[StoreBranch],
    summary="Search stores by postal code",
)
async def search_stores(
    aggregator: Annotated[Aggregator, Depends(get_aggregator)],
    postal_code: Annotated[
        str,
        Query(
            min_length=4,
            max_length=5,
            description="German/Austrian/Swiss postal code",
        ),
    ],
    store: Annotated[
        str | None,
        Query(description="Filter by store, e.g. ``lidl`` or ``lidl,rewe``"),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[StoreBranch]:
    """Return branches near *postal_code*, optionally filtered by store."""

    return await aggregator.search_stores(
        postal_code=postal_code, store=store, limit=limit
    )


__all__ = ["router"]
