"""Persistence layer: products, price points, price history, search trends.

All methods are synchronous; async callers use the ``async_*`` wrappers which
run the blocking SQLite work in a worker thread.
"""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from ..config import get_settings
from ..models import NormalizedProduct
from ..normalization.matcher import normalize_ean, normalize_title
from .database import Database


def _now() -> datetime:
    return datetime.now(tz=UTC)


def _iso(moment: datetime) -> str:
    return moment.replace(microsecond=0).isoformat()


def product_key(product: NormalizedProduct) -> str:
    """Deterministic identity: EAN when known, else a text hash.

    The hash deliberately ignores price/validity so repeated observations of
    the same product line map to one row.
    """

    ean = normalize_ean(product.ean)
    if ean:
        return f"ean:{ean}"
    fingerprint = "|".join(
        [
            normalize_title(product.name),
            normalize_title(product.brand or ""),
            f"{round(float(product.quantity), 3):g}{product.unit}",
        ]
    )
    digest = hashlib.sha1(fingerprint.encode("utf-8")).hexdigest()
    return f"txt:{digest[:20]}"


@dataclass(frozen=True)
class PricePoint:
    store: str
    offer_type: str
    source: str
    price: float
    unit_price: float | None
    unit: str | None
    quantity: float | None
    valid_from: str | None
    valid_to: str | None
    observed_at: str


