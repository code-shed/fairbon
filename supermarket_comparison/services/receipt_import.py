"""Turn uploaded receipt files into text and parsed products.

Supported inputs:

===============  =====================================================
Input            Engine
===============  =====================================================
``.txt``/plain   ``text``  (deterministic, always available)
``.pdf``         ``pdf``   (text layer via ``pypdf``)
image/*          ``ocr``   (only if ``pytesseract`` + binary exist)
===============  =====================================================

Images without a local OCR stack raise :class:`OcrUnavailable`; the API turns
that into a helpful 503 instead of pretending that OCR happened.  An optional
LLM extractor can be plugged in via ``extract_with_llm`` (needs a configured
provider/key), but the default path never requires a paid service.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Any

from .receipts import ParsedReceipt, parse_receipt_text

__all__ = [
    "ExtractionResult",
    "OcrUnavailable",
    "UnsupportedReceipt",
    "extract_text",
    "import_receipt",
]

MAX_UPLOAD_BYTES = 8 * 1024 * 1024


class OcrUnavailable(RuntimeError):
    """Raised when an image is uploaded but no OCR stack is installed."""


class UnsupportedReceipt(RuntimeError):
    """Raised for file types the importer cannot read."""


@dataclass
class ExtractionResult:
    text: str
    engine: str


def _decode(data: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _extract_pdf(data: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - dependency is declared
        raise UnsupportedReceipt(
            "PDF-Unterstützung ist nicht installiert (pypdf fehlt)."
        ) from exc

    reader = PdfReader(io.BytesIO(data))
    chunks: list[str] = []
    for page in reader.pages:
        try:
            chunks.append(page.extract_text() or "")
        except Exception:  # pragma: no cover - defensive, corrupt PDFs
            continue
    return "\n".join(chunks)


def _extract_image(data: bytes) -> str:
    try:
        import pytesseract  # type: ignore[import-not-found]
        from PIL import Image  # type: ignore[import-not-found]
    except ImportError as exc:
        raise OcrUnavailable(
            "Für Bilder ist lokal keine OCR installiert (pytesseract/Pillow). "
            "Bitte den Bon-Text einfügen oder ein PDF mit Textlayer hochladen."
        ) from exc

    try:
        image = Image.open(io.BytesIO(data))
        return pytesseract.image_to_string(image, lang="deu")
    except Exception as exc:  # pragma: no cover - depends on host binaries
        raise OcrUnavailable(
            "Die OCR konnte das Bild nicht lesen. Bitte Bon-Text einfügen."
        ) from exc


def extract_text(
    data: bytes,
    *,
    content_type: str | None = None,
    filename: str | None = None,
) -> ExtractionResult:
    """Return the plain text of an uploaded receipt."""

    if len(data) > MAX_UPLOAD_BYTES:
        raise UnsupportedReceipt("Die Datei ist größer als 8 MB.")

    kind = (content_type or "").split(";")[0].strip().lower()
    suffix = (filename or "").lower().rsplit(".", 1)[-1] if filename else ""

    if kind.startswith("text/") or (filename and suffix in {"txt", "csv", "text"}):
        return ExtractionResult(text=_decode(data), engine="text")

    if content_type == "application/pdf" or suffix == "pdf":
        return ExtractionResult(text=_extract_pdf(data), engine="pdf")

    if (content_type or "").startswith("image/") or suffix in {
        "jpg",
        "jpeg",
        "png",
        "webp",
        "heic",
        "heif",
    }:
        return ExtractionResult(text=_extract_image(data), engine="ocr")

    raise UnsupportedReceipt(
        "Nicht unterstütztes Format. Bitte .txt, .pdf oder ein Bild verwenden."
    )


def import_receipt(
    *,
    community: Any,
    text: str,
    postal_code: str | None,
    scout_id: str | None,
    receipt_id: str | None = None,
    source: str = "receipt",
) -> tuple[ParsedReceipt, list[dict[str, Any]]]:
    """Parse *text* and store every recognised item as a community price."""

    from ..storage import CommunityPriceInput

    parsed = parse_receipt_text(text)
    effective_plz = (postal_code or parsed.postal_code or "").strip()
    effective_store = parsed.store or "unbekannt"

    created: list[dict[str, Any]] = []
    if not effective_plz:
        return parsed, created

    for item in parsed.items:
        entry = CommunityPriceInput(
            name=item.name,
            store=effective_store,
            price=item.price,
            postal_code=effective_plz,
            ean=item.ean,
            unit=item.unit,
            quantity=item.quantity,
            unit_price=item.unit_price,
            scout_id=scout_id,
            source=source,
            receipt_id=receipt_id,
        )
        created.append(community.add_price(entry))
    return parsed, created
