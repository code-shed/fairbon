"""Startup migration tests (idempotent backfills on existing databases)."""

from __future__ import annotations

from supermarket_comparison.storage import Database

FLAG_KEY = "community_receipt_backfill_done"
NOW = "2026-11-22T00:00:00"


def _insert(
    conn,  # type: ignore[no-untyped-def]
    price_id: str,
    name: str,
    source: str,
    status: str,
    *,
    review_reason: str | None = None,
) -> None:
    conn.execute(
        "INSERT INTO community_prices (id, identity, ean, name, store,"
        " price, postal_code, source, status, confirmations, review_reason,"
        " created_at, updated_at) VALUES (?, ?, NULL, ?, 'penny', 1.0,"
        " '65618', ?, ?, 1, ?, ?, ?)",
        (price_id, f"identity-{name}", name, source, status, review_reason, NOW, NOW),
    )


def _statuses(database: Database) -> dict[str, str]:
    rows = database._conn.execute(
        "SELECT name, status FROM community_prices ORDER BY name"
    ).fetchall()
    return {row["name"]: row["status"] for row in rows}


def _clear_backfill_flag(conn) -> None:  # type: ignore[no-untyped-def]
    """Simulate a database created before the backfill ever ran."""

    conn.execute(f"DELETE FROM meta WHERE key = '{FLAG_KEY}'")


def test_migrate_promotes_only_plausible_receipt_rows(tmp_path) -> None:
    path = str(tmp_path / "migrate.db")
    database = Database(path)
    conn = database._conn
    _insert(conn, "id-milch", "Milch", "receipt", "pending")
    _insert(conn, "id-gold", "Gold", "receipt", "pending_review")
    _insert(conn, "id-brot", "Brot", "scout", "pending")
    conn.commit()
    _clear_backfill_flag(conn)
    conn.commit()
    database.close()

    database = Database(path)  # second init: idempotent

    statuses = _statuses(database)
    database.close()
    assert statuses == {
        "Milch": "verified",  # plausible receipt row promoted
        "Gold": "pending_review",  # flagged row untouched
        "Brot": "pending",  # other sources untouched
    }


def test_backfill_runs_once_and_spares_rows_with_review_reason(tmp_path) -> None:
    path = str(tmp_path / "migrate-once.db")
    database = Database(path)
    conn = database._conn
    _insert(conn, "id-milch", "Milch", "receipt", "pending")
    _insert(
        conn,
        "id-gold",
        "Gold",
        "receipt",
        "pending",
        review_reason="Preis 5000,00 außerhalb der Grenze 0,10–200,00.",
    )
    conn.commit()
    _clear_backfill_flag(conn)
    conn.commit()
    database.close()

    database = Database(path)  # first start: one-time backfill runs
    statuses = _statuses(database)
    database.close()
    assert statuses == {"Milch": "verified", "Gold": "pending"}

    # A later crowd submission shares source='receipt' (import_receipt
    # default) and must keep the scout confirmation flow: the backfill
    # has already run, so it stays pending.
    database = Database(path)
    conn = database._conn
    _insert(conn, "id-neu", "Neu", "receipt", "pending")
    conn.commit()
    database.close()

    database = Database(path)  # flag present: no further promotion
    statuses = _statuses(database)
    database.close()
    assert statuses == {
        "Milch": "verified",
        "Gold": "pending",
        "Neu": "pending",
    }
