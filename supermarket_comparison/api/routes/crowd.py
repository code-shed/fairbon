"""Community crowdsourcing endpoints: prices, receipts, coverage, scouts."""

from __future__ import annotations

import asyncio
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, ConfigDict, Field, field_validator

from ...services.receipt_import import (
    OcrUnavailable,
    UnsupportedReceipt,
    extract_text,
    import_receipt,
)
from ...services.receipts import parse_receipt_text
from ...storage import CommunityPriceInput, Repository
from ..routes.history import get_repository

router = APIRouter(prefix="/crowd", tags=["crowd"])

STORE_SLUG_RE = r"^[a-z0-9][a-z0-9-]{0,30}$"


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class PriceSubmission(BaseModel):
    """One manually reported shelf price."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    name: str = Field(min_length=2, max_length=120)
    store: str = Field(min_length=2, max_length=32, pattern=STORE_SLUG_RE)
    price: float = Field(gt=0, le=5000, allow_inf_nan=False)
    postal_code: str = Field(pattern=r"^\d{4,5}$")
    ean: str | None = Field(default=None, pattern=r"^\d{8,14}$")
    unit: str | None = Field(
        default=None,
        pattern=r"^(kg|g|gramm|l|ml|milliliter|stueck|stk|st|stück)$",
    )
    quantity: float | None = Field(default=None, gt=0, le=100000, allow_inf_nan=False)
    scout_id: str | None = Field(default=None, max_length=40)

    @field_validator("store", mode="before")
    @classmethod
    def _lower(cls, value: Any) -> Any:
        return value.strip().lower() if isinstance(value, str) else value

    @field_validator("unit", mode="before")
    @classmethod
    def _lower_unit(cls, value: Any) -> Any:
        return value.strip().lower() if isinstance(value, str) else value


class ReceiptTextSubmission(BaseModel):
    """Paste an eBon / receipt text instead of uploading a file."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    text: str = Field(min_length=3, max_length=20000)
    postal_code: str | None = Field(default=None, pattern=r"^\d{4,5}$")
    store: str | None = Field(default=None, max_length=32)
    scout_id: str | None = Field(default=None, max_length=40)


