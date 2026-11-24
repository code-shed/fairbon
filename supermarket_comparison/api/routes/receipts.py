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

import asyncio
import contextlib
import re
import time
from datetime import UTC, date, datetime
from typing import Annotated, Any, Final

from fastapi import (
    APIRouter,
    Body,
    Depends,
    Form,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
)

from ...config import get_settings
from ...normalization.categories import RECEIPT_CATEGORIES, normalize_category
from ...normalization.matcher import normalize_title
from ...normalization.stores import normalize_store
from ...services.barcode import is_ambiguous_term, lookup_barcode
from ...services.budget import budget_period
from ...services.pdf_pages import MAX_PDF_PAGES, PdfUnreadable, pdf_page_images
from ...services.rate_limit import allow_scan, client_ip, scan_daily_global
from ...services.receipt_import import OcrUnavailable, extract_text, try_ocr_page
from ...services.receipt_vision import (
    BYOK_HEADER,
    BYOK_PROVIDER_HEADER,
    VisionError,
    VisionKeyRejected,
    extract_with_vision,
)
from ...services.receipts import parse_receipt_text
from ...services.upload_security import (
    ImageSanitizeError,
    UnsupportedReceipt as _UnsupportedReceipt,
    UploadTooLarge,
    is_plain_text,
    sanitize,
)
from ...storage import Repository
from .history import get_repository

router = APIRouter(prefix="/receipts", tags=["receipts"])

_PLZ_RE = re.compile(r"^[0-9]{4,5}$")

#: Categories allowed for receipt items (spec §3).
CATEGORIES: frozenset[str] = frozenset(RECEIPT_CATEGORIES)

#: Only these categories are relevant for the price comparison. Other
#: lines stay in the private household book and export (bakery, tech,
#: deposits, unknown items).
_COMMUNITY_CATEGORIES: frozenset[str] = frozenset(
    {"Lebensmittel", "Getränke", "Drogerie", "Haushalt"}
)


