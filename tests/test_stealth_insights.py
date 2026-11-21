"""Tests for the stealth gate, robots policy and price insights."""

from __future__ import annotations

import base64
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from supermarket_comparison.api.main import create_app
from supermarket_comparison.api.routes.history import get_repository
from supermarket_comparison.config import get_settings
from supermarket_comparison.models import NormalizedProduct
from supermarket_comparison.storage import Database, Repository


def force_settings(**values: object) -> None:
    """Mutate the frozen Settings singleton for the duration of one test."""

    settings = get_settings()
    for key, value in values.items():
        object.__setattr__(settings, key, value)


def basic(password: str, user: str = "scout") -> dict[str, str]:
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


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
    force_settings(stealth_mode=True, site_password=None, session_secret=None)


def product(
    price: float, *, store: str = "lidl", day_offset: int = 0
) -> NormalizedProduct:
    return NormalizedProduct(
        id=f"mg-{store}-{price}-{day_offset}",
        store=store,
        name="Bio Butter 250g",
        price=price,
        quantity=0.25,
        unit="kg",
        offer_type="prospect",
        source="marktguru",
    )


# -- robots / stealth -------------------------------------------------------


def test_robots_disallows_everything_in_stealth_mode(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    force_settings(stealth_mode=True)

    response = client.get("/robots.txt")

    assert response.status_code == 200
    assert response.text == "User-agent: *\nDisallow: /\n"


def test_robots_allows_crawling_when_stealth_is_off(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    force_settings(stealth_mode=False)

    assert client.get("/robots.txt").text == "User-agent: *\nAllow: /\n"


def test_noindex_headers_and_meta_in_stealth_mode(client: TestClient) -> None:
    force_settings(stealth_mode=True, site_password=None)

    response = client.get("/")

    assert response.headers["x-robots-tag"] == "noindex, nofollow, noarchive"
    assert 'name="robots" content="noindex, nofollow"' in response.text


def test_public_site_has_no_noindex_meta(client: TestClient) -> None:
    force_settings(stealth_mode=False, site_password=None)

    response = client.get("/")

    assert 'name="robots"' not in response.text


# -- password gate ----------------------------------------------------------


def test_gate_is_off_without_password(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    force_settings(site_password=None)

    assert client.get("/").status_code == 200
    assert client.get("/api/v1/stats/summary").status_code == 200


def test_api_requires_credentials_when_password_is_set(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    force_settings(site_password="geheim123")

    assert client.get("/api/v1/stats/summary").status_code == 401
    assert (
        client.get("/api/v1/stats/summary", headers=basic("falsch")).status_code == 401
    )
    assert (
        client.get("/api/v1/stats/summary", headers=basic("geheim123")).status_code
        == 200
    )


def test_health_stays_public(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    force_settings(site_password="geheim123")

    assert client.get("/health").status_code == 200


def test_browser_is_redirected_to_the_login_page(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    force_settings(site_password="geheim123")

    response = client.get("/", headers={"Accept": "text/html"}, follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"].startswith("/login")


def test_login_sets_a_working_session_cookie(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    force_settings(site_password="geheim123")

    wrong = client.post(
        "/login", data={"password": "nope", "next": "/"}, follow_redirects=False
    )
    assert wrong.status_code == 303
    assert wrong.headers["location"].startswith("/login")

    ok = client.post(
        "/login", data={"password": "geheim123", "next": "/"}, follow_redirects=False
    )
    assert ok.status_code == 303
    assert "spv_session" in ok.cookies

    client.cookies.set("spv_session", ok.cookies["spv_session"])
    assert client.get("/").status_code == 200


def test_logout_clears_the_session(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    force_settings(site_password="geheim123")
    client.post("/login", data={"password": "geheim123", "next": "/"})

    response = client.post("/logout", follow_redirects=False)

    assert response.status_code == 303
    assert client.get("/api/v1/stats/summary").status_code == 401


def test_open_redirect_is_blocked(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    force_settings(site_password="geheim123")

    response = client.post(
        "/login",
        data={"password": "geheim123", "next": "https://evil.example"},
        follow_redirects=False,
    )

    assert response.headers["location"] == "/"


# -- price insights ---------------------------------------------------------


def _seed_history(repository: Repository) -> None:
    data = [
        (1.99, 40),
        (1.79, 30),
        (1.59, 20),
        (1.89, 10),
        (1.49, 0),
    ]
    for price, offset in data:
        repository.record_offers([product(price)])
        # Backdate the rows so the series has a realistic spread.
        repository.db.execute(
            "UPDATE price_history SET changed_at = ? WHERE price = ?",
            (
                (datetime.now(tz=UTC) - timedelta(days=offset))
                .replace(microsecond=0)
                .isoformat(),
                price,
            ),
        )


def test_insights_require_a_product(client: TestClient) -> None:
    assert client.get("/api/v1/products/price-insights").status_code == 422


def test_insights_are_empty_without_history(client: TestClient) -> None:
    payload = client.get(
        "/api/v1/products/price-insights", params={"name": "Butter"}
    ).json()

    assert payload["count"] == 0
    assert payload["verdict"]["level"] == "unknown"
    assert payload["stats"]["current"] is None


def test_insights_compute_low_high_average_and_verdict(
    client: TestClient, repository: Repository
) -> None:
    _seed_history(repository)

    payload = client.get(
        "/api/v1/products/price-insights",
        params={"name": "Bio Butter 250g", "days": 0},
    ).json()

    assert payload["count"] == 5
    assert payload["stats"]["low"] == pytest.approx(1.49)
    assert payload["stats"]["high"] == pytest.approx(1.99)
    assert payload["stats"]["average"] == pytest.approx(1.75)
    assert payload["stats"]["current"] == pytest.approx(1.49)
    assert payload["verdict"]["level"] == "top"


def test_insights_flag_an_expensive_price(
    client: TestClient, repository: Repository
) -> None:
    for price, offset in [(1.49, 30), (1.59, 20), (1.55, 10), (1.99, 0)]:
        repository.record_offers([product(price)])
        repository.db.execute(
            "UPDATE price_history SET changed_at = ? WHERE price = ?",
            (
                (datetime.now(tz=UTC) - timedelta(days=offset))
                .replace(microsecond=0)
                .isoformat(),
                price,
            ),
        )

    payload = client.get(
        "/api/v1/products/price-insights", params={"name": "Bio Butter 250g"}
    ).json()

    assert payload["stats"]["current"] == pytest.approx(1.99)
    assert payload["verdict"]["level"] == "expensive"


def test_insights_say_the_history_is_building_with_two_points(
    client: TestClient, repository: Repository
) -> None:
    repository.record_offers([product(1.79)])
    repository.record_offers([product(1.69)])

    payload = client.get(
        "/api/v1/products/price-insights", params={"name": "Bio Butter 250g"}
    ).json()

    assert payload["count"] == 2
    assert payload["verdict"]["level"] == "building"
    assert "im Aufbau" in payload["verdict"]["label"]


def test_insights_list_the_cheapest_store_per_point(
    client: TestClient, repository: Repository
) -> None:
    repository.record_offers([product(1.79, store="lidl")])
    repository.record_offers([product(1.49, store="netto", day_offset=1)])

    payload = client.get(
        "/api/v1/products/price-insights", params={"name": "Bio Butter 250g"}
    ).json()

    assert [entry["store"] for entry in payload["stores"]] == ["netto", "lidl"]
    assert payload["stores"][0]["price"] == pytest.approx(1.49)