class RejectSubmission(BaseModel):
    """Optional reason for a moderation decision."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    reason: str = Field(default="Vom Admin abgelehnt.", max_length=300)


class ConfirmSubmission(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    scout_id: str = Field(min_length=1, max_length=40)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _community(repository: Repository) -> Any:
    return repository.community


def _serialize(entry: dict[str, Any], *, private: bool = False) -> dict[str, Any]:
    return {
        "id": entry.get("id"),
        "name": entry.get("name"),
        "store": entry.get("store"),
        "price": entry.get("price"),
        "unit": entry.get("unit"),
        "quantity": entry.get("quantity"),
        "unit_price": entry.get("unit_price"),
        "postal_code": entry.get("postal_code"),
        "status": entry.get("status"),
        "review_reason": entry.get("review_reason"),
        "confirmations": entry.get("confirmations"),
        "source": entry.get("source"),
        **({"scout_id": entry.get("scout_id")} if private else {}),
        "created_at": entry.get("created_at"),
    }


# ---------------------------------------------------------------------------
# Prices
# ---------------------------------------------------------------------------


@router.post(
    "/prices",
    summary="Submit a community shelf price",
    status_code=201,
)
async def submit_price(
    body: PriceSubmission,
    repository: Annotated[Repository, Depends(get_repository)],
) -> dict[str, Any]:
    """Store an anonymous price report and return its review status.

    The response always carries ``status`` and, for flagged submissions,
    ``review_reason``.  ``aggregate`` is only populated once an approved or
    verified price exists — a fresh report stays invisible (strict mode).
    """

    try:
        community_input = CommunityPriceInput(
            name=body.name,
            store=body.store,
            price=body.price,
            postal_code=body.postal_code,
            ean=body.ean,
            unit=body.unit,
            quantity=body.quantity,
            scout_id=body.scout_id,
            source="manual",
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    try:
        store = await asyncio.to_thread(repository.community.add_price, community_input)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    aggregate = await asyncio.to_thread(
        repository.community.aggregate,
        identity=store["identity"],
        store=store["store"],
        postal_code=store["postal_code"],
    )
    scout = (
        await asyncio.to_thread(repository.community.scout_stats, body.scout_id)
        if body.scout_id
        else None
    )
    return {"price": _serialize(store), "aggregate": aggregate, "scout": scout}


@router.get("/prices", summary="List or aggregate community prices")
async def list_prices(
    repository: Annotated[Repository, Depends(get_repository)],
    postal_code: Annotated[str | None, Query(pattern=r"^\d{4,5}$")] = None,
    ean: Annotated[str | None, Query(pattern=r"^\d{8,14}$")] = None,
    name: Annotated[str | None, Query(min_length=2, max_length=80)] = None,
    store: Annotated[str | None, Query(max_length=32)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> dict[str, Any]:
    """Raw submissions plus the aggregated median per product/store."""

    rows = await asyncio.to_thread(
        repository.community.list_prices,
        postal_code=postal_code,
        ean=ean,
        name=name,
        store=store,
        limit=limit,
    )
    aggregated: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for row in rows:
        key = (row["identity"], row["store"], row["postal_code"])
        if key in seen:
            continue
        seen.add(key)
        entry = await asyncio.to_thread(
            repository.community.aggregate,
            identity=row["identity"],
            store=row["store"],
            postal_code=row["postal_code"],
        )
        if entry:
            aggregated.append(entry)
    return {
        "submissions": [_serialize(row) for row in rows],
        "aggregated": aggregated,
        "count": len(rows),
    }


@router.post("/prices/{price_id}/confirm", summary="Confirm a community price")
async def confirm_price(
    price_id: str,
    body: ConfirmSubmission,
    repository: Annotated[Repository, Depends(get_repository)],
) -> dict[str, Any]:
    """Add a distinct confirmation; three confirmations mark a price verified."""

    entry = await asyncio.to_thread(
        repository.community.confirm, price_id, body.scout_id
    )
    if entry is None:
        raise HTTPException(status_code=404, detail="Preis nicht gefunden.")
    aggregate = await asyncio.to_thread(
        repository.community.aggregate,
        identity=entry["identity"],
        store=entry["store"],
        postal_code=entry["postal_code"],
    )
    return {"price": _serialize(entry), "aggregate": aggregate}


@router.get("/coverage", summary="Community coverage for a postal code")
async def coverage(
    repository: Annotated[Repository, Depends(get_repository)],
    postal_code: Annotated[str, Query(pattern=r"^\d{4,5}$")],
) -> dict[str, Any]:
    """How many standard prices the community already contributed nearby."""

    return await asyncio.to_thread(repository.community.coverage, postal_code)


@router.get("/scouts/{scout_id}", summary="Anonymous scout statistics")
async def scout_stats(
    scout_id: str,
    repository: Annotated[Repository, Depends(get_repository)],
) -> dict[str, Any]:
    """Contribution count and badges for one anonymous local scout id."""

    return await asyncio.to_thread(repository.community.scout_stats, scout_id)


# ---------------------------------------------------------------------------
# Moderation (admin queue)
# ---------------------------------------------------------------------------


@router.get(
    "/review",
    summary="Community prices waiting for moderation",
)
async def review_queue(
    repository: Annotated[Repository, Depends(get_repository)],
    status: Annotated[
        str,
        Query(
            pattern="^(pending|pending_review|all)$",
            description="Which bucket to list",
        ),
    ] = "pending_review",
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> dict[str, Any]:
    """List flagged entries plus the counts of both open buckets."""

    queue = await asyncio.to_thread(
        repository.community.review_queue, status=status, limit=limit
    )

    counts = await asyncio.to_thread(repository.community.review_counts)
    return {
        "status": status,
        "items": [_serialize(item, private=True) for item in queue],
        "counts": counts,
    }


@router.post(
    "/prices/{price_id}/approve",
    summary="Approve a community price",
)
async def approve_price(
    price_id: str,
    repository: Annotated[Repository, Depends(get_repository)],
) -> dict[str, Any]:
    """Publish one price (admin confirmation)."""

    entry = await asyncio.to_thread(
        repository.community.approve, price_id, reviewer="admin"
    )
    if entry is None:
        raise HTTPException(status_code=404, detail="Preis nicht gefunden.")
    return {"price": _serialize(entry)}


@router.post(
    "/prices/{price_id}/reject",
    summary="Reject a community price",
)
async def reject_price(
    price_id: str,
    repository: Annotated[Repository, Depends(get_repository)],
    body: RejectSubmission | None = None,
) -> dict[str, Any]:
    """Hide one price permanently."""

    reason = body.reason if body is not None else "Vom Admin abgelehnt."
    entry = await asyncio.to_thread(
        repository.community.reject, price_id, reviewer="admin", reason=reason
    )
    if entry is None:
        raise HTTPException(status_code=404, detail="Preis nicht gefunden.")
    return {"price": _serialize(entry)}


@router.post(
    "/review/approve-all",
    summary="Approve every plausible pending price",
)
async def approve_all(
    repository: Annotated[Repository, Depends(get_repository)],
) -> dict[str, int]:
    """Batch-approve the plausible queue; anomalies stay in review."""

    approved = await asyncio.to_thread(
        repository.community.approve_all_pending, reviewer="admin"
    )
    return {"approved": approved}


# ---------------------------------------------------------------------------
# Receipts
# ---------------------------------------------------------------------------


@router.post(
    "/upload-receipt",
    summary="Upload a receipt (image/PDF/text) and import shelf prices",
)
async def upload_receipt(
    repository: Annotated[Repository, Depends(get_repository)],
    file: Annotated[UploadFile, File(description="Kassenbon als Bild, PDF oder Text")],
    postal_code: Annotated[str | None, Form(pattern=r"^\d{4,5}$")] = None,
    store: Annotated[str | None, Form(max_length=32)] = None,
    scout_id: Annotated[str | None, Form(max_length=40)] = None,
) -> dict[str, Any]:
    """Extract items from a receipt and store them for the given postal code.

    Text and PDF-with-text-layer work out of the box.  Images require a local
    OCR stack; without it the endpoint answers ``503`` with a clear hint
    instead of pretending to have read the photo.
    """

    data = await file.read()
    try:
        extraction = await asyncio.to_thread(
            extract_text,
            data,
            content_type=file.content_type,
            filename=file.filename,
        )
    except OcrUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except UnsupportedReceipt as exc:
        raise HTTPException(status_code=415, detail=str(exc)) from exc

    parsed_preview = parse_receipt_text(extraction.text)
    effective_store = (store or parsed_preview.store or "unbekannt").lower()
    effective_plz = postal_code or parsed_preview.postal_code

    receipt_id = await asyncio.to_thread(
        repository.community.save_receipt,
        store=effective_store,
        postal_code=effective_plz,
        scout_id=scout_id,
        filename=file.filename,
        content_type=file.content_type,
        raw_text=extraction.text,
        item_count=len(parsed_preview.items),
        engine=extraction.engine,
    )

    parsed, created = await asyncio.to_thread(
        import_receipt,
        community=repository.community,
        text=extraction.text,
        postal_code=effective_plz,
        scout_id=scout_id,
        receipt_id=receipt_id,
    )

    scout = (
        await asyncio.to_thread(repository.community.scout_stats, scout_id)
        if scout_id
        else None
    )
    coverage_data = (
        await asyncio.to_thread(repository.community.coverage, effective_plz)
        if effective_plz
        else None
    )

    counts = {
        "pending": sum(1 for row in created if row.get("status") == "pending"),
        "pending_review": sum(
            1 for row in created if row.get("status") == "pending_review"
        ),
    }
    return {
        "receipt_id": receipt_id,
        "engine": extraction.engine,
        "store": effective_store,
        "postal_code": effective_plz,
        "items": [item.as_dict() for item in parsed.items],
        "imported": len(created),
        **counts,
        "warnings": parsed.warnings,
        "total": parsed.total,
        "scout": scout,
        "coverage": coverage_data,
    }


@router.post(
    "/receipts/text",
    summary="Import a receipt from pasted text (eBon)",
)
async def import_receipt_text(
    body: ReceiptTextSubmission,
    repository: Annotated[Repository, Depends(get_repository)],
) -> dict[str, Any]:
    """Same as the upload, but for text pasted by the user."""

    parsed_preview = parse_receipt_text(body.text)
    effective_store = (body.store or parsed_preview.store or "unbekannt").lower()
    effective_plz = body.postal_code or parsed_preview.postal_code

    receipt_id = await asyncio.to_thread(
        repository.community.save_receipt,
        store=effective_store,
        postal_code=effective_plz,
        scout_id=body.scout_id,
        filename=None,
        content_type="text/plain",
        raw_text=body.text,
        item_count=len(parsed_preview.items),
        engine="text",
    )

    parsed, created = await asyncio.to_thread(
        import_receipt,
        community=repository.community,
        text=body.text,
        postal_code=effective_plz,
        scout_id=body.scout_id,
        receipt_id=receipt_id,
    )

    scout = (
        await asyncio.to_thread(repository.community.scout_stats, body.scout_id)
        if body.scout_id
        else None
    )
    coverage_data = (
        await asyncio.to_thread(repository.community.coverage, effective_plz)
        if effective_plz
        else None
    )
    counts = {
        "pending": sum(1 for row in created if row.get("status") == "pending"),
        "pending_review": sum(
            1 for row in created if row.get("status") == "pending_review"
        ),
    }
    return {
        "receipt_id": receipt_id,
        "engine": "text",
        "store": effective_store,
        "postal_code": effective_plz,
        "items": [item.as_dict() for item in parsed.items],
        "imported": len(created),
        **counts,
        "warnings": parsed.warnings,
        "total": parsed.total,
        "scout": scout,
        "coverage": coverage_data,
    }


__all__ = ["router"]
