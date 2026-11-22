"""Page images of scanned PDFs (no text layer) for the vision scanner.

A scanner or a phone "scan to PDF" stores every receipt as one embedded image
per page. We take the largest image of each page, decode it with Pillow and
return JPEG bytes. The caller runs them through the usual upload sanitiser
(EXIF strip, re-encode) before they reach a vision provider.
"""

from __future__ import annotations

import io
import itertools
from dataclasses import dataclass, field
from typing import Any, Final

#: Pages read per upload; every page is one paid vision call.
MAX_PDF_PAGES: Final = 6
#: Largest embedded image that is decoded (guards against decompression bombs).
MAX_PAGE_PIXELS: Final = 40_000_000
JPEG_QUALITY: Final = 90


class PdfUnreadable(ValueError):
    """The PDF could not be parsed."""


@dataclass(frozen=True)
class PdfPageImages:
    """``page_count`` pages in the PDF; ``jpeg_pages`` holds ``(number, JPEG)``."""

    page_count: int
    jpeg_pages: list[tuple[int, bytes]] = field(default_factory=list)


def pdf_page_images(
    data: bytes,
    *,
    max_pages: int = MAX_PDF_PAGES,
    max_pixels: int = MAX_PAGE_PIXELS,
) -> PdfPageImages:
    """Return the scannable pages of *data* as JPEG bytes (1-based numbers)."""

    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(data))
        page_count = len(reader.pages)
    except Exception as exc:
        raise PdfUnreadable("PDF konnte nicht gelesen werden.") from exc

    pages: list[tuple[int, bytes]] = []
    numbered = itertools.islice(reader.pages, max_pages)
    for number, page in enumerate(numbered, start=1):
        try:
            jpeg = _largest_image_as_jpeg(page, max_pixels=max_pixels)
        except Exception:  # corrupt page: skip it, keep the readable ones
            continue
        if jpeg is not None:
            pages.append((number, jpeg))
    return PdfPageImages(page_count=page_count, jpeg_pages=pages)


def _dimension(stream: Any, key: str) -> int:
    try:
        return int(stream.get(key, 0))
    except (TypeError, ValueError):
        return 0


def _largest_image_as_jpeg(page: Any, *, max_pixels: int) -> bytes | None:
    best: Any = None
    best_pixels = 0
    for embedded in page.images:
        reference = embedded.indirect_reference
        stream = reference.get_object() if reference is not None else None
        if stream is None:
            continue
        pixels = _dimension(stream, "/Width") * _dimension(stream, "/Height")
        if 0 < pixels <= max_pixels and pixels > best_pixels:
            best, best_pixels = embedded, pixels
    if best is None:
        return None
    buffer = io.BytesIO()
    best.image.convert("RGB").save(buffer, format="JPEG", quality=JPEG_QUALITY)
    return buffer.getvalue()


__all__ = [
    "MAX_PAGE_PIXELS",
    "MAX_PDF_PAGES",
    "PdfPageImages",
    "PdfUnreadable",
    "pdf_page_images",
]
