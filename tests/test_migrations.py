"""Startup migration tests (idempotent backfills on existing databases)."""

from __future__ import annotations

from supermarket_comparison.storage import Database


def test_migrate_promotes_only_plausible_receipt_rows(tmp_path) -> None:
    database = Database(str(tmp_path / "migrate.db"))
    conn = database._conn
    now = "2026-11-22T00:00:00"
    for source, status, name in (
        ("receipt", "pending", "Milch"),
        ("receipt", "pending_review", "Gold"),
        ("scout", "pending", "Brot"),
    ):
        conn.execute(
            "INSERT INTO community_prices (id, identity, ean, name, store,"
            " price, postal_code, source, status, confirmations, created_at,"
            " updated_at) VALUES (?, ?, NULL, ?, 'penny', 1.0, '65618', ?,"
            " ?, 1, ?, ?)",
            (f"id-{name}", f"identity-{name}", name, source, status, now, now),
        )
    conn.commit()
    database.close()

    database = Database(str(tmp_path / "migrate.db"))  # rerun: idempotency

    rows = database._conn.execute(
        "SELECT name, status FROM community_prices ORDER BY name"
    ).fetchall()
    statuses = {row["name"]: row["status"] for row in rows}
    database.close()

    assert statuses == {
        "Milch": "verified",  # plausible receipt row promoted
        "Gold": "pending_review",  # flagged row untouched
        "Brot": "pending",  # other sources untouched
    }
