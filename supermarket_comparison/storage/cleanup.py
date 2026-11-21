"""One-off database cleanup for bad brands and unverifiable images.

Runs automatically on every start (idempotent) and can be invoked manually::

    python -m supermarket_comparison.cli cleanup

Rules
-----
* Placeholder brands (``thisisnobrand123``, ``none``, ``unbekannt`` …) become
  ``NULL``.
* Open Food Facts images on products **without** an EAN are dropped: they came
  from the old, too-loose text match and may show a completely different
  product.  They are re-resolved on demand (Marktguru offers now carry their
  own leaflet image).
* Loose fruit/vegetables lose any catalogue photo; the UI shows the category
  icon instead.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import UTC, datetime
from typing import Any

from ..normalization.brands import clean_brand
from ..normalization.categories import is_loose_produce

__all__ = ["clean_database", "revalidate_pending"]

logger = logging.getLogger(__name__)


def clean_database(connection: sqlite3.Connection) -> dict[str, int]:
    """Clean brands and suspect image URLs; returns the number of changes."""

    row_factory = connection.row_factory
    connection.row_factory = sqlite3.Row

    brands = 0
    images = 0
    produce_images = 0
    try:
        rows = connection.execute(
            "SELECT id, name, brand, ean, image_url FROM products"
        ).fetchall()

        for row in rows:
            updated: dict[str, Any] = {}

            cleaned = clean_brand(row["brand"])
            if cleaned != row["brand"]:
                updated["brand"] = cleaned

            image_url = row["image_url"]
            if image_url:
                has_ean = bool((row["ean"] or "").strip())
                if not has_ean and "openfoodfacts" in image_url:
                    updated["image_url"] = None
                    images += 1
                elif is_loose_produce(row["name"] or ""):
                    updated["image_url"] = None
                    produce_images += 1

            if not updated:
                continue

            assignments = ", ".join(f"{key} = ?" for key in updated)
            connection.execute(
                f"UPDATE products SET {assignments} WHERE id = ?",
                (*updated.values(), row["id"]),
            )
            if "brand" in updated:
                brands += 1

        if brands or images or produce_images:
            connection.commit()
    finally:
        connection.row_factory = row_factory

    return {
        "brands_cleaned": brands,
        "unverified_images_cleared": images,
        "produce_images_cleared": produce_images,
    }


def revalidate_pending(connection: sqlite3.Connection) -> int:
    """Move implausible legacy ``pending`` rows to ``pending_review``.

    Rows inserted before the validator existed were never checked; without
    this a single batch approval could publish a 999,99 € milk.
    """

    from ..services.price_validator import PriceContext, validate_price

    row_factory = connection.row_factory
    connection.row_factory = sqlite3.Row
    moved = 0
    try:
        rows = connection.execute(
            "SELECT * FROM community_prices WHERE status = 'pending'"
        ).fetchall()
        for row in rows:
            history = [
                float(item["price"])
                for item in connection.execute(
                    """
                    SELECT price FROM community_prices
                     WHERE identity = ? AND store = ?
                       AND status IN ('approved', 'verified')
                    """,
                    (row["identity"], row["store"]),
                ).fetchall()
            ]
            verdict = validate_price(
                PriceContext(
                    name=row["name"],
                    price=float(row["price"]),
                    unit=row["unit"],
                    quantity=row["quantity"],
                    unit_price=row["unit_price"],
                ),
                history=history,
            )
            if not verdict.needs_review:
                continue
            connection.execute(
                """
                UPDATE community_prices
                   SET status = 'pending_review', review_reason = ?,
                       updated_at = ?
                 WHERE id = ? AND status = 'pending'
                """,
                (
                    "; ".join(verdict.reasons),
                    datetime.now(tz=UTC).replace(microsecond=0).isoformat(),
                    row["id"],
                ),
            )
            moved += 1
        if moved:
            connection.commit()
    finally:
        connection.row_factory = row_factory
    return moved