#: Shown when the server-funded daily scan budget is used up.
FREE_SCAN_QUOTA_MESSAGE: Final = (
    "Das heutige Gratis-Kontingent für Foto-Scans ist aufgebraucht – "
    "eBon-PDF/Text, Haushaltsbuch, Export und Preisvergleich "
    "funktionieren weiter!"
)
#: Minimum mean Tesseract confidence for a local preview at all.
OCR_MIN_CONFIDENCE: Final = 60.0
#: At or above this confidence, a reconciling page needs no review warning.
OCR_TRUSTED_CONFIDENCE: Final = 80.0
#: Allowed gap between item sum and printed total (cents) for trusted OCR.
OCR_TOTAL_TOLERANCE_CENTS: Final = 100
#: Shown for PDFs without any text that vision cannot read either.
NO_TEXT_LAYER_WARNING: Final = (
    "Dieses PDF hat keinen Textlayer (gescannt). Die Auswertung gescannter "
    "Seiten braucht die Vision-API."
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


def _text_scan_payload(parsed: Any) -> dict[str, Any]:
    """Map a local text parse to the same shape vision/PDF previews use."""

    items = []
    for item in parsed.items:
        price_cents = round(float(item.price or 0) * 100)
        items.append(
            {
                "raw_text": item.raw_line or item.name,
                "normalized_name": item.name,
                "brand": None,
                "category": "Sonstiges",
                "quantity": item.quantity or 1.0,
                "unit": item.unit or "stueck",
                "price_cents": price_cents,
                "unit_price_cents": None,
                "discount_cents": 0,
                "deposit_cents": 0,
                "vat_rate": None,
                "is_private": False,
            }
        )
    return {
        "store": parsed.store,
        "postal_code": parsed.postal_code,
        "total": parsed.total,
        "total_cents": round(float(parsed.total or 0) * 100),
        "items": items,
        "warnings": list(parsed.warnings),
    }


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

    try:
        cleaned = await asyncio.to_thread(sanitize, data)
    except (UploadTooLarge, _UnsupportedReceipt, ImageSanitizeError) as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc

    if cleaned.kind == "pdf":
        return None  # PDFs go through the local text extraction path

    if not user_key and not settings.vision_primary_api_key:
        # No vision configured: fail gracefully (fall back to local text if
        # a tesseract stack exists; else a clear message).
        return None

    # Reserve the server-funded budget atomically right before the paid call.
    if not user_key:
        from ...services.rate_limit import scan_daily_global

        if not scan_daily_global.try_increment(settings.max_global_scans_per_day):
            raise HTTPException(status_code=429, detail=FREE_SCAN_QUOTA_MESSAGE)

    try:
        result = await extract_with_vision(
            cleaned,
            user_key=user_key,
            user_provider=(request.headers.get(BYOK_PROVIDER_HEADER) or "").strip(),
        )
    except VisionKeyRejected as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except VisionError as exc:
        message = str(exc)
        status = 503 if "nicht konfiguriert" in message else 502
        raise HTTPException(status_code=status, detail=message) from exc

    return result.as_dict()


def _ocr_page_receipt(jpeg: bytes, *, page: int) -> dict[str, Any] | None:
    """Read one scanned page locally; ``None`` when OCR finds too little."""

    ocr = try_ocr_page(jpeg)
    if ocr is None or ocr.confidence < OCR_MIN_CONFIDENCE:
        return None
    parsed = parse_receipt_text(ocr.text)
    if not parsed.items or parsed.total is None:
        return None
    item_cents = round(sum(item.price for item in parsed.items) * 100)
    declared_cents = round(parsed.total * 100)
    review = ocr.confidence < OCR_TRUSTED_CONFIDENCE or abs(
        item_cents - declared_cents
    ) > max(OCR_TOTAL_TOLERANCE_CENTS, round(declared_cents * 0.02))

    items: list[dict[str, Any]] = []
    for item in parsed.items:
        items.append(
            {
                "raw_text": item.raw_line or item.name,
                "normalized_name": item.name,
                "brand": None,
                "category": "Sonstiges",
                "quantity": item.quantity,
                "unit": item.unit,
                "price_cents": round(item.price * 100),
                "unit_price_cents": (
                    round(item.unit_price * 100)
                    if item.unit_price is not None
                    else None
                ),
                "discount_cents": 0,
                "deposit_cents": 0,
                "vat_rate": None,
                "is_private": False,
            }
        )
    return {
        "store": parsed.store,
        "postal_code": parsed.postal_code,
        "date": None,
        "currency": "EUR",
        "total_cents": declared_cents,
        "items": items,
        "engine": "ocr",
        "provider": "tesseract",
        "page": page,
        "ocr_review": review,
    }


async def _scan_pdf_pages(request: Request, *, data: bytes) -> dict[str, Any] | None:
    """Read every page of a scanned PDF, OCR first and vision as fallback.

    Local OCR is free and trusted when it reconciles with the printed
    total. Pages that OCR cannot read – or reads only partially – go to
    the vision provider, one paid call and one daily-budget unit per such
    page. If vision fails, a partially read page still returns as an OCR
    preview that is flagged for review. Uploads with the user's own key
    skip the budget, as photos do.
    """

    settings = get_settings()
    user_key = (request.headers.get(BYOK_HEADER) or "").strip()
    allowed, reason = allow_scan(request)
    if not allowed:
        raise HTTPException(status_code=429, detail=reason)
    try:
        pages = await asyncio.to_thread(pdf_page_images, data)
    except PdfUnreadable as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not pages.jpeg_pages:
        return None

    receipts: list[dict[str, Any]] = []
    warnings: list[str] = []
    vision_pages: list[tuple[int, bytes]] = []
    ocr_candidates: dict[int, dict[str, Any]] = {}
    for number, jpeg in pages.jpeg_pages:
        local = await asyncio.to_thread(_ocr_page_receipt, jpeg, page=number)
        if local is None:
            vision_pages.append((number, jpeg))
        elif local.pop("ocr_review", False):
            ocr_candidates[number] = local
            vision_pages.append((number, jpeg))
        else:
            receipts.append(local)

    def accept_ocr_candidate(number: int) -> bool:
        candidate = ocr_candidates.pop(number, None)
        if candidate is None:
            return False
        warnings.append(
            f"Seite {number} wurde lokal per OCR gelesen – bitte "
            "Beträge und fehlende Artikel prüfen."
        )
        receipts.append(candidate)
        return True

    provider_ready = bool(
        user_key
        or settings.vision_primary_api_key
        or (settings.vision_fallback_provider and settings.vision_fallback_api_key)
    )
    if vision_pages and not provider_ready:
        for number, _ in vision_pages:
            if not accept_ocr_candidate(number):
                warnings.append(f"Seite {number} konnte nicht gelesen werden.")
        vision_pages = []

    if vision_pages and not user_key:
        reserved = scan_daily_global.try_increment(
            settings.max_global_scans_per_day, amount=len(vision_pages)
        )
        if not reserved:
            if not receipts and not ocr_candidates:
                raise HTTPException(status_code=429, detail=FREE_SCAN_QUOTA_MESSAGE)
            warnings.append(FREE_SCAN_QUOTA_MESSAGE)
            for number, _ in vision_pages:
                accept_ocr_candidate(number)
            vision_pages = []

    provider = (request.headers.get(BYOK_PROVIDER_HEADER) or "").strip()
    vision_used = False
    last_error = ""
    for number, jpeg in vision_pages:
        try:
            cleaned = await asyncio.to_thread(sanitize, jpeg)
            result = await extract_with_vision(
                cleaned, user_key=user_key or None, user_provider=provider
            )
        except VisionKeyRejected as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except VisionError as exc:
            last_error = str(exc)
            if not accept_ocr_candidate(number):
                warnings.append(f"Seite {number} konnte nicht gelesen werden.")
            continue
        except (ImageSanitizeError, UploadTooLarge, _UnsupportedReceipt):
            if not accept_ocr_candidate(number):
                warnings.append(f"Seite {number} ist kein lesbares Bild.")
            continue
        vision_used = True
        ocr_candidates.pop(number, None)
        receipts.append({**result.as_dict(), "page": number})

    if not receipts:
        if last_error:
            raise HTTPException(status_code=502, detail=last_error)
        return None

    receipts.sort(key=lambda receipt: receipt.get("page") or 0)
    if pages.page_count > MAX_PDF_PAGES:
        warnings.append(
            f"Nur die ersten {MAX_PDF_PAGES} von {pages.page_count} Seiten "
            "wurden gelesen."
        )
    return {
        **receipts[0],
        "engine": "vision-pdf" if vision_used else "ocr",
        "receipts": receipts,
        "warnings": warnings,
    }


def _finish_scan(
    response: Response,
    payload: dict[str, Any],
    started: float,
) -> dict[str, Any]:
    """Add timing metadata without leaking keys, image data or user details."""

    duration_ms = round((time.perf_counter() - started) * 1000)
    engine = str(payload.get("engine") or "")
    provider = str(payload.get("provider") or "")
    method = (
        "vision"
        if "vision" in engine or (provider and provider != "tesseract")
        else "ebon_local"
    )
    response.headers["Server-Timing"] = (
        f"total;dur={duration_ms}, method;desc={method}"
    )
    return {**payload, "duration_ms": duration_ms, "method": method}


@router.post(
    "/scan",
    summary="Vorschau eines Kassenbon-Scans (ohne Speichern)",
)
async def scan_receipt(
    request: Request,
    response: Response,
    repository: Annotated[Repository, Depends(get_repository)],
    file: UploadFile,
    turnstile_token: Annotated[str, Form()] = "",
) -> dict[str, Any]:
    """Parse a receipt photo / PDF / text and return a preview.

    Nothing is stored.  Images use the configured vision provider (with
    automatic fallback); PDFs and plain text are parsed locally for free.
    When ``TURNSTILE_*`` keys are configured, a valid ``turnstile_token``
    is required for scans.
    """

    from ...services.turnstile import verify_turnstile

    started = time.perf_counter()
    if not await verify_turnstile(
        turnstile_token or None, remote_ip=client_ip(request)
    ):
        raise HTTPException(
            status_code=403,
            detail="Bot-Schutz (Turnstile) fehlgeschlagen – bitte erneut versuchen.",
        )

    settings = get_settings()
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > settings.max_upload_bytes:
        raise HTTPException(status_code=413, detail="Upload zu groß (max. 3 MB).")
    if getattr(file, "size", None) and file.size > settings.max_upload_bytes:
        raise HTTPException(status_code=413, detail="Upload zu groß (max. 3 MB).")

    data = await file.read()
    # Plain-text eBon receipts never enter the image/PDF sanitizer (and
    # never reach a paid vision provider).
    if is_plain_text(data, file.content_type, file.filename):
        try:
            extraction = await asyncio.to_thread(
                extract_text,
                data,
                filename=file.filename or "",
                content_type="text/plain",
            )
        except OcrUnavailable as exc:  # pragma: no cover - no OCR for text
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        payload = _text_scan_payload(
            await asyncio.to_thread(parse_receipt_text, extraction.text)
        )
        return _finish_scan(
            response, {**payload, "engine": extraction.engine}, started
        )

    result = await _scan_upload(
        request,
        data=data,
        filename=file.filename or "",
        content_type=file.content_type or "",
        repository=repository,
    )

    if result is not None:
        return _finish_scan(response, result, started)

    # eBon / PDF / text path (0 € API costs)
    try:
        extraction = await asyncio.to_thread(
            extract_text,
            data,
            filename=file.filename or "",
            content_type=file.content_type or "",
        )
    except _UnsupportedReceipt as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except OcrUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    payload = (
        await asyncio.to_thread(parse_receipt_text, extraction.text)
    ).as_dict()
    if extraction.engine == "pdf" and not payload.get("items"):
        scanned = await _scan_pdf_pages(request, data=data)
        if scanned is not None:
            return _finish_scan(response, scanned, started)
        if not extraction.text.strip():
            payload["warnings"] = [*payload.get("warnings", []), NO_TEXT_LAYER_WARNING]
    return _finish_scan(
        response, {**payload, "engine": extraction.engine}, started
    )


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
        public = {k: v for k, v in receipt.items() if k != "owner_token"}
        result.append(
            {
                **public,
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
    start_day: Annotated[int, Query(ge=1, le=28)] = 1,
) -> dict[str, Any]:
    """Totals for the budget period plus all calendar months for navigation."""

    owner_token = _owner_token(request)
    receipts = repository.user_receipts_for(owner_token)

    period_month = month or date.today().strftime("%Y-%m")
    try:
        year, period_number = (int(part) for part in period_month.split("-")[:2])
    except (TypeError, ValueError):
        today = date.today()
        year, period_number = today.year, today.month
    period_start, period_end = budget_period(year, period_number, start_day)
    low, high = period_start.isoformat(), period_end.isoformat()

    by_month: dict[str, int] = {}
    categories: dict[str, int] = {}
    shared_count = 0
    selected_total = 0
    selected_count = 0
    discount_total = 0

    for receipt in receipts:
        receipt_month = str(receipt["receipt_date"] or "")[:7]
        total = int(receipt["total_cents"] or 0)
        by_month[receipt_month] = by_month.get(receipt_month, 0) + total
        if int(receipt["shared_to_community"] or 0):
            shared_count += 1
        receipt_date = str(receipt["receipt_date"] or "")
        if not receipt_date or not (low <= receipt_date <= high):
            continue
        selected_total += total
        selected_count += 1
        for item in repository.user_receipt_items_for(int(receipt["id"])):
            discount_total += int(item["discount_cents"] or 0)
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
        "period": {"from": low, "to": high, "start_day": start_day},
        "total_cents": selected_total,
        "discount_cents": discount_total,
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


@router.get("/backup", summary="Alle eigenen Bons als JSON-Backup")
async def export_backup(
    request: Request,
    repository: Annotated[Repository, Depends(get_repository)],
) -> dict[str, Any]:
    """Export every receipt and item of the owner — a real data backup.

    Unlike the access token this contains the actual data (never the token).
    """

    owner_token = _owner_token(request)
    receipts: list[dict[str, Any]] = []
    for receipt in repository.user_receipts_for(owner_token):
        entry = {
            key: receipt.get(key)
            for key in (
                "store", "postal_code", "country_code", "currency",
                "receipt_date", "total_cents", "shared_to_community",
                "is_business",
            )
        }
        entry["items"] = [
            {
                key: item.get(key)
                for key in (
                    "raw_text", "normalized_name", "brand", "category", "ean",
                    "quantity", "unit", "unit_price_cents", "price_cents",
                    "discount_cents", "deposit_cents", "vat_rate", "is_private",
                )
            }
            for item in repository.user_receipt_items_for(int(receipt["id"]))
        ]
        receipts.append(entry)
    return {"version": 1, "exported_at": datetime.now(UTC).isoformat(),
            "receipts": receipts}


@router.post("/backup/import", summary="JSON-Backup wiederherstellen")
async def import_backup(
    request: Request,
    repository: Annotated[Repository, Depends(get_repository)],
    payload: Annotated[dict[str, Any], Body()],
) -> dict[str, int]:
    """Restore receipts for the current owner; validates every field."""

    owner_token = _owner_token(request)
    if payload.get("version") != 1 or not isinstance(
        payload.get("receipts"), list
    ):
        raise HTTPException(status_code=422, detail="Ungültiges Backup-Format.")
    if len(payload["receipts"]) > 500:
        raise HTTPException(status_code=422, detail="Backup zu groß (max. 500 Bons).")

    imported = 0
    item_count = 0
    for raw_receipt in payload["receipts"]:
        if not isinstance(raw_receipt, dict):
            raise HTTPException(status_code=422, detail="Ungültiger Bon im Backup.")
        raw_items = raw_receipt.get("items") or []
        if not isinstance(raw_items, list) or len(raw_items) > 120:
            raise HTTPException(status_code=422, detail="Zu viele Positionen im Bon.")
        items: list[dict[str, Any]] = []
        for raw_item in raw_items:
            if not isinstance(raw_item, dict):
                raise HTTPException(status_code=422, detail="Ungültige Position.")
            name = str(raw_item.get("normalized_name") or "")[:200].strip()
            if not name:
                continue
            try:
                cents = int(raw_item.get("price_cents") or 0)
            except (TypeError, ValueError) as exc:
                raise HTTPException(
                    status_code=422, detail="Ungültiger Preis."
                ) from exc
            if not 0 <= cents <= 500_000:
                raise HTTPException(
                    status_code=422, detail="Preis außerhalb der Grenzen."
                )
            try:
                vat = float(raw_item.get("vat_rate") or 0)
            except (TypeError, ValueError):
                vat = 0.0
            try:
                quantity = float(raw_item.get("quantity") or 1)
            except (TypeError, ValueError):
                quantity = 1.0
            items.append(
                {
                    "raw_text": str(raw_item.get("raw_text") or "")[:200],
                    "normalized_name": name,
                    "brand": str(raw_item.get("brand") or "")[:200] or None,
                    "category": normalize_category(raw_item.get("category")),
                    "ean": str(raw_item.get("ean") or "")[:32] or None,
                    "quantity": max(0.01, quantity),
                    "unit": str(raw_item.get("unit") or "stueck")[:20],
                    "unit_price_cents": raw_item.get("unit_price_cents"),
                    "price_cents": cents,
                    "discount_cents": int(raw_item.get("discount_cents") or 0),
                    "deposit_cents": int(raw_item.get("deposit_cents") or 0),
                    "vat_rate": vat,
                    "is_private": bool(raw_item.get("is_private")),
                }
            )
        date_text = str(raw_receipt.get("receipt_date") or "")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_text):
            raise HTTPException(status_code=422, detail="Ungültiges Belegdatum.")
        try:
            total = int(raw_receipt.get("total_cents") or 0)
        except (TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=422, detail="Ungültige Gesamtsumme."
            ) from exc
        if not 0 <= total <= 50_000_000:
            raise HTTPException(status_code=422, detail="Summe außerhalb der Grenzen.")
        repository.insert_user_receipt(
            owner_token=owner_token,
            store=normalize_store(str(raw_receipt.get("store") or "")[:100]),
            postal_code=_normalize_plz(raw_receipt.get("postal_code")),
            country_code=str(raw_receipt.get("country_code") or "DE")[:2],
            currency=str(raw_receipt.get("currency") or "EUR")[:3],
            receipt_date=date_text,
            total_cents=total,
            shared_to_community=bool(raw_receipt.get("shared_to_community")),
            is_business=bool(raw_receipt.get("is_business")),
            items=items,
        )
        imported += 1
        item_count += len(items)
    return {"imported": imported, "items": item_count}


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
    public = {k: v for k, v in receipt.items() if k != "owner_token"}
    return {
        **public,
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
    "/{receipt_id}",
    summary="Händler eines Bons korrigieren",
)
async def edit_receipt_store(
    receipt_id: int,
    request: Request,
    repository: Annotated[Repository, Depends(get_repository)],
    payload: Annotated[dict[str, Any], Body()],
) -> dict[str, Any]:
    owner_token = _owner_token(request)
    fields: dict[str, Any] = {}
    if "store" in payload:
        fields["store"] = str(payload["store"] or "").strip()[:100] or "Sonstiges"
    if "receipt_date" in payload:
        date_text = str(payload["receipt_date"] or "")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_text):
            raise HTTPException(status_code=422, detail="Ungültiges Belegdatum.")
        fields["receipt_date"] = date_text
    if "total_cents" in payload:
        try:
            total = int(payload["total_cents"])
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail="Ungültige Summe.") from exc
        if not 0 <= total <= 50_000_000:
            raise HTTPException(status_code=422, detail="Summe außerhalb der Grenzen.")
        fields["total_cents"] = total
    updated = repository.update_user_receipt(
        receipt_id=receipt_id, owner_token=owner_token, fields=fields
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="Beleg nicht gefunden.")
    return {key: updated.get(key) for key in fields} or {"ok": True}


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


