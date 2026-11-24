"""Legal pages: environment-only content and permanent noindex."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from supermarket_comparison.api.main import create_app
from supermarket_comparison.config import get_settings

LEGAL_KEYS = (
    "imprint_name", "imprint_co", "imprint_address", "imprint_email",
    "imprint_phone", "privacy_hoster", "privacy_vision_provider",
    "privacy_contact_email", "stealth_mode",
    "site_password",
    "turnstile_site_key", "require_community_sharing",
    "vision_primary_provider", "vision_fallback_provider",
)


@pytest.fixture()
def settings_backup() -> Iterator[None]:
    settings = get_settings()
    previous = {key: getattr(settings, key) for key in LEGAL_KEYS}
    for key in LEGAL_KEYS:
        default = "" if isinstance(previous[key], str) else False
        object.__setattr__(settings, key, default)
    object.__setattr__(settings, "stealth_mode", False)
    object.__setattr__(settings, "site_password", None)
    object.__setattr__(settings, "max_global_scans_per_day", 500)
    yield
    for key, value in previous.items():
        object.__setattr__(settings, key, value)


@pytest.fixture()
def client(settings_backup: None) -> Iterator[TestClient]:
    with TestClient(create_app()) as test_client:
        yield test_client


def test_legal_pages_load_with_neutral_placeholder(client: TestClient) -> None:
    for path in ("/impressum", "/datenschutz"):
        response = client.get(path)
        assert response.status_code == 200
        assert "Private Test- oder selbstgehostete FairBon-Instanz" in response.text
        assert "← Zurück zu FairBon" in response.text
        assert './css/styles.css' in response.text
        assert 'src="./js/legal-theme.js"' in response.text
        assert "<script>" not in response.text  # no inline scripts (CSP)


def test_noindex_is_permanent_without_stealth_mode(client: TestClient) -> None:
    settings = get_settings()
    object.__setattr__(settings, "stealth_mode", False)

    for path in ("/impressum", "/datenschutz"):
        response = client.get(path)
        assert response.status_code == 200
        assert '<meta name="robots" content="noindex, nofollow">' in response.text
        assert response.headers["x-robots-tag"] == "noindex, nofollow"
        assert "noarchive" not in response.headers["x-robots-tag"]

    robots = client.get("/robots.txt").text
    assert "Allow: /" in robots
    assert "Disallow: /impressum" not in robots
    assert "Disallow: /datenschutz" not in robots


def test_env_values_are_escaped_and_optional_fields_conditionally_rendered(
    client: TestClient,
) -> None:
    settings = get_settings()
    object.__setattr__(settings, "imprint_name", "<script>alert(1)</script>")
    object.__setattr__(settings, "imprint_co", "c/o Muster-Impressumsservice")
    object.__setattr__(
        settings, "imprint_address", "Musterstraße 1 | 12345 Musterstadt"
    )
    object.__setattr__(settings, "imprint_email", "kontakt@example.test")
    object.__setattr__(settings, "imprint_phone", "+49 123 456789")
    object.__setattr__(settings, "privacy_hoster", "Hoster &amp; Co. KG")

    html = client.get("/impressum").text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "<script>alert(1)</script>" not in html
    assert "c/o Muster-Impressumsservice" in html
    assert "Musterstraße 1<br>12345 Musterstadt" in html
    assert 'href="mailto:kontakt@example.test"' in html
    assert "+49 123 456789" in html
    assert "Private Test- oder selbstgehostete" not in html

    privacy = client.get("/datenschutz").text
    assert "Hoster &amp;amp; Co. KG" in privacy
    assert "kontakt@example.test" in privacy


def test_optional_sections_follow_configuration(client: TestClient) -> None:
    settings = get_settings()
    object.__setattr__(settings, "turnstile_site_key", "")
    object.__setattr__(settings, "require_community_sharing", False)
    assert "Cloudflare Turnstile" not in client.get("/datenschutz").text
    assert "vollständig freiwillig" in client.get("/datenschutz").text

    object.__setattr__(settings, "turnstile_site_key", "site-key")
    object.__setattr__(settings, "require_community_sharing", True)
    text = client.get("/datenschutz").text
    assert "Cloudflare Turnstile" in text
    assert "automatisch Bestandteil" in text

    object.__setattr__(settings, "vision_primary_provider", "gemini")
    object.__setattr__(settings, "vision_fallback_provider", "mistral")
    assert "Google Gemini und Mistral AI" in client.get("/datenschutz").text


def test_no_outdated_legal_terms(client: TestClient) -> None:
    for path in ("/impressum", "/datenschutz"):
        text = client.get(path).text
        assert "§ 5 TMG" not in text
        assert "ec.europa.eu/consumers/odr" not in text
        assert "§ 5 DDG" in text or "Datenschutzerklärung" in text
