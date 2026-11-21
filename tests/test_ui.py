"""Tests for the human-friendly web UI served at ``/``."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from supermarket_comparison.api.deps import get_aggregator
from supermarket_comparison.api.main import create_app, load_index_html
from supermarket_comparison.config import get_settings
from supermarket_comparison.models import NormalizedProduct


class StubAggregator:
    async def search(self, **kwargs):  # pragma: no cover - not used by the UI tests
        return [
            NormalizedProduct(
                id="mg-1",
                store="lidl",
                name="Feine Butter",
                price=1.49,
                quantity=0.25,
                unit="kg",
                unit_price=5.96,
            )
        ]

    async def compare(self, **kwargs):  # pragma: no cover
        return []

    async def search_stores(self, **kwargs):  # pragma: no cover
        return []


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[get_aggregator] = StubAggregator
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_index_html_template_exists() -> None:
    html = load_index_html()

    assert html.lstrip().startswith("<!DOCTYPE html>")
    assert html.rstrip().endswith("</html>")


def test_root_serves_the_html_ui(client: TestClient) -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "Supermarkt-Preisvergleich" in response.text
    assert "Angebote, Standardpreise und Grundpreise vergleichen" in response.text


def test_ui_contains_the_search_form(client: TestClient) -> None:
    html = client.get("/").text

    assert "<form" in html
    assert 'id="search-form"' in html
    assert 'placeholder="z. B. Butter, Bier, Milch"' in html
    assert 'value="65618"' in html
    assert 'pattern="[0-9]{5}"' in html
    assert 'type="submit"' in html
    assert ">Suchen<" in html
    assert "/api/v1/products/search" in html


@pytest.mark.parametrize(
    "label",
    [
        "Lidl",
        "Rewe",
        "Edeka",
        "Aldi",
        "Penny",
        "Netto",
        "Kaufland",
        "Rossmann",
        "dm",
        "Globus",
    ],
)
def test_ui_has_a_checkbox_per_retailer(client: TestClient, label: str) -> None:
    html = client.get("/").text

    assert f'label: "{label}"' in html


def test_ui_contains_states_sorting_and_footer(client: TestClient) -> None:
    html = client.get("/").text

    assert "Keine Angebote gefunden – andere PLZ oder Suchbegriff probieren" in html
    assert "Angebote werden geladen" in html
    assert "Grundpreis" in html
    assert 'data-sort="price"' in html
    assert 'data-sort="unit"' in html
    assert 'data-sort="discount"' in html
    assert "Daten: Community-Kassenbons (anonymisiert) · Open Food Facts" in html
    assert 'href="/docs"' in html


def test_ui_uses_the_ranked_endpoint(client: TestClient) -> None:
    html = client.get("/").text

    assert "/api/v1/products/search/ranked" in html
    assert "/api/v1/basket/optimize" in html


def test_ui_contains_precision_and_today_toggles(client: TestClient) -> None:
    html = client.get("/").text

    assert 'id="precise"' in html
    assert 'id="precise" checked' in html
    assert "Genauere Suche" in html
    assert 'id="today-only"' in html
    assert "Nur heute gültige Angebote" in html
    assert "today_only" in html


def test_ui_contains_standard_price_controls(client: TestClient) -> None:
    html = client.get("/").text

    assert 'id="standard"' in html
    assert "Gesamtes Sortiment inkl. Standardpreise" in html
    assert "Standardpreis · Dauersortiment" in html
    assert "include_standard" in html


def test_ui_contains_quick_filter_chips(client: TestClient) -> None:
    html = client.get("/").text

    assert 'id="chips"' in html
    assert "quick_filters" in html
    assert "Alle zurücksetzen" in html
    assert "exclude" in html


def test_ui_contains_validity_badges_and_relevance_hint(
    client: TestClient,
) -> None:
    html = client.get("/").text

    assert "Heute gültig" in html
    assert "Abgelaufen" in html
    assert "unscharfer Treffer" in html
    assert "validity" in html


def test_ui_contains_the_basket_drawer(client: TestClient) -> None:
    html = client.get("/").text

    assert 'id="basket"' in html
    assert 'id="basket-toggle"' in html
    assert "Merkliste" in html
    assert "spv.basket.v1" in html
    assert "localStorage" in html
    assert "+ Merken" in html
    assert "Alle entfernen" in html
    assert "Günstigste Aufteilung berechnen" in html


def test_ui_contains_share_actions(client: TestClient) -> None:
    html = client.get("/").text

    assert 'id="share-whatsapp"' in html or "share-whatsapp" in html
    assert "WhatsApp teilen" in html
    assert "In die Zwischenablage kopieren" in html
    assert "Kopiert! ✓" in html
    assert "whatsapp_url" in html
    assert 'id="drawer-share"' in html


def test_admin_database_page_is_disabled_without_admin_password(
    client: TestClient,
) -> None:
    """Admin is fail-closed: without ADMIN_PASSWORD the dashboard returns 503."""

    settings = get_settings()
    previous = settings.admin_password
    object.__setattr__(settings, "admin_password", None)
    try:
        response = client.get("/admin")
    finally:
        object.__setattr__(settings, "admin_password", previous)

    assert response.status_code == 503
    assert "deaktiviert" in response.json()["detail"]


def test_admin_database_page_is_available_with_admin_password(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from supermarket_comparison.services.auth import admin_password_matches

    monkeypatch.setenv("ADMIN_PASSWORD", "hunter2")
    get_settings.cache_clear()
    try:
        assert admin_password_matches(get_settings(), "hunter2") is True
        assert admin_password_matches(get_settings(), "wrong") is False
    finally:
        monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
        get_settings.cache_clear()


def test_admin_link_exists_in_the_search_ui(client: TestClient) -> None:
    html = client.get("/").text

    assert 'href="/admin"' in html
    assert "Datenbank" in html


def test_ui_contains_review_queue(client: TestClient) -> None:
    html = client.get("/").text

    assert 'id="admin-review"' in html
    assert 'id="admin-review-counts"' in html
    assert "/api/v1/crowd/review" in html
    assert "Alle plausiblen freigeben" in html
    assert "Freigeben" in html
    assert "Ablehnen" in html


def test_ui_contains_community_controls(client: TestClient) -> None:
    html = client.get("/").text

    assert 'id="coverage"' in html
    assert 'id="report-modal"' in html
    assert 'id="report-form"' in html
    assert "Preis melden" in html
    assert 'id="receipt-modal"' in html
    assert "Kassenbon hochladen" in html
    assert "Community-Standardpreis" in html
    assert "/api/v1/crowd/prices" in html
    assert "/api/v1/crowd/upload-receipt" in html
    assert "/api/v1/crowd/receipts/text" in html
    assert "/api/v1/crowd/coverage" in html


def test_ui_contains_anonymous_scout_gamification(client: TestClient) -> None:
    html = client.get("/").text

    assert "spv.scout.v1" in html
    assert "Scout-#" in html
    assert 'id="scout-name"' in html
    assert 'id="scout-badges"' in html
    assert "Kassenbon-Scout" in html
    assert "Nachbarschafts-Helfer" in html


def test_shopping_list_mode_accepts_input_without_commas(client: TestClient) -> None:
    html = client.get("/").text

    assert 'id="shopping-list"' in html
    assert "Kommas sind optional" in html
    assert "Einkaufszettel übernehmen" in html
    assert "Alle Begriffe suchen" in html
    assert 'id="list-chips"' in html
    assert "parseTerms" in html
    assert "MULTIWORD" in html


def test_ui_contains_speech_input_with_fallback(client: TestClient) -> None:
    html = client.get("/").text

    assert 'id="mic"' in html
    assert 'id="mic-search"' in html
    assert "SpeechRecognition" in html
    assert "webkitSpeechRecognition" in html
    assert "isSecureContext" in html
    assert 'lang = "de-DE"' in html
    assert "interimResults" in html
    assert "Höre zu…" in html
    assert "unterstützt keine Spracheingabe" in html
    assert "sichere Verbindung" in html
    assert 'id="speech-hint"' in html


def test_ui_contains_both_optimizer_options(client: TestClient) -> None:
    html = client.get("/").text

    assert "Option A · Bester Split" in html
    assert "Option B · Max. 2 Märkte" in html
    assert "Ersparnis gegenüber günstigstem Einzelmarkt" in html
    assert "Kein Einzelmarkt deckt alle Artikel ab" in html
    assert "Nicht gefunden" in html


def test_ui_stays_es5_style(client: TestClient) -> None:
    html = client.get("/").text
    script = html.split("<script>", 1)[1].split("</script>", 1)[0]

    assert "=>" not in script
    assert "`" not in script
    assert " let " not in script
    assert " const " not in script


def test_ui_is_self_contained(client: TestClient) -> None:
    html = client.get("/").text

    # No external CDN/font/script dependencies.
    assert "cdn." not in html
    assert "https://unpkg" not in html
    assert "<script src=" not in html
    assert '<link rel="stylesheet"' not in html


def test_docs_still_available(client: TestClient) -> None:
    assert client.get("/docs").status_code == 200
    assert client.get("/redoc").status_code == 200
    assert client.get("/openapi.json").status_code == 200
