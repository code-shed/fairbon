"""Community price storage, aggregation and trust handling.

Everything here is anonymous: contributions are linked to a randomly
generated client-side id (`scout_id`) only. No IP addresses, device
fingerprints or account data are stored.

Trust model
-----------
* Every submission runs through :func:`validate_price`; plausible entries are
  ``pending``, suspicious ones ``pending_review`` with a stored reason.
* **Only ``approved`` and ``verified`` rows are visible** (median, search,
  basket, coverage). A single plausible report stays hidden until an admin
  approves it or three distinct scouts confirm it (strict mode).
* ``rejected`` rows stay hidden forever and are never revived by confirms.
"""

from __future__ import annotations

import statistics
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final

from ..models import NormalizedProduct
from ..normalization.matcher import normalize_ean, normalize_title
from ..services.price_validator import PriceContext, validate_price
from .database import Database
from .repository import Repository

#: Distinct confirmations required to mark a price as verified.
VERIFY_THRESHOLD = 3

#: Statuses that may appear in search, basket, median and coverage.
VISIBLE_STATUSES: frozenset[str] = frozenset({"approved", "verified"})

#: Canonical units and the aliases accepted from clients/receipts.
_UNIT_ALIASES: Final[dict[str, str]] = {
    "kg": "kg",
    "g": "kg",
    "gramm": "kg",
    "l": "l",
    "ml": "l",
    "milliliter": "l",
    "stueck": "stueck",
    "stk": "stueck",
    "st": "stueck",
    "stück": "stueck",
}
SUPPORTED_UNITS: Final[frozenset[str]] = frozenset(_UNIT_ALIASES)


def visible_status_sql() -> str:
    """SQL fragment built from :data:`VISIBLE_STATUSES` (single source)."""

    quoted = ", ".join(f"'{status}'" for status in sorted(VISIBLE_STATUSES))
    return f"({quoted})"


#: Coverage labels (postal code level).
COVERAGE_LEVELS: tuple[tuple[int, str], ...] = (
    (50, "stark"),
    (10, "aktiv"),
    (1, "im Aufbau"),
)


def _iso_now() -> str:
    return datetime.now(tz=UTC).replace(microsecond=0).isoformat()


def normalise_unit(
    unit: str | None, quantity: float | None
) -> tuple[str, float | None]:
    """Map ``g``/``ml`` to ``kg``/``l`` and reject unknown units."""

    key = (unit or "stueck").strip().lower()
    if key not in _UNIT_ALIASES:
        raise ValueError(f"Unsupported unit: {unit!r}")
    canonical = _UNIT_ALIASES[key]
    if quantity is not None and key in {"g", "ml"}:
        return canonical, quantity / 1000.0
    return canonical, quantity


def identity_of(
    *, ean: str | None, name: str, unit: str | None, quantity: float | None
) -> str:
    """Stable key for aggregating community submissions."""

    normalized_ean = normalize_ean(ean)
    if normalized_ean:
        return f"ean:{normalized_ean}"
    base = normalize_title(name)
    if unit:
        normalized_unit = str(unit).strip().lower()
        amount = f"{round(float(quantity or 1.0), 3):g}"
        return f"txt:{base}|{amount}{normalized_unit}"
    return f"txt:{base}"


@dataclass(frozen=True)
class CommunityPriceInput:
    """One user-submitted shelf price."""

    name: str
    store: str
    price: float
    postal_code: str
    ean: str | None = None
    unit: str | None = None
    quantity: float | None = None
    unit_price: float | None = None
    scout_id: str | None = None
    source: str = "manual"
    receipt_id: str | None = None


