"""Integration tests for the admin database endpoints (auth + CRUD)."""

from __future__ import annotations

import base64
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from supermarket_comparison.api.main import create_app
from supermarket_comparison.api.routes.history import get_repository
from supermarket_comparison.config import get_settings
from supermarket_comparison.models import NormalizedProduct
from supermarket_comparison.storage import Database, Repository

PREFIX = "/api/v1/admin/database"


def basic(password: str, user: str = "admin") -> dict[str, str]:
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def force_settings(**values: object) -> None:
    settings = get_settings()
    for key, value in values.items():
        object.__setattr__(settings, key, value)


@pytest.fixture()
def repository() -> Iterator[Repository]:
    repo = Repository(Database(":memory:"))
    yield repo
    repo.close()


@pytest.fixture()
def client(repository: Repository) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[get_repository] = lambda: repository
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    object.__setattr__(get_settings(), "site_password", None)


def seed(repository: Repository) -> None:
    for name, price in [("Butter", 2.49), ("Milch", 1.19)]:
        repository.record_offers(
            [
                NormalizedProduct(
                    id=f"mg-{name}",
                    store="lidl",
                    name=name,
                    price=price,
                    quantity=1.0,
                    unit="stueck",
                    source="marktguru",
                )
            ]
        )


def auth() -> dict[str, str]:
    force_settings(admin_password="test-admin-pw")
    return basic("test-admin-pw")


# -- authentication ---------------------------------------------------------


def test_records_require_a_password(client: TestClient) -> None:
    force_settings(admin_password="test-admin-pw")

    assert (
        client.get(f"{PREFIX}/records", params={"table": "products"}).status_code == 401
    )
    assert (
        client.get(
            f"{PREFIX}/records",
            params={"table": "products"},
            headers=basic("falsch"),
        ).status_code
        == 401
    )


def test_records_are_readable_with_the_password(
    client: TestClient, repository: Repository
) -> None:
    seed(repository)
    headers = auth()

    response = client.get(
        f"{PREFIX}/records", params={"table": "products"}, headers=headers
    )

    assert response.status_code == 200
    assert response.json()["total"] == 2


# -- read ------------------------------------------------------------------


def test_schema_lists_the_tables(client: TestClient) -> None:
    headers = auth()

    payload = client.get(f"{PREFIX}/schema", headers=headers).json()

    names = [table["name"] for table in payload["tables"]]
    assert names == ["products", "price_points", "price_history", "community_prices"]
    assert payload["max_page_size"] >= 100


def test_records_are_paginated(client: TestClient, repository: Repository) -> None:
    seed(repository)
    headers = auth()

    payload = client.get(
        f"{PREFIX}/records",
        params={"table": "price_points", "page_size": 1},
        headers=headers,
    ).json()

    assert payload["total"] == 2
    assert payload["pages"] == 2
    assert len(payload["rows"]) == 1


def test_records_search_and_filter(client: TestClient, repository: Repository) -> None:
    seed(repository)
    headers = auth()

    payload = client.get(
        f"{PREFIX}/records",
        params={"table": "price_points", "q": "milch", "store": "lidl"},
        headers=headers,
    ).json()

    assert payload["total"] == 1
    assert payload["rows"][0]["store"] == "lidl"


def test_unknown_table_returns_404(client: TestClient) -> None:
    headers = auth()

    response = client.get(
        f"{PREFIX}/records", params={"table": "sqlite_master"}, headers=headers
    )

    assert response.status_code == 404


# -- write -----------------------------------------------------------------


def test_update_persists_and_returns_the_row(
    client: TestClient, repository: Repository
) -> None:
    seed(repository)
    headers = auth()
    row = client.get(
        f"{PREFIX}/records",
        params={"table": "price_points", "q": "butter"},
        headers=headers,
    ).json()["rows"][0]

    response = client.put(
        f"{PREFIX}/records/price_points/{row['id']}",
        json={"price": 1.49, "valid_to": "2026-12-31"},
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["price"] == pytest.approx(1.49)
    assert response.json()["valid_to"] == "2026-12-31"


def test_update_rejects_unknown_field(
    client: TestClient, repository: Repository
) -> None:
    seed(repository)
    headers = auth()
    row = client.get(
        f"{PREFIX}/records", params={"table": "price_points"}, headers=headers
    ).json()["rows"][0]

    response = client.put(
        f"{PREFIX}/records/price_points/{row['id']}",
        json={"hacked": 1},
        headers=headers,
    )

    assert response.status_code == 422


def test_update_rejects_negative_price(
    client: TestClient, repository: Repository
) -> None:
    seed(repository)
    headers = auth()
    row = client.get(
        f"{PREFIX}/records", params={"table": "price_points"}, headers=headers
    ).json()["rows"][0]

    response = client.put(
        f"{PREFIX}/records/price_points/{row['id']}",
        json={"price": -5},
        headers=headers,
    )

    assert response.status_code == 422


def test_update_missing_record_returns_404(client: TestClient) -> None:
    headers = auth()

    response = client.put(
        f"{PREFIX}/records/price_points/999999", json={"price": 1.0}, headers=headers
    )

    assert response.status_code == 404


def test_delete_removes_the_row(client: TestClient, repository: Repository) -> None:
    seed(repository)
    headers = auth()
    row = client.get(
        f"{PREFIX}/records",
        params={"table": "price_points", "q": "kaffee"},
        headers=headers,
    ).json()
    target = client.get(
        f"{PREFIX}/records", params={"table": "price_points"}, headers=headers
    ).json()["rows"][0]

    response = client.delete(
        f"{PREFIX}/records/price_points/{target['id']}", headers=headers
    )

    assert response.status_code == 200
    assert response.json() == {"deleted": True}
    assert row["total"] == 0


def test_delete_missing_record_returns_404(client: TestClient) -> None:
    headers = auth()

    assert (
        client.delete(
            f"{PREFIX}/records/price_points/999999", headers=headers
        ).status_code
        == 404
    )


def test_admin_page_is_served_when_authenticated(client: TestClient) -> None:
    headers = auth()

    response = client.get("/admin", headers=headers)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "Datenbank" in response.text


def test_admin_page_rejects_missing_admin_credentials(client: TestClient) -> None:
    force_settings(admin_password="test-admin-pw")

    response = client.get("/admin", follow_redirects=False)

    assert response.status_code == 401
    assert response.headers.get("www-authenticate", "").startswith("Basic")
