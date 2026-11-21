"""Admin database endpoints (protected by the site password)."""

from __future__ import annotations

import asyncio
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query

from ...services.admin_records import (
    TABLES,
    delete_record,
    list_records,
    schema_payload,
    update_record,
)
from ...storage import Repository
from .history import get_repository

router = APIRouter(prefix="/admin/database", tags=["admin"])


@router.get("/schema", summary="Tables and editable fields for the admin UI")
async def admin_schema() -> dict[str, Any]:
    return schema_payload()


@router.get("/records", summary="Paginated, filterable table view")
async def admin_records(
    repository: Annotated[Repository, Depends(get_repository)],
    table: Annotated[
        str, Query(description="products|price_points|price_history|community_prices")
    ],
    q: Annotated[str | None, Query(max_length=120)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
    sort: Annotated[str | None, Query(max_length=40)] = None,
    store: Annotated[str | None, Query(max_length=40)] = None,
    source: Annotated[str | None, Query(max_length=40)] = None,
    status: str | None = None,
    postal_code: str | None = None,
) -> dict[str, Any]:
    """Return one page of records; unknown tables answer 404."""

    if table not in TABLES:
        raise HTTPException(status_code=404, detail=f"Unbekannte Tabelle: {table}")

    filters = {
        "store": store,
        "source": source,
        "status": status,
        "postal_code": postal_code,
    }
    return await asyncio.to_thread(
        list_records,
        repository.db,
        table,
        q=q,
        filters={key: value for key, value in filters.items() if value},
        page=page,
        page_size=page_size,
        sort=sort,
    )


@router.put(
    "/records/{table}/{record_id}",
    summary="Update one record (whitelisted fields only)",
)
async def update_record_endpoint(
    table: str,
    record_id: int,
    repository: Annotated[Repository, Depends(get_repository)],
    values: Annotated[dict[str, Any], Body(...)],
) -> dict[str, Any]:
    """Apply a correction and return the fresh row."""

    if table not in TABLES:
        raise HTTPException(status_code=404, detail=f"Unbekannte Tabelle: {table}")
    if not values:
        raise HTTPException(status_code=422, detail="Keine Felder angegeben.")

    try:
        updated = await asyncio.to_thread(
            update_record, repository.db, table, record_id, values
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if updated is None:
        raise HTTPException(status_code=404, detail="Eintrag nicht gefunden.")
    return updated


@router.delete(
    "/records/{table}/{record_id}",
    summary="Delete one record",
)
async def delete_record_endpoint(
    table: str,
    record_id: int,
    repository: Annotated[Repository, Depends(get_repository)],
) -> dict[str, bool]:
    """Remove one row; products cascade to their prices."""

    if table not in TABLES:
        raise HTTPException(status_code=404, detail=f"Unbekannte Tabelle: {table}")

    deleted = await asyncio.to_thread(delete_record, repository.db, table, record_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Eintrag nicht gefunden.")
    return {"deleted": True}


__all__ = ["router"]