class CommunityStore:
    """Repository mix-in for community prices (kept separate for clarity)."""

    def __init__(self, repository: Repository) -> None:
        self.repository = repository
        self.db: Database = repository.db

    # -- writes -----------------------------------------------------------
    def add_price(
        self,
        entry: CommunityPriceInput,
        *,
        history: Sequence[float] | None = None,
        auto_verify: bool = False,
    ) -> dict[str, Any]:
        unit, quantity = normalise_unit(entry.unit, entry.quantity)
        identity = identity_of(
            ean=entry.ean,
            name=entry.name,
            unit=unit,
            quantity=quantity,
        )
        price_id = uuid.uuid4().hex
        now = _iso_now()
        # The server derives the unit price; a client-supplied value is ignored.
        unit_price = None
        if quantity and quantity > 0 and unit in {"kg", "l"}:
            unit_price = round(float(entry.price) / quantity, 2)

        if history is None:
            history = self.confirmed_prices(identity=identity, store=entry.store)
        verdict = validate_price(
            PriceContext(
                name=entry.name,
                price=float(entry.price),
                unit=unit,
                quantity=quantity,
                unit_price=unit_price,
                brand=None,
            ),
            history=history,
        )
        # Own-receipt prices (auto_verify) skip the scout confirmation
        # round-trip: the uploader reviewed the items in the save dialog.
        # Flagged outliers still quarantine for the review queue.
        insert_status = "verified" if (
            auto_verify and verdict.status == "pending"
        ) else verdict.status
        self.db.execute(
            """
            INSERT INTO community_prices
                (id, identity, ean, name, store, price, unit, quantity,
                 unit_price, postal_code, scout_id, source, receipt_id,
                 status, confirmations, review_reason, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
            """,
            (
                price_id,
                identity,
                normalize_ean(entry.ean),
                entry.name.strip(),
                entry.store.strip().lower(),
                float(entry.price),
                unit,
                quantity,
                unit_price,
                entry.postal_code.strip(),
                entry.scout_id,
                entry.source,
                entry.receipt_id,
                insert_status,
                "; ".join(verdict.reasons) or None,
                now,
                now,
            ),
        )
        if entry.scout_id:
            self.db.execute(
                """
                INSERT OR IGNORE INTO community_confirmations
                    (price_id, scout_id, created_at)
                VALUES (?, ?, ?)
                """,
                (price_id, entry.scout_id, now),
            )
        return self.get_price(price_id) or {}

    def confirm(self, price_id: str, scout_id: str) -> dict[str, Any] | None:
        """Add one distinct confirmation; auto-verify at the threshold.

        Only ``pending`` prices can be promoted by scouts.  Flagged
        (``pending_review``) and already approved/rejected rows are
        admin-only and stay untouched.
        """

        row = self.get_price(price_id)
        if row is None or not scout_id:
            return row
        if row["status"] != "pending":
            return row

        cursor = self.db.execute(
            """
            INSERT OR IGNORE INTO community_confirmations
                (price_id, scout_id, created_at)
            VALUES (?, ?, ?)
            """,
            (price_id, scout_id, _iso_now()),
        )
        if cursor.rowcount == 0:
            return row

        # Atomic increment guarded on the expected status.
        self.db.execute(
            """
            UPDATE community_prices
               SET confirmations = confirmations + 1, updated_at = ?
             WHERE id = ? AND status = 'pending'
            """,
            (_iso_now(), price_id),
        )
        updated = self.get_price(price_id)
        if updated and int(updated["confirmations"]) >= VERIFY_THRESHOLD:
            self.db.execute(
                """
                UPDATE community_prices SET status = 'verified'
                 WHERE id = ? AND status = 'pending'
                """,
                (price_id,),
            )
            updated = self.get_price(price_id)
        return updated

    def confirmed_prices(self, *, identity: str, store: str) -> list[float]:
        """Confirmed prices for one product/store (input for the validator)."""

        rows = self.db.query(
            """
            SELECT price FROM community_prices
             WHERE identity = ? AND store = ?
               AND status IN ('approved', 'verified')
            """,
            (identity, store.strip().lower()),
        )
        return [float(row["price"]) for row in rows]

    # -- moderation -------------------------------------------------------
    def approve(
        self, price_id: str, *, reviewer: str = "admin"
    ) -> dict[str, Any] | None:
        """Publish a price (admin confirmation)."""

        cursor = self.db.execute(
            """
            UPDATE community_prices
               SET status = 'approved', reviewed_at = ?, reviewed_by = ?,
                   updated_at = ?
             WHERE id = ? AND status IN ('pending', 'pending_review')
            """,
            (_iso_now(), reviewer, _iso_now(), price_id),
        )
        if cursor.rowcount == 0:
            return None
        return self.get_price(price_id)

    def reject(
        self,
        price_id: str,
        *,
        reviewer: str = "admin",
        reason: str = "Vom Admin abgelehnt.",
    ) -> dict[str, Any] | None:
        """Hide a price permanently."""

        row = self.get_price(price_id)
        if row is None:
            return None
        self.db.execute(
            """
            UPDATE community_prices
               SET status = 'rejected',
                   review_reason = CASE
                       WHEN review_reason IS NULL OR review_reason = ''
                           THEN ?
                       ELSE review_reason || ' | Admin: ' || ?
                   END,
                   reviewed_at = ?, reviewed_by = ?, updated_at = ?
             WHERE id = ?
            """,
            (reason, reason, _iso_now(), reviewer, _iso_now(), price_id),
        )
        return self.get_price(price_id)

    def approve_all_pending(self, *, reviewer: str = "admin") -> int:
        """Approve every *plausible* pending price (re-validated, atomic).

        Legacy or hand-crafted rows that would fail the validator are moved to
        ``pending_review`` instead of being published.
        """

        rows = self.db.query(
            """
            SELECT * FROM community_prices WHERE status = 'pending'
            """
        )
        passing: list[str] = []
        for row in rows:
            history = self.confirmed_prices(
                identity=row["identity"], store=row["store"]
            )
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
            if verdict.needs_review:
                self.db.execute(
                    """
                    UPDATE community_prices
                       SET status = 'pending_review', review_reason = ?,
                           updated_at = ?
                     WHERE id = ? AND status = 'pending'
                    """,
                    ("; ".join(verdict.reasons), _iso_now(), row["id"]),
                )
            else:
                passing.append(str(row["id"]))

        if not passing:
            return 0

        placeholders = ", ".join("?" for _ in passing)
        now = _iso_now()
        cursor = self.db.execute(
            f"""
            UPDATE community_prices
               SET status = 'approved', reviewed_at = ?, reviewed_by = ?,
                   updated_at = ?
             WHERE status = 'pending' AND id IN ({placeholders})
            """,
            (now, reviewer, now, *passing),
        )
        return int(cursor.rowcount)

    def review_queue(
        self, *, status: str = "pending_review", limit: int = 100
    ) -> list[dict[str, Any]]:
        """Moderation entries for one bucket (or both with ``"all"``)."""

        limit = int(limit)
        if status == "all":
            rows = self.db.query(
                """
                SELECT * FROM community_prices
                 WHERE status IN ('pending', 'pending_review')
                 ORDER BY status DESC, created_at ASC
                 LIMIT ?
                """,
                (limit,),
            )
        else:
            rows = self.db.query(
                """
                SELECT * FROM community_prices
                 WHERE status = ?
                 ORDER BY created_at ASC
                 LIMIT ?
                """,
                (status, limit),
            )
        return [dict(row) for row in rows]

    def review_counts(self) -> dict[str, int]:
        rows = self.db.query(
            """
            SELECT status, COUNT(*) AS n FROM community_prices
             WHERE status IN ('pending', 'pending_review')
             GROUP BY status
            """
        )
        counts = {"pending": 0, "pending_review": 0}
        for row in rows:
            counts[str(row["status"])] = int(row["n"])
        return counts

    # -- reads ------------------------------------------------------------
    def get_price(self, price_id: str) -> dict[str, Any] | None:
        row = self.db.query_one(
            "SELECT * FROM community_prices WHERE id = ?", (price_id,)
        )
        return dict(row) if row else None

    def list_prices(
        self,
        *,
        postal_code: str | None = None,
        ean: str | None = None,
        name: str | None = None,
        store: str | None = None,
        status: str | None = None,
        visible_only: bool = True,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if postal_code:
            clauses.append("postal_code = ?")
            params.append(postal_code.strip())
        if ean:
            clauses.append("identity = ?")
            params.append(identity_of(ean=ean, name="", unit=None, quantity=None))
        if name:
            clauses.append("name LIKE ?")
            params.append(f"%{name.strip()}%")
        if store:
            clauses.append("store = ?")
            params.append(store.strip().lower())
        if status:
            clauses.append("status = ?")
            params.append(status)
        elif visible_only:
            clauses.append(f"status IN {visible_status_sql()}")

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self.db.query(
            f"""
            SELECT * FROM community_prices
            {where}
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (*tuple(params), int(limit)),
        )
        return [dict(row) for row in rows]

    def aggregate(
        self, *, identity: str, store: str, postal_code: str
    ) -> dict[str, Any] | None:
        """Median price for one product in one store and postal code."""

        rows = self.db.query(
            """
            SELECT price, unit, quantity, unit_price, status, created_at, name
              FROM community_prices
             WHERE identity = ? AND store = ? AND postal_code = ?
               AND status IN ('approved', 'verified')
            """,
            (identity, store.strip().lower(), postal_code.strip()),
        )
        if not rows:
            return None

        prices = sorted(float(row["price"]) for row in rows)
        verified = [row for row in rows if row["status"] == "verified"]
        unit_prices = [
            float(row["unit_price"]) for row in rows if row["unit_price"] is not None
        ]
        latest = max((row["created_at"] for row in rows), default=None)
        return {
            "identity": identity,
            "name": rows[0]["name"],
            "store": store.strip().lower(),
            "postal_code": postal_code.strip(),
            "median_price": round(statistics.median(prices), 2),
            "min_price": round(min(prices), 2),
            "max_price": round(max(prices), 2),
            "median_unit_price": (
                round(statistics.median(unit_prices), 2) if unit_prices else None
            ),
            "unit": rows[0]["unit"],
            "quantity": rows[0]["quantity"],
            "observations": len(rows),
            "verified": len(verified),
            "confidence": "verified" if len(verified) >= 1 else "unverified",
            "last_updated": latest,
        }

    @staticmethod
    def _plz_tier(wanted: str, candidate: str) -> int:
        """Distance proxy for German-style postal codes.

        0 = exact, 1 = four leading digits, 2 = three, 99 = far away. German
        PLZs are zoned geographically, so shared leading digits approximate a
        local radius without maintaining a coordinate table.
        """

        wanted = (wanted or "").strip()
        candidate = (candidate or "").strip()
        if not wanted:
            return 0
        if candidate == wanted:
            return 0
        shortest = min(len(wanted), len(candidate))
        for length in range(shortest - 1, 1, -1):
            if wanted[:length] == candidate[:length]:
                return shortest - length
        return 99

    def aggregated_for_query(
        self,
        *,
        query: str,
        postal_code: str | None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Aggregated community prices near *postal_code* whose name matches."""

        term = normalize_title(query)
        if not term:
            return []

        # SQL only pre-filters on individual words: names are stored with
        # punctuation ("Schoko-Bons", "H-Milch 3,5%") while the query is
        # normalised ("schoko bons").  The exact check happens below.
        words = [word for word in term.split() if word]
        clause = " OR ".join("LOWER(name) LIKE ?" for _ in words)
        params: list[Any] = [f"%{word}%" for word in words]

        rows = self.db.query(
            f"""
            SELECT identity, store, postal_code, name
              FROM community_prices
             WHERE ({clause}) AND status IN ('approved', 'verified')
             GROUP BY identity, store, postal_code
             LIMIT ?
            """,
            (*tuple(params), max(200, int(limit) * 20)),
        )

        wanted = (postal_code or "").strip()
        aggregated: list[dict[str, Any]] = []
        for row in rows:
            if term not in normalize_title(row["name"]):
                continue
            entry = self.aggregate(
                identity=row["identity"],
                store=row["store"],
                postal_code=row["postal_code"],
            )
            if entry is not None:
                tier = self._plz_tier(wanted, row["postal_code"])
                if tier <= 2:
                    entry["_plz_tier"] = tier
                    aggregated.append(entry)
        # Exact matches first, then nearby PLZs, then by price as before.
        aggregated.sort(key=lambda item: (item["_plz_tier"], item["median_price"]))
        for entry in aggregated:
            entry.pop("_plz_tier", None)
        return aggregated[: int(limit)]

    def coverage(self, postal_code: str) -> dict[str, Any]:
        wanted = (postal_code or "").strip()
        # Same nearby-PLZ rule as aggregated_for_query so the coverage text
        # agrees with what the price search actually finds.
        rows = self.db.query(
            """
            SELECT identity, store, postal_code, scout_id, status, created_at
              FROM community_prices
             WHERE status IN ('approved', 'verified')
            """
        )
        near = [
            row
            for row in rows
            if self._plz_tier(wanted, row["postal_code"]) <= 2
        ]
        observations = len(near)
        verified = sum(1 for row in near if row["status"] == "verified")
        level = "keine Daten"
        for threshold, label in COVERAGE_LEVELS:
            if observations >= threshold:
                level = label
                break
        return {
            "postal_code": wanted,
            "observations": observations,
            "products": len({row["identity"] for row in near}),
            "stores": len({row["store"] for row in near}),
            "scouts": len({row["scout_id"] for row in near if row["scout_id"]}),
            "verified": verified,
            "level": level,
            "last_updated": max(
                (row["created_at"] or "" for row in near), default=None
            ),
        }

    def scout_stats(self, scout_id: str) -> dict[str, Any]:
        rows = self.db.query(
            """
            SELECT COUNT(*) AS contributions,
                   COUNT(DISTINCT identity) AS products,
                   COUNT(DISTINCT postal_code) AS regions,
                   MIN(created_at) AS first_at,
                   MAX(created_at) AS last_at
              FROM community_prices
             WHERE scout_id = ?
            """,
            (scout_id,),
        )
        summary = dict(rows[0]) if rows else {}
        receipts = self.db.query_one(
            "SELECT COUNT(*) AS n FROM receipts WHERE scout_id = ?", (scout_id,)
        )
        contributions = int(summary.get("contributions") or 0)
        return {
            "scout_id": scout_id,
            "contributions": contributions,
            "products": int(summary.get("products") or 0),
            "regions": int(summary.get("regions") or 0),
            "receipts": int(receipts["n"]) if receipts else 0,
            "first_at": summary.get("first_at"),
            "last_at": summary.get("last_at"),
            "badges": badges_for(contributions, int(receipts["n"]) if receipts else 0),
        }

    # -- receipts ---------------------------------------------------------
    def save_receipt(
        self,
        *,
        store: str | None,
        postal_code: str | None,
        scout_id: str | None,
        filename: str | None,
        content_type: str | None,
        raw_text: str,
        item_count: int,
        engine: str,
    ) -> str:
        receipt_id = uuid.uuid4().hex
        self.db.execute(
            """
            INSERT INTO receipts
                (id, store, postal_code, scout_id, filename, content_type,
                 raw_text, item_count, engine, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'parsed', ?)
            """,
            (
                receipt_id,
                (store or "").lower() or None,
                postal_code,
                scout_id,
                filename,
                content_type,
                raw_text[:20000],
                int(item_count),
                engine,
                _iso_now(),
            ),
        )
        return receipt_id

    def get_receipt(self, receipt_id: str) -> dict[str, Any] | None:
        row = self.db.query_one("SELECT * FROM receipts WHERE id = ?", (receipt_id,))
        return dict(row) if row else None


def badges_for(contributions: int, receipts: int) -> list[dict[str, str]]:
    """Gamification badges (pure function, also mirrored in the UI)."""

    badges: list[dict[str, str]] = []
    if contributions >= 1:
        badges.append({"id": "first-price", "label": "Erster Preis", "icon": "🌱"})
    if receipts >= 1:
        badges.append({"id": "receipt-scout", "label": "Kassenbon-Scout", "icon": "🧾"})
    if contributions >= 5:
        badges.append(
            {"id": "neighbourhood", "label": "Nachbarschafts-Helfer", "icon": "🏘️"}
        )
    if contributions >= 20:
        badges.append({"id": "local-hero", "label": "Preis-Held", "icon": "🏆"})
    return badges


def to_products(aggregated: Iterable[dict[str, Any]]) -> list[NormalizedProduct]:
    """Convert aggregated community rows into standard-price products."""

    products: list[NormalizedProduct] = []
    for entry in aggregated:
        unit = entry.get("unit") or "stueck"
        quantity = entry.get("quantity")
        products.append(
            NormalizedProduct(
                id=f"crowd-{entry['identity']}-{entry['store']}-{entry['postal_code']}",
                store=entry["store"],
                name=entry["name"],
                price=float(entry["median_price"]),
                quantity=float(quantity) if quantity else 1.0,
                unit=unit,
                unit_price=entry.get("median_unit_price"),
                offer_type="standard",
                source="community",
                postal_code=entry["postal_code"],
                valid_from=entry.get("last_updated"),
                category="Community",
            )
        )
    return products


__all__ = [
    "COVERAGE_LEVELS",
    "VERIFY_THRESHOLD",
    "CommunityPriceInput",
    "CommunityStore",
    "badges_for",
    "identity_of",
    "to_products",
]
