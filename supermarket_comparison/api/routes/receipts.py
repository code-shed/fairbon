"""Receipt scanning (vision + eBon) and personal receipt storage.

Endpoints
---------
* ``POST /api/v1/receipts/scan``  – preview parse, nothing is stored.
* ``POST /api/v1/receipts``       – store a receipt (after user correction),
  with strict opt-in for anonymised community sharing.
* ``POST /api/v1/receipts/export`` – wait, export is a GET; see export.py.

Guests are identified by an anonymous ``owner_token`` (client-generated UUID
in localStorage). No account, no email, no personal data beyond the receipt
itself.  Receipt items are stored as **cents** (integers) to avoid float
drift; prices are shared with the community only when the user explicitly
opts in, and never carry the ``owner_token`` or the ``receipt_id``.
"""

from __future__ import annotations

import contextlib
import re
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Form, HTTPException, Request, UploadFile

from ...config import get_settings
from ...services.rate_limit import allow_scan
from ...services.receipt_import import OcrUnavailable, extract_text
from ...services.receipt_vision import (
    BYOK_HEADER,
    BYOK_PROVIDER_HEADER,
    VisionError,
    extract_with_vision,
)
from ...services.upload_security import (
    ImageSanitizeError,
    UnsupportedReceipt as _UnsupportedReceipt,
    UploadTooLarge,
    sanitize,
)
from ...storage import Repository
from .history import get_repository

router = APIRouter(prefix="/receipts", tags=["receipts"])

_PLZ_RE = re.compile(r"^[0-9]{4,5}$")

#: Categories allowed for receipt items (spec §3).
CATEGORIES: frozenset[str] = frozenset(
    {
        "Lebensmittel",
        "Getränke",
        "Drogerie",
        "Haushalt",
        "Bäcker/Gastronomie",
        "Technik/Non-Food",
        "Pfand",
        "Sonstiges",
    }
)

#: Categories that must never be shared with the community.
_PRIVATE_ONLY_CATEGORIES: frozenset[str] = frozenset(
    {
        "Pfand",
        "Technik/Non-Food",
    }
)


def _owner_token(request: Request) -> str:
    """Anonymous guest token from the ``X-Owner-Token`` header."""

    token = (request.headers.get("x-owner-token") or "").strip()
    if not token or len(token) < 8 or len(token) > 128:
        raise HTTPException(
            status_code=422,
            detail="X-Owner-Token fehlt (mind. 8 Zeichen, anonyme Gast-UUID).",
        )
    return token


