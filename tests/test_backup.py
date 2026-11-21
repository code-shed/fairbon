"""Tests for the SQLite backup and restore endpoints."""

from __future__ import annotations

import base64
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from supermarket_comparison.api.main import create_app
from supermarket_comparison.api.routes.history import get_repository
from supermarket_comparison.api.routes.system import MAX_RESTORE_BYTES
from supermarket_comparison.models import NormalizedProduct
from supermarket_comparison.storage import Database, Repository

PREFIX = "/api/v1"
SQLITE_HEADER = b"SQLite format 3\x00"


def product(
    *,
    name: str = "Bio Vollmilch",
    ean: str = "4012345678901",
    price: float = 1.29,
) -> NormalizedProduct:
    return NormalizedProduct(
        id=f"lidl-{name.lower().replace(' ', '-')}",
        store="lidl",
        name=name,
        brand="Weihenstephan",
        ean=ean,
        price=price,
        quantity=1.0,
        unit="l",
    )


@pytest.fixture()
def repository(tmp_path: Path) -> Iterator[Repository]:
    repo = Repository(Database(tmp_path / "test.db"))
    yield repo
    repo.close()


ADMIN_AUTH = {
    "Authorization": "Basic "
    + base64.b64encode(b"admin:test-admin-pw").decode()
}


def build_app(repository: Repository) -> Any:
    app = create_app()
    app.dependency_overrides[get_repository] = lambda: repository
    return app


def test_backup_returns_a_valid_sqlite_download(
    repository: Repository, tmp_path: Path
) -> None:
    repository.record_offers([product(name="DB A", ean="4000000000001")])

    with TestClient(build_app(repository), headers=ADMIN_AUTH) as client:
        response = client.get(f"{PREFIX}/system/backup-db")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/octet-stream"
    disposition = response.headers["content-disposition"]
    assert "supermarkt-" in disposition
    assert disposition.endswith('.db"')

    data = response.content
    assert data.startswith(SQLITE_HEADER)

    download = tmp_path / "download.db"
    download.write_bytes(data)
    connection = sqlite3.connect(download)
    try:
        names = [row[0] for row in connection.execute("SELECT name FROM products")]
    finally:
        connection.close()
    assert names == ["DB A"]


def test_restore_roundtrip_brings_back_the_old_rows(
    repository: Repository,
) -> None:
    repository.record_offers([product(name="DB A", ean="4000000000001")])

    with TestClient(build_app(repository), headers=ADMIN_AUTH) as client:
        backup = client.get(f"{PREFIX}/system/backup-db")
    assert backup.status_code == 200
    backup_bytes = backup.content

    # Turn the live database into "DB B".
    repository.db.execute("DELETE FROM price_points")
    repository.db.execute("DELETE FROM products")
    repository.record_offers([product(name="DB B", ean="4000000000002")])
    assert repository.db.query_one("SELECT name FROM products")["name"] == "DB B"

    with TestClient(build_app(repository), headers=ADMIN_AUTH) as client:
        response = client.post(
            f"{PREFIX}/system/restore-db",
            files={"file": ("backup.db", backup_bytes, "application/octet-stream")},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "restored"
    assert payload["products"] == 1
    assert payload["price_points"] == 1
    backup_path = Path(payload["backup_file"])
    assert backup_path.exists()
    assert backup_path.parent == repository.db.path.parent
    assert ".bak-" in backup_path.name

    row = repository.db.query_one("SELECT name FROM products")
    assert row is not None
    assert row["name"] == "DB A"
    assert repository.db.query_one("SELECT COUNT(*) AS n FROM products")["n"] == 1


def test_restore_via_history_endpoint(repository: Repository) -> None:
    repository.record_offers([product(name="DB A", ean="4000000000001")])

    with TestClient(build_app(repository), headers=ADMIN_AUTH) as client:
        backup = client.get(f"{PREFIX}/system/backup-db").content

    repository.db.execute("DELETE FROM price_points")
    repository.db.execute("DELETE FROM products")
    repository.record_offers([product(name="DB B", ean="4000000000002")])

    app = build_app(repository)
    with TestClient(app, headers=ADMIN_AUTH) as client:
        restored = client.post(
            f"{PREFIX}/system/restore-db",
            files={"file": ("backup.db", backup, "application/octet-stream")},
        )
        assert restored.status_code == 200
        history = client.get(
            f"{PREFIX}/products/history", params={"ean": "4000000000001"}
        )

    assert history.status_code == 200
    assert history.json()["count"] >= 1
    assert history.json()["points"][0]["name"] == "DB A"


def test_restore_rejects_bytes_that_are_not_sqlite(repository: Repository) -> None:
    with TestClient(build_app(repository), headers=ADMIN_AUTH) as client:
        response = client.post(
            f"{PREFIX}/system/restore-db",
            files={"file": ("broken.db", b"definitely not sqlite", "text/plain")},
        )

    assert response.status_code == 400
    assert "SQLite" in response.json()["detail"]


def test_restore_rejects_sqlite_without_required_tables(
    repository: Repository, tmp_path: Path
) -> None:
    unrelated = tmp_path / "unrelated.db"
    connection = sqlite3.connect(unrelated)
    try:
        connection.execute("CREATE TABLE something_else (id INTEGER PRIMARY KEY)")
        connection.commit()
    finally:
        connection.close()

    with TestClient(build_app(repository), headers=ADMIN_AUTH) as client:
        response = client.post(
            f"{PREFIX}/system/restore-db",
            files={
                "file": (
                    "unrelated.db",
                    unrelated.read_bytes(),
                    "application/octet-stream",
                )
            },
        )

    assert response.status_code == 400
    assert "required tables" in response.json()["detail"]


def test_in_memory_database_cannot_be_backed_up() -> None:
    repo = Repository(Database(":memory:"))
    try:
        with TestClient(build_app(repo), headers=ADMIN_AUTH) as client:
            response = client.get(f"{PREFIX}/system/backup-db")
    finally:
        repo.close()

    assert response.status_code == 404


def test_restore_size_limit_is_defined() -> None:
    assert MAX_RESTORE_BYTES == 200 * 1024 * 1024