@router.post(
    "/items/{item_id}/link-barcode",
    summary="Barcode mit einer Bon-Zeile verknüpfen (Open Food Facts)",
)
async def link_item_barcode(
    item_id: int,
    request: Request,
    repository: Annotated[Repository, Depends(get_repository)],
    payload: Annotated[dict[str, Any], Body()],
    preview: Annotated[bool, Query()] = False,
) -> dict[str, Any]:
    """Link an EAN to one item; a failed upstream lookup never blocks it."""

    owner_token = _owner_token(request)
    ean = str(payload.get("ean") or "").strip()
    if not re.fullmatch(r"\d{8,14}", ean):
        raise HTTPException(status_code=422, detail="Ungültige EAN/GTIN.")

    item = repository.item_for_owner(item_id=item_id, owner_token=owner_token)
    if item is None:
        raise HTTPException(status_code=404, detail="Position nicht gefunden.")

    product = await lookup_barcode(ean)
    raw_text = str(item.get("raw_text") or "")
    name = str((product or {}).get("name") or payload.get("name")
               or item.get("normalized_name") or raw_text).strip()
    brand = str((product or {}).get("brand") or payload.get("brand")
                or item.get("brand") or "").strip() or None
    quantity = (
        (product or {}).get("quantity")
        or payload.get("quantity")
        or item.get("quantity")
    )
    unit = str((product or {}).get("unit") or payload.get("unit")
               or item.get("unit") or "stueck").strip().lower()

    if preview:
        return {
            "ean": ean,
            "name": name,
            "brand": brand,
            "quantity": quantity,
            "unit": unit,
            "found_upstream": product is not None,
        }

    updated = repository.update_receipt_item(
        item_id=item_id,
        owner_token=owner_token,
        fields={
            "ean": ean,
            "normalized_name": name,
            "brand": brand,
            "quantity": quantity,
            "unit": unit,
            "is_ambiguous": is_ambiguous_term(raw_text),
        },
    ) or {}
    repository.upsert_alias(
        store=str(item.get("store") or "unbekannt"),
        raw_text_norm=normalize_title(raw_text),
        normalized_name=name,
        brand=brand,
        category=item.get("category"),
        quantity=quantity,
        unit=unit,
        ean=ean,
        is_ambiguous=is_ambiguous_term(raw_text),
        verified_count=1,
    )

    # Improve the community price as well — still without owner linkage.
    if (
        item.get("shared_to_community")
        and item.get("category") in _COMMUNITY_CATEGORIES
    ):
        with contextlib.suppress(Exception):  # sharing must not fail the link
            await _share_to_community(
                repository,
                str(item.get("store") or "unbekannt"),
                item.get("postal_code"),
                updated,
            )

    return {
        "id": item_id,
        "ean": ean,
        "name": name,
        "brand": brand,
        "quantity": quantity,
        "unit": unit,
        "found_upstream": product is not None,
    }


