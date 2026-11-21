"""Seed a demo database with realistic community price points.

For self-hosters who want to explore the UI without scanning real receipts:
this inserts a small set of plausible products and community prices into
``data/supermarkt.db`` (or the database configured via
``SUPERMARKET_DATABASE_PATH``).

Usage::

    uv run python scripts/seed_demo.py
    uv run python scripts/seed_demo.py --db /tmp/demo.db

The script is idempotent: products are keyed deterministically, so re-running
does not duplicate rows.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

# Allow running from a source checkout without installation.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from supermarket_comparison.models import NormalizedProduct
from supermarket_comparison.storage import Database, Repository


def _days_ago(n: int) -> str:
    return (date.today() - timedelta(days=n)).isoformat()


def _demo_offers() -> list[NormalizedProduct]:
    """~10 realistic offers across stores and categories."""

    base = [
        # (name, brand, store, price, quantity, unit, category)
        ("Feine Butter", "Weihenstephan", "rewe", 1.99, 0.25, "kg", "Butter"),
        ("Feine Butter", "Weihenstephan", "netto", 1.49, 0.25, "kg", "Butter"),
        ("Frische Vollmilch 3,5%", "Weihenstephan", "lidl", 1.19, 1.0, "l", "Milch"),
        ("Frische Vollmilch 3,5%", "Weihenstephan", "edeka", 1.29, 1.0, "l", "Milch"),
        ("Bauernbrot", "", "edeka", 1.79, 1.0, "stueck", "Brot"),
        ("Bier", "Beck's", "penny", 0.79, 0.5, "l", "Bier"),
        ("Bier", "Beck's", "rewe", 0.89, 0.5, "l", "Bier"),
        ("Griechischer Joghurt 10%", "Milbona", "lidl", 0.99, 0.5, "kg", "Joghurt"),
        ("Kaffee gemahlen", "Melitta", "rewe", 4.99, 0.5, "kg", "Kaffee"),
        ("Spaghetti", "Barilla", "netto", 1.29, 0.5, "kg", "Nudeln"),
    ]

    offers: list[NormalizedProduct] = []
    for i, (name, brand, store, price, quantity, unit, category) in enumerate(base):
        offers.append(
            NormalizedProduct(
                id=f"demo-{i}",
                store=store,
                name=name,
                brand=brand or None,
                price=price,
                quantity=quantity,
                unit=unit,
                category=category,
                offer_type="standard",
                source="seed",
            )
        )
    return offers


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db",
        default=None,
        help="SQLite path (default: from config, data/supermarkt.db).",
    )
    args = parser.parse_args(argv)

    repo = Repository(Database(args.db)) if args.db else Repository()
    try:
        offers = _demo_offers()
        stats = repo.record_offers(offers)

        # Backdate the observations so the price history looks lived-in.
        day = _days_ago(3)
        for offer in offers:
            repo.db.execute(
                """
                UPDATE price_points
                   SET observed_at = ?, observed_day = ?
                 WHERE product_id = (
                     SELECT id FROM products WHERE key = ?
                 )
                """,
                (day, day[:10], offer.id),
            )

        print(f"Seeded {len(offers)} demo offers.")
        print(f"  products:     {stats['products']}")
        print(f"  price points: {len([o for o in offers])}")
        print("Done. Open the UI and search for 'Butter', 'Milch' or 'Bier'.")
        return 0
    finally:
        repo.close()


if __name__ == "__main__":
    raise SystemExit(main())
