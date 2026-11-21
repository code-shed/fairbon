"""Tests for the admin database registry (query, update, delete)."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from supermarket_comparison.services.admin_records import (
    TABLES,
    delete_record,
    list_records,
    update_record,
)
from supermarket_comparison.storage import Database, Repository


@pytest.fixture()
def repository() -> Iterator[Repository]:
    repo = Repository(Database(":memory:"))
    yield repo
    repo.close()


def seed(repository: Repository) -> None:
    from supermarket_comparison.models import NormalizedProduct

    for name, price in [("Butter", 2.49), ("Milch", 1.19), ("Kaffee", 5.99)]:
        repository.record_offers(
            [
                NormalizedProduct(
                    id=f"mg-{name}",
                    store="lidl",
                    name=name,
                    brand="Testbrand",
                    price=price,
                    quantity=1.0,
                    unit="stueck",
                    offer_type="prospect",
                    source="marktguru",
                )
            ]
        )


def test_registry_lists_the_admin_tables() -> None:
    assert set(TABLES) == {
        "products",
        "price_points",
        "price_history",
        "community_prices",
    }
    for spec in TABLES.values():
        assert spec.editable, spec.name
        assert spec.list_columns


def test_list_records_paginates_and_counts(repository: Repository) -> None:
    seed(repository)

    page = list_records(repository.db, "price_points", page=1, page_size=2)

    assert page["table"] == "price_points"
    assert page["total"] == 3
    assert page["page"] == 1
    assert page["pages"] == 2
    assert len(page["rows"]) == 2
    assert page["rows"][0]["id"] > page["rows"][1]["id"]  # newest first


def test_list_records_searches_text_columns(repository: Repository) -> None:
    seed(repository)

    page = list_records(repository.db, "price_points", q="milch")

    assert page["total"] == 1
    assert page["rows"][0]["store"] == "lidl"


def test_list_records_filters_by_store(repository: Repository) -> None:
    seed(repository)

    assert (
        list_records(repository.db, "price_points", filters={"store": "rewe"})["total"]
        == 0
    )
    assert (
        list_records(repository.db, "price_points", filters={"store": "lidl"})["total"]
        == 3
    )


def test_list_records_rejects_unknown_table(repository: Repository) -> None:
    with pytest.raises(ValueError):
        list_records(repository.db, "sqlite_master")


def test_update_record_changes_allowed_fields(repository: Repository) -> None:
    seed(repository)
    row = list_records(repository.db, "price_points", q="butter")["rows"][0]

    updated = update_record(
        repository.db,
        "price_points",
        row["id"],
        {"price": 1.99, "valid_to": "2026-12-24"},
    )

    assert updated is not None
    assert updated["price"] == pytest.approx(1.99)
    assert updated["valid_to"] == "2026-12-24"


def test_update_record_rejects_unknown_field(repository: Repository) -> None:
    seed(repository)
    row = list_records(repository.db, "price_points")["rows"][0]

    with pytest.raises(ValueError, match="not editable"):
        update_record(repository.db, "price_points", row["id"], {"dropped": 1})


def test_update_record_rejects_negative_price(repository: Repository) -> None:
    seed(repository)
    row = list_records(repository.db, "price_points")["rows"][0]

    with pytest.raises(ValueError, match="price"):
        update_record(repository.db, "price_points", row["id"], {"price": -1})


def test_update_record_rejects_wrong_type(repository: Repository) -> None:
    seed(repository)
    row = list_records(repository.db, "price_points")["rows"][0]

    with pytest.raises(ValueError):
        update_record(repository.db, "price_points", row["id"], {"price": "teuer"})


def test_update_missing_record_returns_none(repository: Repository) -> None:
    assert update_record(repository.db, "price_points", 999999, {"price": 1.0}) is None


def test_delete_record_removes_the_row(repository: Repository) -> None:
    seed(repository)
    row = list_records(repository.db, "price_points", q="kaffee")["rows"][0]

    assert delete_record(repository.db, "price_points", row["id"]) is True
    assert list_records(repository.db, "price_points", q="kaffee")["total"] == 0


def test_delete_missing_record_returns_false(repository: Repository) -> None:
    assert delete_record(repository.db, "price_points", 999999) is False


def test_deleting_a_product_cascades_prices(repository: Repository) -> None:
    seed(repository)
    product = list_records(repository.db, "products", q="butter")["rows"][0]

    assert delete_record(repository.db, "products", product["id"]) is True
    assert list_records(repository.db, "price_points", q="butter")["total"] == 0
