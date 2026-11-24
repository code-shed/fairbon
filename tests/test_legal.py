"""Legal pages: environment-only content and permanent noindex."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from supermarket_comparison.api.main import create_app
from supermarket_comparison.config import get_settings

LEGAL_KEYS = (
    "imprint_name",
    "imprint_co",
    "imprint_address",
    "imprint_email",
    "imprint_phone",
    "privacy_test_mode",
    "privacy_hoster",
    "privacy_vision_provider",
    "privacy_contact_email",
    "privacy_log_retention",
    "privacy_vision_provider_details",
    "privacy_byok_reaches_server",
    "privacy_supervisory_authority",
    "stealth_mode",
    "site_password",
    "turnstile_site_key",
    "require_community_sharing",
    "vision_primary_provider",
    "vision_fallback_provider",
    "max_global_scans_per_day",
)

DEFAULT_RETENTION = "in der Regel bis zu 7 Tage"


@pytest.fixture()
def settings_backup() -> Iterator[None]:
    settings = get_settings()
    previous = {key: getattr(settings, key) for key in LEGAL_KEYS}
    for key in LEGAL_KEYS:
        default = "" if isinstance(previous[key], str) else False
        object.__setattr__(settings, key, default)
    object.__setattr__(settings, "stealth_mode", False)
    object.__setattr__(settings, "site_password", None)
    object.__setattr__(settings, "privacy_test_mode", True)
    object.__setattr__(settings, "privacy_byok_reaches_server", True)
    object.__setattr__(settings, "privacy_log_retention", DEFAULT_RETENTION)
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
        assert "./css/styles.css" in response.text
        assert 'src="./js/legal-theme.js"' in response.text
        assert "<script>" not in response.text  # no inline scripts (CSP)
        assert "Geschlossener Testbetrieb" in response.text

    privacy = client.get("/datenschutz").text
    neutral_hoster = "Diese Instanz wird von der jeweils verantwortlichen Person"
    assert neutral_hoster in privacy
    assert DEFAULT_RETENTION in privacy


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
    object.__setattr__(settings, "privacy_log_retention", "<script>alert(2)</script>")
    object.__setattr__(
        settings,
        "privacy_vision_provider_details",
        '<img src=x onerror="alert(3)"> Anbieter & Co.',
    )
    object.__setattr__(
        settings, "privacy_supervisory_authority", "<b>Behörde</b> & Co."
    )

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
    assert "Art. 28 DSGVO" in privacy  # named hoster = technical service provider
    assert "kontakt@example.test" in privacy
    for raw, escaped in (
        ("<script>alert(2)</script>", "&lt;script&gt;alert(2)&lt;/script&gt;"),
        (
            '<img src=x onerror="alert(3)"> Anbieter & Co.',
            "&lt;img src=x onerror=&quot;alert(3)&quot;&gt; Anbieter &amp; Co.",
        ),
        ("<b>Behörde</b> & Co.", "&lt;b&gt;Behörde&lt;/b&gt; &amp; Co."),
    ):
        assert raw not in privacy
        assert escaped in privacy


def test_optional_sections_follow_configuration(client: TestClient) -> None:
    settings = get_settings()
    object.__setattr__(settings, "turnstile_site_key", "")
    object.__setattr__(settings, "require_community_sharing", False)
    text = client.get("/datenschutz").text
    assert "Cloudflare Turnstile" not in text
    assert "ausschließlich nach ausdrücklichem Opt-in" in text
    assert "Art. 6 Abs. 1 lit. a DSGVO" in text
    assert "jederzeit abschalten" in text

    object.__setattr__(settings, "turnstile_site_key", "site-key")
    object.__setattr__(settings, "require_community_sharing", True)
    text = client.get("/datenschutz").text
    assert "Cloudflare Turnstile" in text
    assert "automatisch Bestandteil" in text
    assert "Art. 6 Abs. 1 lit. b bzw. lit. f DSGVO" in text

    # Known provider keys are mapped to human-readable names.
    object.__setattr__(settings, "vision_primary_provider", "gemini")
    object.__setattr__(settings, "vision_fallback_provider", "mistral")
    assert "Google Gemini API und Mistral AI API" in client.get("/datenschutz").text
    object.__setattr__(settings, "privacy_vision_provider", "mistral")
    assert "Mistral AI API" in client.get("/datenschutz").text

    # An explicit authority is rendered; otherwise only the general Art. 77
    # hint appears.
    authority = "Landesbeauftragte für Datenschutz Musterland"
    object.__setattr__(settings, "privacy_supervisory_authority", authority)
    assert authority in client.get("/datenschutz").text


def test_unknown_provider_stays_neutral(client: TestClient) -> None:
    settings = get_settings()
    object.__setattr__(settings, "vision_primary_provider", "opencode")
    object.__setattr__(settings, "vision_fallback_provider", "mimo-v2.6-flash")
    text = client.get("/datenschutz").text
    assert "den vom Instanz-Betreiber konfigurierten Vision-API-Anbieter" in text
    assert "OpenCode" not in text
    assert "opencode" not in text
    assert "mimo-v2.6-flash" not in text

    # Fallback wording when no provider details are configured.
    assert "Verarbeitungsland, etwaige Drittlandübermittlungen" in text


def test_privacy_legal_bases_and_concrete_fields(client: TestClient) -> None:
    text = " ".join(client.get("/datenschutz").text.split())

    # Legal bases and storage mechanics.
    for phrase in (
        "§ 25 Abs. 2 Nr. 2 TDDDG",
        "Art. 6 Abs. 1",
        "Art. 11 DSGVO",
        "Art. 77 DSGVO",
        "X-User-Vision-Key",
        "Der Key wird vom Server nicht dauerhaft gespeichert",
        "zufällig erzeugter Gast-Token, der den Zugriff auf die "
        "zugehörigen Bons ermöglicht",
        "Kein Werbe- oder Analytics-Tracking",
        "Oberflächeneinstellungen",
        "durch Löschen der Website-Daten deines Browsers",
        "Anbieter und Standort",
        "Auftragsverarbeiter",
        "STRATO",
        "Speicherdauer",
        "nicht mehr individuell gelöscht",
        "Produktbezeichnung/EAN",
        "ohne <code>receipt_id</code>",
        "PLZ-Region",
        "ohne genaue Uhrzeit",
    ):
        assert phrase in text, phrase

    # Server-side vs. browser-side Open Food Facts access is distinguished.
    assert "IP-Adresse des Servers" in text
    assert "nicht deine IP-Adresse" in text
    assert "deine IP-Adresse und übliche Request-Daten" in text
    assert "ODbL-Lizenz" in text

    # Data subject rights, contact route and supervisory authority.
    for phrase in (
        "Datenübertragbarkeit",
        "Widerspruch",
        "Anfrage bitte an",
        "gewöhnlichen Aufenthaltsort",
        "Arbeitsplatz",
        "Sitz des Verantwortlichen",
        "löschen oder exportieren",
    ):
        assert phrase in text, phrase


def test_no_absolute_or_raw_developer_claims(client: TestClient) -> None:
    text = " ".join(client.get("/datenschutz").text.split())
    for phrase in (
        "100 % lokal",
        "niemals auf der Festplatte",
        "sofort verworfen",
        "OpenCode Go",
        "glm-5.3-flash",
    ):
        assert phrase not in text, phrase
    assert "ausschließlich auf dem Server dieser Instanz" in text
    assert "FairBon speichert das Belegfoto nicht dauerhaft" in text


def test_no_outdated_legal_terms(client: TestClient) -> None:
    for path in ("/impressum", "/datenschutz"):
        text = client.get(path).text
        assert "§ 5 TMG" not in text
        assert "ec.europa.eu/consumers/odr" not in text
        assert "§ 5 DDG" in text or "Datenschutzerklärung" in text


def test_phase_note_follows_privacy_test_mode(client: TestClient) -> None:
    settings = get_settings()
    for path in ("/impressum", "/datenschutz"):
        text = " ".join(client.get(path).text.split())
        assert "Geschlossener Testbetrieb" in text
        assert "eBon-/PDF-/Textimport und manuelle Eingabe" in text

    object.__setattr__(settings, "site_password", "test-pass")
    object.__setattr__(settings, "vision_primary_api_key", "dummy")
    auth = ("x", "test-pass")
    text = " ".join(client.get("/datenschutz", auth=auth).text.split())
    assert "Zugriff nur mit Passwort (privater Testkreis)" in text
    assert "Foto-Scan per Vision-Anbieter verfügbar" in text
    assert "Keine öffentlichen Betreiberdaten hinterlegt" in text

    object.__setattr__(settings, "privacy_test_mode", False)
    text = " ".join(client.get("/datenschutz", auth=auth).text.split())
    assert "Regulärer Betrieb" in text
    assert "Geschlossener Testbetrieb" not in text


def test_byok_route_follows_configuration(client: TestClient) -> None:
    settings = get_settings()
    text = " ".join(client.get("/datenschutz").text.split())
    assert "an den FairBon-Server übermittelt" in text
    assert "von dort aus an den selbst gewählten Anbieter weitergeleitet" in text

    object.__setattr__(settings, "privacy_byok_reaches_server", False)
    text = " ".join(client.get("/datenschutz").text.split())
    assert "ohne den FairBon-Server zu durchlaufen" in text
    assert "als Request-Header" not in text


def test_tracking_section_is_factual(client: TestClient) -> None:
    text = " ".join(client.get("/datenschutz").text.split())
    assert "kein Tracking des Nutzerverhaltens" in text
    assert "Kein Werbe- oder Analytics-Tracking" in text
    for phrase in (
        "keine externen Verbindungen",
        "ohne jegliche Datenübertragung",
        "absolut keine Speicherung",
    ):
        assert phrase not in text
