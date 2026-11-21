"""Whitelisted database access for the admin dashboard.

Every table, column and sort key comes from :data:`TABLES`; user input never
reaches SQL as an identifier.  Values are coerced and range-checked before they
are written.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final

from ..storage.database import Database

__all__ = [
    "MAX_PAGE_SIZE",
    "TABLES",
    "TableSpec",
    "delete_record",
    "list_records",
    "schema_payload",
    "update_record",
]

MAX_PAGE_SIZE: Final = 100
DEFAULT_PAGE_SIZE: Final = 25

#: Statuses a community price may have.
COMMUNITY_STATUSES: Final = frozenset(
    {"pending", "pending_review", "approved", "verified", "rejected"}
)


@dataclass(frozen=True)
class TableSpec:
    """Metadata and guardrails for one editable table."""

    name: str
    label: str
    list_columns: tuple[str, ...]
    search_columns: tuple[str, ...]
    filter_columns: tuple[str, ...]
    editable: dict[str, str]
    updated_at_column: str | None = None

    def payload(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label,
            "columns": list(self.list_columns),
            "editable": [
                {"name": field, "type": kind} for field, kind in self.editable.items()
            ],
            "filters": list(self.filter_columns),
        }


TABLES: Final[dict[str, TableSpec]] = {
    "products": TableSpec(
        name="products",
        label="Produkte",
        list_columns=(
            "id",
            "name",
            "brand",
            "ean",
            "category",
            "unit",
            "quantity",
            "image_url",
            "updated_at",
        ),
        search_columns=("name", "brand", "ean", "category"),
        filter_columns=(),
        editable={
            "name": "text",
            "brand": "text",
            "ean": "text",
            "category": "text",
            "unit": "text",
            "quantity": "quantity",
            "image_url": "text",
        },
        updated_at_column="updated_at",
    ),
    "price_points": TableSpec(
        name="price_points",
        label="Preispunkte",
        list_columns=(
            "id",
            "product_id",
            "store",
            "offer_type",
            "source",
            "price",
            "old_price",
            "unit_price",
            "unit",
            "valid_from",
            "valid_to",
            "observed_at",
        ),
        search_columns=("store", "source", "offer_id"),
        filter_columns=("store", "source"),
        editable={
            "store": "text",
            "offer_type": "text",
            "source": "text",
            "price": "price",
            "old_price": "price",
            "unit_price": "price",
            "unit": "text",
            "valid_from": "text",
            "valid_to": "text",
        },
    ),
    "price_history": TableSpec(
        name="price_history",
        label="Preishistorie",
        list_columns=(
            "id",
            "product_id",
            "store",
            "offer_type",
            "source",
            "price",
            "unit_price",
            "changed_at",
        ),
        search_columns=("store", "source"),
        filter_columns=("store", "source"),
        editable={
            "store": "text",
            "offer_type": "text",
            "source": "text",
            "price": "price",
            "unit_price": "price",
            "changed_at": "text",
        },
    ),
    "community_prices": TableSpec(
        name="community_prices",
        label="Community-Preise",
        list_columns=(
            "id",
            "name",
            "store",
            "price",
            "unit",
            "quantity",
            "unit_price",
            "postal_code",
            "status",
            "confirmations",
            "review_reason",
            "created_at",
        ),
        search_columns=("name", "store", "ean", "scout_id", "postal_code"),
        filter_columns=("store", "status", "postal_code"),
        editable={
            "name": "text",
            "ean": "text",
            "store": "text",
            "price": "price",
            "unit": "text",
            "quantity": "quantity",
            "unit_price": "price",
            "postal_code": "text",
            "status": "status",
            "review_reason": "text",
        },
        updated_at_column="updated_at",
    ),
}


def _spec(table: str) -> TableSpec:
    spec = TABLES.get(table)
    if spec is None:
        raise ValueError(f"Unknown table: {table!r}")
    return spec


def _now() -> str:
    return datetime.now(tz=UTC).replace(microsecond=0).isoformat()


def _coerce(field: str, kind: str, value: Any) -> Any:
    """Validate one editable value; raises ``ValueError`` with a German hint."""

    if kind == "text":
        text = "" if value is None else str(value).strip()
        if len(text) > 500:
            raise ValueError(f"{field}: Text zu lang (max. 500 Zeichen).")
        return text or None
    if kind == "status":
        text = str(value or "").strip().lower()
        if text not in COMMUNITY_STATUSES:
            raise ValueError(f"{field}: unbekannter Status {value!r}.")
        return text
    if kind in {"price", "quantity"}:
        if isinstance(value, bool):
            raise ValueError(f"{field}: Zahl erwartet.")
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field}: Zahl erwartet.") from exc
        if not math.isfinite(number):
            raise ValueError(f"{field}: keine gültige Zahl.")
        if number < 0:
            raise ValueError(f"{field}: darf nicht negativ sein.")
        return round(number, 4)
    raise ValueError(f"{field}: unbekannter Typ {kind!r}.")


def list_records(
    database: Database,
    table: str,
    *,
    q: str | None = None,
    filters: dict[str, str] | None = None,
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
    sort: str | None = None,
) -> dict[str, Any]:
    """Return one paginated, filtered page of *table*."""

    spec = _spec(table)
    page = max(1, int(page))
    page_size = max(1, min(int(page_size), MAX_PAGE_SIZE))

    clauses: list[str] = []
    params: list[Any] = []

    if q and q.strip():
        term = f"%{q.strip().lower()}%"
        search = " OR ".join(
            f"lower(COALESCE({column}, '')) LIKE ?" for column in spec.search_columns
        )
        clauses.append(f"({search})")
        params.extend([term] * len(spec.search_columns))

    for field, value in (filters or {}).items():
        if field not in spec.filter_columns or value in (None, ""):
            continue
        clauses.append(f"{field} = ?")
        params.append(value)

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    order = "-id"
    if sort:
        candidate = sort if sort in spec.list_columns else sort.lstrip("-")
        if candidate in spec.list_columns:
            order = sort

    descending = order.startswith("-")
    column = order.lstrip("-")
    direction = "DESC" if descending else "ASC"

    total_row = database.query_one(
        f"SELECT COUNT(*) AS n FROM {table} {where}", tuple(params)
    )
    total = int(total_row["n"]) if total_row else 0

    offset = (page - 1) * page_size
    rows = database.query(
        f"""
        SELECT {", ".join(spec.list_columns)}
          FROM {table}
          {where}
         ORDER BY {column} {direction}
         LIMIT ? OFFSET ?
        """,
        (*params, page_size, offset),
    )

    pages = max(1, math.ceil(total / page_size)) if total else 1
    return {
        "table": table,
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": pages,
        "rows": [dict(row) for row in rows],
    }


def update_record(
    database: Database, table: str, record_id: int, values: dict[str, Any]
) -> dict[str, Any] | None:
    """Update whitelisted fields of one row and return the fresh row."""

    spec = _spec(table)
    if not values:
        raise ValueError("Keine Felder zum Aktualisieren angegeben.")

    assignments: list[str] = []
    params: list[Any] = []
    for field, raw in values.items():
        if field not in spec.editable:
            raise ValueError(f"{field}: not editable.")
        if field == "id":
            raise ValueError("id: not editable.")
        assignments.append(f"{field} = ?")
        params.append(_coerce(field, spec.editable[field], raw))

    if spec.updated_at_column:
        assignments.append(f"{spec.updated_at_column} = ?")
        params.append(_now())

    cursor = database.execute(
        f"UPDATE {table} SET {', '.join(assignments)} WHERE id = ?",
        (*params, int(record_id)),
    )
    if cursor.rowcount == 0:
        return None

    row = database.query_one(
        f"SELECT {', '.join(spec.list_columns)} FROM {table} WHERE id = ?",
        (int(record_id),),
    )
    return dict(row) if row else None


def delete_record(database: Database, table: str, record_id: int) -> bool:
    """Delete one row; returns ``False`` when it did not exist."""

    _spec(table)
    cursor = database.execute(f"DELETE FROM {table} WHERE id = ?", (int(record_id),))
    return cursor.rowcount > 0


def schema_payload() -> dict[str, Any]:
    """Table metadata for the admin UI."""

    return {
        "tables": [spec.payload() for spec in TABLES.values()],
        "page_size": DEFAULT_PAGE_SIZE,
        "max_page_size": MAX_PAGE_SIZE,
    }