class Repository:
    """High-level database operations used by the API and the aggregator."""

    def __init__(self, database: Database | None = None) -> None:
        settings = get_settings()
        self.db = database or Database(settings.database_path)

    # -- lifecycle --------------------------------------------------------
    def close(self) -> None:
        self.db.close()

    @property
    def community(self) -> Any:
        """Lazily created :class:`CommunityStore` for crowdsourced prices."""

        store = getattr(self, "_community", None)
        if store is None:
            from .community import CommunityStore

            store = CommunityStore(self)
            self._community = store
        return store

    # -- products + prices ------------------------------------------------
    def _upsert_product(self, product: NormalizedProduct) -> int:
        now = _iso(_now())
        key = product_key(product)
        row = self.db.query_one("SELECT id FROM products WHERE key = ?", (key,))
        if row is not None:
            self.db.execute(
                """
                UPDATE products
                   SET name = ?, brand = ?, category = ?, unit = ?, quantity = ?,
                       ean = COALESCE(?, ean),
                       image_url = COALESCE(?, image_url), updated_at = ?
                 WHERE id = ?
                """,
                (
                    product.name,
                    product.brand,
                    product.category,
                    product.unit,
                    float(product.quantity),
                    normalize_ean(product.ean),
                    product.image_url,
                    now,
                    row["id"],
                ),
            )
            return int(row["id"])

        cursor = self.db.execute(
            """
            INSERT INTO products
                (key, ean, name, brand, category, unit, quantity, image_url,
                 created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                key,
                normalize_ean(product.ean),
                product.name,
                product.brand,
                product.category,
                product.unit,
                float(product.quantity),
                product.image_url,
                now,
                now,
            ),
        )
        return int(cursor.lastrowid)

    def _record_price_point(
        self, product_id: int, product: NormalizedProduct, moment: datetime
    ) -> bool:
        """Insert the observation and, on a real change, a history row."""

        observed_at = _iso(moment)
        observed_day = moment.date().isoformat()
        offer_type = product.offer_type
        store = product.store

        before = self.db.query_one(
            """
            SELECT price, unit_price FROM price_history
             WHERE product_id = ? AND store = ? AND offer_type = ?
             ORDER BY changed_at DESC, id DESC LIMIT 1
            """,
            (product_id, store, offer_type),
        )

        self.db.execute(
            """
            INSERT OR IGNORE INTO price_points
                (product_id, store, offer_type, source, offer_id, price, old_price,
                 unit_price, unit, quantity, valid_from, valid_to,
                 observed_at, observed_day)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                product_id,
                store,
                offer_type,
                product.source or "unknown",
                product.id,
                float(product.price),
                product.old_price,
                product.unit_price,
                product.unit,
                float(product.quantity),
                product.valid_from or "",
                product.valid_to or "",
                observed_at,
                observed_day,
            ),
        )

        previous_price = float(before["price"]) if before is not None else None
        if previous_price is None or abs(previous_price - float(product.price)) > 1e-9:
            self.db.execute(
                """
                INSERT INTO price_history
                    (product_id, store, offer_type, source, price,
                     unit_price, changed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    product_id,
                    store,
                    offer_type,
                    product.source or "unknown",
                    float(product.price),
                    product.unit_price,
                    observed_at,
                ),
            )
            return True
        return False

    def record_offers(self, offers: Iterable[NormalizedProduct]) -> dict[str, int]:
        """Persist offers and return ``{"products": n, "changes": n}``."""

        moment = _now()
        products = 0
        changes = 0
        for product in offers:
            product_id = self._upsert_product(product)
            products += 1
            if self._record_price_point(product_id, product, moment):
                changes += 1
        return {"products": products, "changes": changes}

    # -- search statistics ------------------------------------------------
    def record_search(
        self,
        *,
        query: str,
        postal_code: str | None,
        result_count: int,
        stores: Sequence[str] | None = None,
    ) -> None:
        """Store an anonymised search event and bump the daily aggregate.

        Only the normalised query term, the postal code, the result count and a
        timestamp are kept — no IP address, session id or user agent.
        """

        term = normalize_title(query)
        if not term:
            return
        moment = _now()
        created_at = _iso(moment)
        day = moment.date().isoformat()
        store_slugs = ",".join(sorted({str(store) for store in (stores or [])}))

        self.db.execute(
            """
            INSERT INTO search_events
                (query, postal_code, result_count, stores, created_at, created_day)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (term, postal_code, int(result_count), store_slugs, created_at, day),
        )
        self.db.execute(
            """
            INSERT INTO search_trends (day, query, postal_code, searches, results)
            VALUES (?, ?, ?, 1, ?)
            ON CONFLICT(day, query, postal_code) DO UPDATE SET
                searches = searches + 1,
                results  = results + excluded.results
            """,
            (day, term, postal_code or "", int(result_count)),
        )

    def top_queries(self, *, days: int = 30, limit: int = 20) -> list[dict[str, Any]]:
        since = (date.today() - _days(days)).isoformat()
        rows = self.db.query(
            """
            SELECT query,
                   SUM(searches) AS searches,
                   SUM(results)  AS results,
                   MAX(postal_code) AS sample_postal_code,
                   COUNT(DISTINCT postal_code) AS regions
              FROM search_trends
             WHERE day >= ? AND postal_code <> ''
             GROUP BY query
             ORDER BY searches DESC, results DESC
             LIMIT ?
            """,
            (since, int(limit)),
        )
        return [dict(row) for row in rows]

    def regional_queries(
        self, *, postal_code: str, days: int = 30, limit: int = 20
    ) -> list[dict[str, Any]]:
        since = (date.today() - _days(days)).isoformat()
        rows = self.db.query(
            """
            SELECT query, SUM(searches) AS searches, SUM(results) AS results
              FROM search_trends
             WHERE day >= ? AND postal_code = ?
             GROUP BY query
             ORDER BY searches DESC
             LIMIT ?
            """,
            (since, postal_code, int(limit)),
        )
        return [dict(row) for row in rows]

    def stats_summary(self) -> dict[str, Any]:
        products = self.db.query_one("SELECT COUNT(*) AS n FROM products")
        points = self.db.query_one("SELECT COUNT(*) AS n FROM price_points")
        history = self.db.query_one("SELECT COUNT(*) AS n FROM price_history")
        events = self.db.query_one("SELECT COUNT(*) AS n FROM search_events")
        return {
            "products": int(products["n"]) if products else 0,
            "price_points": int(points["n"]) if points else 0,
            "price_changes": int(history["n"]) if history else 0,
            "search_events": int(events["n"]) if events else 0,
        }

    # -- price history ----------------------------------------------------
    def price_history(
        self,
        *,
        product_id: int | None = None,
        ean: str | None = None,
        name: str | None = None,
        brand: str | None = None,
        quantity: float | None = None,
        unit: str | None = None,
        store: str | None = None,
        days: int = 90,
    ) -> list[dict[str, Any]]:
        """Return the recorded price changes for one product (optionally one store).

        Leaflet offers have no EAN, so *name* matches on the normalised product
        name (umlaut folded) instead of requiring an exact string.
        """

        clauses: list[str] = []
        params: list[Any] = []

        if product_id is not None:
            clauses.append("h.product_id = ?")
            params.append(int(product_id))
        if ean:
            clauses.append("p.ean = ?")
            params.append(normalize_ean(ean))

        if not params and not name:
            raise ValueError("one of product_id, ean or name is required")

        if store:
            clauses.append("h.store = ?")
            params.append(store.strip().lower())

        since = (_now().date() - _days(days)).isoformat()
        clauses.append("substr(h.changed_at, 1, 10) >= ?")
        params.append(since)

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self.db.query(
            f"""
            SELECT h.product_id, h.changed_at, h.store, h.offer_type, h.source,
                   h.price, h.unit_price, p.name, p.brand, p.ean, p.unit,
                   p.quantity
              FROM price_history h
              JOIN products p ON p.id = h.product_id
             {where}
             ORDER BY h.changed_at ASC, h.id ASC
            """,
            tuple(params),
        )

        wanted = normalize_title(name) if name else None
        wanted_brand = normalize_title(brand) if brand else None
        wanted_quantity = round(float(quantity), 3) if quantity is not None else None
        wanted_unit = (unit or "").strip().lower() or None

        def _matches(row: Any) -> bool:
            if wanted is not None and normalize_title(row["name"]) != wanted:
                return False
            if wanted_brand is not None and normalize_title(
                row["brand"] or ""
            ) != wanted_brand:
                return False
            if wanted_quantity is not None and wanted_unit is not None:
                try:
                    row_qty = round(float(row["quantity"]), 3)
                except (TypeError, ValueError):
                    return False
                if row_qty != wanted_quantity or str(
                    row["unit"] or ""
                ).strip().lower() != wanted_unit:
                    return False
            return True

        return [dict(row) for row in rows if _matches(row)]

    # -- user receipts (V1.0, guest mode via owner_token) -----------------
    def insert_user_receipt(
        self,
        *,
        owner_token: str,
        store: str,
        postal_code: str | None,
        country_code: str,
        currency: str,
        receipt_date: str,
        total_cents: int,
        shared_to_community: bool,
        items: Iterable[dict[str, Any]],
        is_business: bool = False,
    ) -> int:
        """Insert a personal receipt and return its id.

        ``owner_token`` is the only access key (guest mode). Items are stored
        as cents (integers) to avoid float drift. ``is_business`` marks a
        geschäftliche Ausgabe (self-employed tax export).
        """

        from datetime import UTC, datetime

        now = datetime.now(tz=UTC).isoformat()
        cursor = self.db.execute(
            """
            INSERT INTO user_receipts
                (owner_token, store, postal_code, country_code, currency,
                 receipt_date, total_cents, shared_to_community, is_business,
                 created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                owner_token,
                store,
                postal_code,
                country_code,
                currency,
                receipt_date,
                int(total_cents),
                1 if shared_to_community else 0,
                1 if is_business else 0,
                now,
            ),
        )
        receipt_id = int(cursor.lastrowid)

        self.db.executemany(
            """
            INSERT INTO user_receipt_items
                (receipt_id, raw_text, normalized_name, brand, category,
                 quantity, unit, unit_price_cents, price_cents, discount_cents,
                 deposit_cents, vat_rate, is_private)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    receipt_id,
                    item.get("raw_text", ""),
                    item.get("normalized_name"),
                    item.get("brand"),
                    item.get("category"),
                    item.get("quantity"),
                    item.get("unit"),
                    item.get("unit_price_cents"),
                    item.get("price_cents"),
                    item.get("discount_cents", 0),
                    item.get("deposit_cents", 0),
                    item.get("vat_rate"),
                    1 if item.get("is_private") else 0,
                )
                for item in items
            ],
        )
        return receipt_id

    def user_receipts_for(self, owner_token: str) -> list[dict[str, Any]]:
        rows = self.db.query(
            """
            SELECT * FROM user_receipts WHERE owner_token = ?
             ORDER BY receipt_date DESC, id DESC
            """,
            (owner_token,),
        )
        return [dict(row) for row in rows]

    def user_receipt(
        self, *, receipt_id: int, owner_token: str
    ) -> dict[str, Any] | None:
        row = self.db.query_one(
            "SELECT * FROM user_receipts WHERE id = ? AND owner_token = ?",
            (int(receipt_id), owner_token),
        )
        return dict(row) if row else None

    def delete_user_receipt(self, *, receipt_id: int, owner_token: str) -> bool:
        cursor = self.db.execute(
            "DELETE FROM user_receipts WHERE id = ? AND owner_token = ?",
            (int(receipt_id), owner_token),
        )
        return bool(cursor.rowcount)

    def set_receipt_item_private(
        self, *, item_id: int, receipt_id: int, owner_token: str, is_private: bool
    ) -> bool:
        cursor = self.db.execute(
            """
            UPDATE user_receipt_items
               SET is_private = ?
             WHERE id = ? AND receipt_id = ?
               AND receipt_id IN (
                   SELECT id FROM user_receipts WHERE owner_token = ?
               )
            """,
            (1 if is_private else 0, int(item_id), int(receipt_id), owner_token),
        )
        return bool(cursor.rowcount)

    def user_receipt_items_for(self, receipt_id: int) -> list[dict[str, Any]]:
        rows = self.db.query(
            """
            SELECT * FROM user_receipt_items
             WHERE receipt_id = ? ORDER BY id ASC
            """,
            (int(receipt_id),),
        )
        return [dict(row) for row in rows]

    # -- receipt aliases (self-learning) -----------------------------------
    def resolve_alias(
        self, *, store: str, raw_text_norm: str
    ) -> dict[str, Any] | None:
        row = self.db.query_one(
            """
            SELECT * FROM receipt_aliases
             WHERE store = ? AND raw_text_norm = ?
            """,
            (store, raw_text_norm),
        )
        return dict(row) if row else None

    def upsert_alias(
        self,
        *,
        store: str,
        raw_text_norm: str,
        normalized_name: str,
        brand: str | None,
        category: str | None,
        quantity: float | None,
        unit: str | None,
    ) -> None:
        from datetime import UTC, datetime

        now = datetime.now(tz=UTC).isoformat()
        self.db.execute(
            """
            INSERT INTO receipt_aliases
                (store, raw_text_norm, normalized_name, brand, category,
                 quantity, unit, hit_count, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
            ON CONFLICT(store, raw_text_norm) DO UPDATE SET
                normalized_name = excluded.normalized_name,
                brand           = excluded.brand,
                category        = excluded.category,
                quantity        = excluded.quantity,
                unit            = excluded.unit,
                hit_count       = hit_count + 1,
                updated_at      = excluded.updated_at
            """,
            (
                store,
                raw_text_norm,
                normalized_name,
                brand,
                category,
                quantity,
                unit,
                now,
                now,
            ),
        )

    async def ainsert_user_receipt(self, **kwargs: Any) -> int:
        return await asyncio.to_thread(self.insert_user_receipt, **kwargs)

    async def auser_receipts_for(self, owner_token: str) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self.user_receipts_for, owner_token)

    async def auser_receipt_items_for(self, receipt_id: int) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self.user_receipt_items_for, receipt_id)

    async def auser_receipt(self, **kwargs: Any) -> dict[str, Any] | None:
        return await asyncio.to_thread(self.user_receipt, **kwargs)

    async def adelete_user_receipt(self, **kwargs: Any) -> bool:
        return await asyncio.to_thread(self.delete_user_receipt, **kwargs)

    async def aset_receipt_item_private(self, **kwargs: Any) -> bool:
        return await asyncio.to_thread(self.set_receipt_item_private, **kwargs)

    async def aresolve_alias(self, **kwargs: Any) -> dict[str, Any] | None:
        return await asyncio.to_thread(self.resolve_alias, **kwargs)

    async def aupsert_alias(self, **kwargs: Any) -> None:
        await asyncio.to_thread(self.upsert_alias, **kwargs)

    # -- product images ---------------------------------------------------
    def set_product_image(self, *, name: str, ean: str | None, image_url: str) -> int:
        """Attach an image URL to every product row matching *name* / *ean*."""

        if not image_url:
            return 0
        if ean:
            cursor = self.db.execute(
                "UPDATE products SET image_url = ?, updated_at = ? WHERE ean = ?",
                (image_url, _iso(_now()), normalize_ean(ean)),
            )
            if cursor.rowcount:
                return int(cursor.rowcount)
        cursor = self.db.execute(
            "UPDATE products SET image_url = ?, updated_at = ? WHERE name = ?",
            (image_url, _iso(_now()), name),
        )
        return int(cursor.rowcount)

    def image_for(
        self, *, name: str | None = None, ean: str | None = None
    ) -> str | None:
        """Return a stored image URL for a product (EAN first, then name)."""

        if ean:
            row = self.db.query_one(
                "SELECT image_url FROM products "
                "WHERE ean = ? AND image_url IS NOT NULL LIMIT 1",
                (normalize_ean(ean),),
            )
            if row and row["image_url"]:
                return str(row["image_url"])
        if name:
            row = self.db.query_one(
                "SELECT image_url FROM products "
                "WHERE name = ? AND image_url IS NOT NULL LIMIT 1",
                (name,),
            )
            if row and row["image_url"]:
                return str(row["image_url"])
        return None

    async def aset_product_image(self, **kwargs: Any) -> int:
        return await asyncio.to_thread(self.set_product_image, **kwargs)

    async def aimage_for(self, **kwargs: Any) -> str | None:
        return await asyncio.to_thread(self.image_for, **kwargs)

    # -- harvester runs (removed in V1.0) --------------------------------
    def last_harvest_run(self) -> dict[str, Any] | None:
        row = self.db.query_one("SELECT * FROM harvest_runs ORDER BY id DESC LIMIT 1")
        return dict(row) if row else None

    async def alast_harvest_run(self) -> dict[str, Any] | None:
        return await asyncio.to_thread(self.last_harvest_run)

    # -- async wrappers ---------------------------------------------------
    async def arecord_offers(
        self, offers: Iterable[NormalizedProduct]
    ) -> dict[str, int]:
        return await asyncio.to_thread(self.record_offers, list(offers))

    async def arecord_search(
        self,
        *,
        query: str,
        postal_code: str | None,
        result_count: int,
        stores: Sequence[str] | None = None,
    ) -> None:
        await asyncio.to_thread(
            self.record_search,
            query=query,
            postal_code=postal_code,
            result_count=result_count,
            stores=stores,
        )

    async def atop_queries(
        self, *, days: int = 30, limit: int = 20
    ) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self.top_queries, days=days, limit=limit)

    async def aregional_queries(
        self, *, postal_code: str, days: int = 30, limit: int = 20
    ) -> list[dict[str, Any]]:
        return await asyncio.to_thread(
            self.regional_queries, postal_code=postal_code, days=days, limit=limit
        )

    async def astats_summary(self) -> dict[str, Any]:
        return await asyncio.to_thread(self.stats_summary)

    async def aprice_history(self, **kwargs: Any) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self.price_history, **kwargs)


def _days(count: int) -> timedelta:
    return timedelta(days=max(1, int(count)))


__all__ = ["PricePoint", "Repository", "product_key"]