def _normalize_plz(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = value.strip()
    if not _PLZ_RE.fullmatch(cleaned):
        return None
    return cleaned


async def _scan_upload(
    request: Request,
    *,
    data: bytes,
    filename: str,
    content_type: str,
    repository: Repository,
) -> dict[str, Any] | None:
    """Run the vision pipeline for an uploaded image, or eBon for text/PDF.

    Returns ``None`` when the upload should go through the local text parser
    instead (text/PDF without vision, no vision configured).
    """

    settings = get_settings()

    # 1. Enforce scan budget (per IP + global), skip for BYOK users.
    user_key = (request.headers.get(BYOK_HEADER) or "").strip()
    if not user_key and content_type.startswith("image/"):
        allowed, reason = allow_scan(request)
        if not allowed:
            raise HTTPException(status_code=429, detail=reason)
        from ...services.rate_limit import scan_daily_global

        if scan_daily_global.count() >= int(settings.max_global_scans_per_day):
            raise HTTPException(
                status_code=429,
                detail=(
                    "Das heutige Gratis-Kontingent für Foto-Scans ist aufgebraucht – "
                    "eBon-PDF/Text, Haushaltsbuch, Export und Preisvergleich "
                    "funktionieren weiter!"
                ),
            )

    try:
        cleaned = sanitize(data)
    except (UploadTooLarge, _UnsupportedReceipt, ImageSanitizeError) as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc

    if cleaned.kind == "pdf":
        return None  # PDFs go through the local text extraction path

    if not user_key and not settings.vision_primary_api_key:
        # No vision configured: fail gracefully (fall back to local text if
        # a tesseract stack exists; else a clear message).
        return None

    try:
        result = await extract_with_vision(
            cleaned,
            user_key=user_key,
            user_provider=(request.headers.get(BYOK_PROVIDER_HEADER) or "").strip(),
        )
    except VisionError as exc:
        message = str(exc)
        status = 503 if "nicht konfiguriert" in message else 502
        raise HTTPException(status_code=status, detail=message) from exc

    if not user_key:
        scan_daily_global.increment()

    return result.as_dict()


@router.post(
    "/scan",
    summary="Vorschau eines Kassenbon-Scans (ohne Speichern)",
)
async def scan_receipt(
    request: Request,
    repository: Annotated[Repository, Depends(get_repository)],
    file: UploadFile,
    turnstile_token: Annotated[str, Form()] = "",
) -> dict[str, Any]:
    """Parse a receipt photo / PDF / text and return a preview.

    Nothing is stored.  Images use the configured vision provider (with
    automatic fallback); PDFs and plain text are parsed locally for free.
    When ``TURNSTILE_*`` keys are configured, a valid ``turnstile_token``
    is required for image scans.
    """

    from ...services.turnstile import verify_turnstile

    if not await verify_turnstile(turnstile_token or None):
        raise HTTPException(
            status_code=403,
            detail="Bot-Schutz (Turnstile) fehlgeschlagen – bitte erneut versuchen.",
        )

    data = await file.read()
    result = await _scan_upload(
        request,
        data=data,
        filename=file.filename or "",
        content_type=file.content_type or "",
        repository=repository,
    )

    if result is not None:
        return result

    # eBon / PDF / text path (0 € API costs)
    try:
        extraction = extract_text(
            data, filename=file.filename or "", content_type=file.content_type or ""
        )
    except _UnsupportedReceipt as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except OcrUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    from ...services.receipts import parse_receipt_text

    parsed = parse_receipt_text(extraction.text)
    return {**parsed.as_dict(), "engine": extraction.engine}


@router.get("", summary="Eigene Kassenbons auflisten")
async def list_receipts(
    request: Request,
    repository: Annotated[Repository, Depends(get_repository)],
) -> list[dict[str, Any]]:
    """Return all receipts of the anonymous owner (newest first)."""

    owner_token = _owner_token(request)
    receipts = repository.user_receipts_for(owner_token)
    result: list[dict[str, Any]] = []
    for receipt in receipts:
        items = repository.user_receipt_items_for(int(receipt["id"]))
        result.append(
            {
                **receipt,
                "item_count": len(items),
                "items": items,
            }
        )
    return result


@router.get("/stats", summary="Ausgaben-Statistik der eigenen Bons")
async def receipt_stats(
    request: Request,
    repository: Annotated[Repository, Depends(get_repository)],
    month: str = "",
) -> dict[str, Any]:
    """Monthly totals and category breakdown for the overview tab."""

    owner_token = _owner_token(request)
    receipts = repository.user_receipts_for(owner_token)

    by_month: dict[str, int] = {}
    categories: dict[str, int] = {}
    shared_count = 0
    selected_total = 0
    selected_count = 0

    for receipt in receipts:
        receipt_month = str(receipt["receipt_date"] or "")[:7]
        total = int(receipt["total_cents"] or 0)
        by_month[receipt_month] = by_month.get(receipt_month, 0) + total
        if int(receipt["shared_to_community"] or 0):
            shared_count += 1
        if month and receipt_month != month:
            continue
        selected_total += total
        selected_count += 1
        for item in repository.user_receipt_items_for(int(receipt["id"])):
            if item["is_private"]:
                continue
            category = str(item["category"] or "Sonstiges")
            categories[category] = categories.get(category, 0) + int(
                item["price_cents"] or 0
            )

    months = sorted(by_month, reverse=True)
    average = round(selected_total / selected_count) if selected_count else 0

    return {
        "month": month or (months[0] if months else ""),
        "total_cents": selected_total,
        "receipt_count": selected_count,
        "average_cents": average,
        "shared_count": shared_count,
        "by_month": [
            {"month": m, "total_cents": by_month[m]} for m in months
        ],
        "categories": sorted(
            (
                {"category": category, "total_cents": value}
                for category, value in categories.items()
            ),
            key=lambda entry: entry["total_cents"],
            reverse=True,
        ),
    }


@router.get("/{receipt_id}", summary="Einen eigenen Kassenbon im Detail")
async def get_receipt(
    receipt_id: int,
    request: Request,
    repository: Annotated[Repository, Depends(get_repository)],
) -> dict[str, Any]:
    owner_token = _owner_token(request)
    receipt = repository.user_receipt(receipt_id=receipt_id, owner_token=owner_token)
    if receipt is None:
        raise HTTPException(status_code=404, detail="Beleg nicht gefunden.")
    return {
        **receipt,
        "items": repository.user_receipt_items_for(receipt_id),
    }


@router.delete("/{receipt_id}", summary="Eigenen Kassenbon löschen")
async def delete_receipt(
    receipt_id: int,
    request: Request,
    repository: Annotated[Repository, Depends(get_repository)],
) -> dict[str, bool]:
    owner_token = _owner_token(request)
    deleted = repository.delete_user_receipt(
        receipt_id=receipt_id, owner_token=owner_token
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="Beleg nicht gefunden.")
    return {"deleted": True}


@router.patch(
    "/{receipt_id}/items/{item_id}",
    summary="Privat-Markierung einer Bon-Zeile setzen",
)
async def set_item_private(
    receipt_id: int,
    item_id: int,
    request: Request,
    repository: Annotated[Repository, Depends(get_repository)],
    is_private: Annotated[bool, Form()] = True,
) -> dict[str, bool]:
    owner_token = _owner_token(request)
    updated = repository.set_receipt_item_private(
        item_id=item_id,
        receipt_id=receipt_id,
        owner_token=owner_token,
        is_private=is_private,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Position nicht gefunden.")
    return {"is_private": is_private}


@router.post("", summary="Kassenbon speichern (privat + optional Community)")
async def save_receipt(
    request: Request,
    repository: Annotated[Repository, Depends(get_repository)],
    store: Annotated[str, Form()] = "",
    postal_code: Annotated[str, Form()] = "",
    country_code: Annotated[str, Form()] = "DE",
    currency: Annotated[str, Form()] = "EUR",
    receipt_date: Annotated[str, Form()] = "",
    total_cents: Annotated[int, Form()] = 0,
    share_anonymized: Annotated[bool, Form()] = False,
    is_demo: Annotated[bool, Form()] = False,
    items_json: Annotated[str, Form()] = "[]",
) -> dict[str, Any]:
    """Create a personal receipt.

    The client sends the corrected items as a JSON string in ``items_json``.
    ``share_anonymized`` (opt-in) publishes suitable lines to the community
    price pool — without the owner token and without the receipt id.
    """

    owner_token = _owner_token(request)
    import json

    try:
        items: list[dict[str, Any]] = json.loads(items_json)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=422, detail="items_json ist kein valides JSON."
        ) from exc
    if not isinstance(items, list):
        raise HTTPException(
            status_code=422, detail="items_json muss eine Liste sein."
        )

    clean_store = store.strip()
    if not clean_store:
        clean_store = "Sonstiges"
    plz = _normalize_plz(postal_code)

    receipt_id = repository.insert_user_receipt(
        owner_token=owner_token,
        store=clean_store,
        postal_code=plz,
        country_code=(country_code or "DE").upper()[:2],
        currency=(currency or "EUR").upper()[:3],
        receipt_date=receipt_date,
        total_cents=int(total_cents),
        shared_to_community=bool(share_anonymized),
        items=items,
    )

    # Self-learning aliases: remember how the market abbreviated each line.
    # Demo receipts are synthetic and must not pollute the alias table.
    from ...normalization.matcher import normalize_title

    for item in ([] if is_demo else items):
        raw_text = str(item.get("raw_text") or "").strip()
        normalized = str(item.get("normalized_name") or "").strip()
        if not raw_text or not normalized:
            continue
        with contextlib.suppress(Exception):  # alias learning must never fail a save
            repository.upsert_alias(
                store=clean_store,
                raw_text_norm=normalize_title(raw_text),
                normalized_name=normalized,
                brand=item.get("brand"),
                category=item.get("category"),
                quantity=item.get("quantity"),
                unit=item.get("unit"),
            )

    # Community opt-in: share only eligible lines, without any owner data.
    shared_count = 0
    if share_anonymized:
        for item in items:
            category = str(item.get("category") or "Sonstiges")
            if category in _PRIVATE_ONLY_CATEGORIES:
                continue
            if item.get("is_private"):
                continue
            if item.get("deposit_cents"):  # Pfand is never shared
                continue
            # Use the existing community machinery (validator, visibility).
            try:
                await _share_to_community(repository, clean_store, plz, item)
                shared_count += 1
            except Exception:  # pragma: no cover - sharing must never fail the save
                continue

    return {
        "receipt_id": receipt_id,
        "shared_count": shared_count,
    }


async def _share_to_community(
    repository: Repository, store: str, postal_code: str | None, item: dict[str, Any]
) -> None:
    """Write an anonymised community price (validated; never leaks owner)."""

    import asyncio

    from ...storage.community import CommunityPriceInput

    name = (item.get("normalized_name") or item.get("raw_text") or "").strip()
    if not name:
        return
    price_cents = int(item.get("price_cents") or 0)
    if price_cents <= 0:
        return

    quantity = float(item.get("quantity") or 1.0)
    unit = str(item.get("unit") or "stueck").strip().lower()
    if unit not in ("g", "kg", "ml", "l"):
        unit = "stueck"

    entry = CommunityPriceInput(
        name=name,
        store=store,
        price=round(price_cents / 100.0, 2),
        postal_code=postal_code or "00000",
        ean=None,
        unit=unit,
        quantity=quantity,
        scout_id=None,  # deliberately anonymous — no owner linkage
        source="receipt",
        receipt_id=None,  # never link back to the personal receipt
    )

    # The CommunityStore runs the price_validator (incl. pending_review
    # quarantine) and only approved/verified entries become visible.
    community = repository.community
    if hasattr(community, "add_price"):
        await asyncio.to_thread(community.add_price, entry)
    else:  # pragma: no cover - defensive
        community.add_price(entry)


__all__ = ["CATEGORIES", "router"]
