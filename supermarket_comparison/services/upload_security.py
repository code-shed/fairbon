"""Upload hardening: magic-byte checks and RAM-only image sanitising.

Every uploaded image is re-encoded in memory with Pillow (stripping all EXIF
and GPS metadata, flattening alpha, and re-encoding as JPEG), then discarded
immediately — it never touches the disk.  ``Image.MAX_IMAGE_PIXELS`` guards
against decompression bombs.

Only JPEG, PNG, WebP and PDF are accepted, validated by their real file
header (magic bytes), never by the filename or content-type.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Final

from ..config import get_settings
from .receipt_import import MAX_UPLOAD_BYTES, UnsupportedReceipt

#: Magic-byte signatures -> canonical kind.
_MAGIC: tuple[tuple[bytes, str], ...] = (
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"RIFF", "image/webp"),  # webp: "RIFF" + size + "WEBP"
    (b"%PDF-", "application/pdf"),
)


class UploadTooLarge(RuntimeError):
    """Raised when the upload exceeds the configured byte limit."""


class ImageSanitizeError(RuntimeError):
    """Raised when an image cannot be safely re-encoded."""


@dataclass(frozen=True)
class SanitizedUpload:
    """A validated, re-encoded upload ready for the vision service."""

    #: Canonical media type after magic-byte validation.
    media_type: str
    #: Re-encoded bytes (JPEG for images; unchanged for PDFs).
    data: bytes
    #: Human-readable label for error messages.
    kind: str  # image or pdf


#: Local eBon/Text uploads are tiny; never send them through the vision stack.
PLAIN_TEXT_MAX_BYTES: Final = 512 * 1024


def is_plain_text(data: bytes, content_type: str | None, filename: str | None) -> bool:
    """Whether an upload is a small, decodable plain-text receipt."""

    declared = (content_type or "").split(";", 1)[0].strip().lower()
    suffix = (filename or "").lower().rsplit(".", 1)[-1]
    if declared != "text/plain" or suffix != "txt":
        return False
    if not data or len(data) > PLAIN_TEXT_MAX_BYTES or b"\x00" in data:
        return False
    for encoding in ("utf-8", "latin-1"):
        try:
            data.decode(encoding)
            return True
        except UnicodeDecodeError:
            continue
    return False


def validate_size(data: bytes) -> None:
    """Raise :class:`UploadTooLarge` when *data* exceeds the configured cap."""

    settings = get_settings()
    limit = int(settings.max_upload_bytes or MAX_UPLOAD_BYTES)
    if len(data) > limit:
        raise UploadTooLarge(
            f"Upload zu groß ({len(data)} Bytes > {limit} Bytes). Maximum: 3 MB."
        )


def detect_media_type(data: bytes) -> str:
    """Return the canonical media type from the magic bytes, or raise."""

    for signature, media_type in _MAGIC:
        if data.startswith(signature):
            if media_type == "image/webp" and data[8:12] != b"WEBP":
                continue
            return media_type
    raise UnsupportedReceipt(
        "Nicht unterstützter Dateityp – nur JPEG, PNG, WebP oder PDF."
    )


def sanitize(upload: bytes) -> SanitizedUpload:
    """Validate and sanitise an uploaded file in-memory.

    * enforces the byte cap,
    * checks real magic bytes,
    * re-encodes images with Pillow as JPEG in RAM (EXIF/GPS stripped),
    * leaves PDFs untouched (text layer is parsed separately),

    Returns a :class:`SanitizedUpload`; raises ``UploadTooLarge``,
    ``UnsupportedReceipt`` or ``ImageSanitizeError``.
    """

    validate_size(upload)

    from PIL import Image

    media_type = detect_media_type(upload)
    if media_type == "application/pdf":
        return SanitizedUpload(media_type=media_type, data=upload, kind="pdf")

    try:
        image = Image.open(io.BytesIO(upload))
        # Dimension guard BEFORE decoding pixels (decompression bombs).
        if image.width * image.height > (Image.MAX_IMAGE_PIXELS or 89_478_485):
            raise ImageSanitizeError("Bild hat zu große Abmessungen.")
        image.load()
        if image.mode not in ("RGB", "L"):
            if image.mode in ("RGBA", "LA", "P"):
                background = image.convert("RGBA")
                flat = Image.new("RGBA", background.size, (255, 255, 255, 255))
                flat.alpha_composite(background)
                image = flat.convert("RGB")
            else:
                image = image.convert("RGB")
        buffer = io.BytesIO()
        settings = get_settings()
        image.save(
            buffer,
            format="JPEG",
            quality=int(settings.vision_jpeg_quality or 82),
            optimize=True,
        )
    except ImageSanitizeError:
        raise
    except Exception as exc:  # pragma: no cover - defensive
        raise ImageSanitizeError(
            f"Bild konnte nicht verarbeitet werden: {exc}"
        ) from exc
    finally:
        try:
            if "image" in locals():
                image.close()
        except Exception:  # pragma: no cover
            pass

    return SanitizedUpload(
        media_type="image/jpeg", data=buffer.getvalue(), kind="image"
    )


__all__ = [
    "PLAIN_TEXT_MAX_BYTES",
    "ImageSanitizeError",
    "SanitizedUpload",
    "UploadTooLarge",
    "detect_media_type",
    "is_plain_text",
    "sanitize",
    "validate_size",
]