@router.patch(
    "/items/{item_id}",
    summary="Bon-Zeile nachbearbeiten",
)
async def edit_item(
    item_id: int,
    request: Request,
    repository: Annotated[Repository, Depends(get_repository)],
    payload: Annotated[dict[str, Any], Body()],
) -> dict[str, Any]:
    owner_token = _owner_token(request)
    fields: dict[str, Any] = {}
    if "name" in payload:
        fields["normalized_name"] = str(payload["name"] or "").strip()[:200]
    if "brand" in payload:
        fields["brand"] = str(payload["brand"] or "").strip()[:200] or None
    if "quantity" in payload:
        fields["quantity"] = max(0.01, float(payload["quantity"] or 1.0))
    if "unit" in payload:
        fields["unit"] = str(payload["unit"] or "stueck").strip()[:20]
    if "price_cents" in payload:
        cents = int(payload["price_cents"] or 0)
        if not 0 <= cents <= 500_000:
            raise HTTPException(status_code=422, detail="Preis außerhalb der Grenzen.")
        fields["price_cents"] = cents
    if "category" in payload:
        fields["category"] = normalize_category(payload["category"])
    updated = repository.update_receipt_item(
        item_id=item_id, owner_token=owner_token, fields=fields
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="Position nicht gefunden.")
    return {key: updated.get(key) for key in fields}


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
    is_business: Annotated[bool, Form()] = False,
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
    if len(items) > 120:
        raise HTTPException(
            status_code=422, detail="Maximal 120 Positionen pro Beleg."
        )
    for item in items:
        if not isinstance(item, dict):
            raise HTTPException(status_code=422, detail="Ungültige Bon-Position.")
        for field in ("raw_text", "normalized_name", "brand", "category", "unit"):
            value = item.get(field)
            if value is not None and len(str(value)) > 200:
                raise HTTPException(
                    status_code=422, detail=f"Feld '{field}' ist zu lang."
                )
        price_cents = item.get("price_cents")
        try:
            price_cents = int(price_cents or 0)
        except (TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=422, detail="Ungültiger Zeilenpreis."
            ) from exc
        if not 0 <= price_cents <= 500_000:
            raise HTTPException(
                status_code=422, detail="Zeilenpreis außerhalb der Grenzen."
            )

    for item in items:
        item["category"] = normalize_category(item.get("category"))

    clean_store = normalize_store(store)
    plz = _normalize_plz(postal_code)

    # A demo receipt is never shared, even if a client sends share=true.
    # On the hosted instance (REQUIRE_COMMUNITY_SHARING) anonymous prices are
    # shared by default — unless the user brings their own API key.
    user_key = (request.headers.get(BYOK_HEADER) or "").strip()
    hosted_auto_share = (
        bool(get_settings().require_community_sharing) and not user_key
    )
    effective_share = (
        (bool(share_anonymized) or hosted_auto_share) and not is_demo
    )

    receipt_id = repository.insert_user_receipt(
        owner_token=owner_token,
        store=clean_store,
        postal_code=plz,
        country_code=(country_code or "DE").upper()[:2],
        currency=(currency or "EUR").upper()[:3],
        receipt_date=receipt_date,
        total_cents=int(total_cents),
        shared_to_community=effective_share,
        is_business=is_business,
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
    if effective_share:
        for item in items:
            category = str(item.get("category") or "Sonstiges")
            if category not in _COMMUNITY_CATEGORIES:
                continue
            # In hosted mode is_private only controls the tax export;
            # anonymous sharing must not depend on it.
            if item.get("is_private") and not hosted_auto_share:
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
        ean=(item.get("ean") or "").strip() or None,
        unit=unit,
        quantity=quantity,
        scout_id=None,  # deliberately anonymous — no owner linkage
        source="receipt",
        receipt_id=None,  # never link back to the personal receipt
    )

    # The CommunityStore runs the price_validator (incl. pending_review
    # quarantine). Own-receipt prices are auto-verified: plausible rows go
    # straight to `verified`; flagged ones quarantine for the review queue.
    community = repository.community
    if hasattr(community, "add_price"):
        await asyncio.to_thread(
            lambda: community.add_price(entry, auto_verify=True)
        )
    else:  # pragma: no cover - defensive
        community.add_price(entry, auto_verify=True)


__all__ = ["CATEGORIES", "router"]
