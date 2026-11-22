"""Thin, synchronous SQLite wrapper.

The API is async, so every public helper is executed via
:func:`asyncio.to_thread` by the repository.  A single connection guarded by a
lock is sufficient for this workload (one local process, low write volume) and
avoids ``database is locked`` surprises from ``check_same_thread=False``
without a lock.
"""

from __future__ import annotations

import sqlite3
import threading
from importlib import resources
from pathlib import Path
from typing import Any, Self

SCHEMA_VERSION = 9


def load_schema() -> str:
    """Return the packaged SQL schema."""

    return (
        resources.files(__package__).joinpath("schema.sql").read_text(encoding="utf-8")
    )


class Database:
    """Owns the SQLite connection and applies the schema once."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(
            str(self.path), check_same_thread=False, timeout=30.0
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._apply_schema()

    def _apply_schema(self) -> None:
        with self._lock:
            self._conn.executescript(load_schema())
            self._migrate()

    def _migrate(self) -> None:
        """Add columns that older databases predate (idempotent)."""

        columns = {
            row["name"]
            for row in self._conn.execute("PRAGMA table_info(products)").fetchall()
        }
        if "image_url" not in columns:
            self._conn.execute("ALTER TABLE products ADD COLUMN image_url TEXT")

        community_columns = {
            row["name"]
            for row in self._conn.execute(
                "PRAGMA table_info(community_prices)"
            ).fetchall()
        }
        for column in ("review_reason", "reviewed_at", "reviewed_by"):
            if column not in community_columns:
                self._conn.execute(
                    f"ALTER TABLE community_prices ADD COLUMN {column} TEXT"
                )

        # Iteration 10: remove placeholder brands and unverifiable images that
        # the old, too-loose Open Food Facts text match produced.
        from .cleanup import clean_database, revalidate_pending

        try:
            revalidate_pending(self._conn)
            result = clean_database(self._conn)
        except Exception:  # pragma: no cover - cleanup must never block startup
            result = {}
        if result:
            self._conn.commit()
            self._conn.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES ('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )
            self._conn.commit()

    # -- primitives -------------------------------------------------------
    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> sqlite3.Cursor:
        with self._lock:
            cursor = self._conn.execute(sql, params)
            self._conn.commit()
            return cursor

    def executemany(self, sql: str, rows: list[tuple[Any, ...]]) -> sqlite3.Cursor:
        with self._lock:
            cursor = self._conn.executemany(sql, rows)
            self._conn.commit()
            return cursor

    def query(self, sql: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return list(self._conn.execute(sql, params).fetchall())

    def query_one(self, sql: str, params: tuple[Any, ...] = ()) -> sqlite3.Row | None:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


__all__ = ["SCHEMA_VERSION", "Database", "load_schema"]
