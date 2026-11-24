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


def test_migrate_adds_is_business_column(tmp_path) -> None:
    path = str(tmp_path / "business.db")
    database = Database(path)
    conn = database._conn
    conn.execute("ALTER TABLE user_receipts DROP COLUMN is_business")
    conn.commit()
    database.close()

    database = Database(path)  # _migrate re-adds the column

    columns = {
        row["name"]
        for row in database._conn.execute("PRAGMA table_info(user_receipts)")
    }
    database.close()
    assert "is_business" in columns


def test_migrate_normalizes_stored_categories(tmp_path) -> None:
    from supermarket_comparison.storage import Repository

    path = str(tmp_path / "categories.db")
    database = Database(path)
    conn = database._conn
    conn.execute(
        "INSERT INTO user_receipts (owner_token, store, postal_code,"
        " country_code, currency, receipt_date, total_cents, created_at) VALUES"
        " ('owner-token-1234', 'penny', '65618', 'DE', 'EUR', '2026-11-22', 100,"
        " '2026-11-22T00:00:00')"
    )
    conn.execute(
        "INSERT INTO user_receipt_items (receipt_id, raw_text, normalized_name,"
        " category, price_cents) VALUES (1, 'Bier', 'Bier', 'Getraenke', 100)"
    )
    conn.execute(
        "INSERT INTO receipt_aliases (store, raw_text_norm, normalized_name,"
        " category, created_at, updated_at) VALUES"
        " ('penny', 'bier', 'Bier', 'Getraenke', '2026-11-22', '2026-11-22')"
    )
    conn.commit()
    database.close()

    database = Database(path)  # idempotente Migration
    repo = Repository(database)
    items = repo.user_receipt_items_for(1)
    aliases = database._conn.execute("SELECT category FROM receipt_aliases").fetchall()
    aliases_category = aliases[0]["category"] if aliases else None
    database.close()

    assert items[0]["category"] == "Getränke"
    assert aliases_category == "Getränke"
