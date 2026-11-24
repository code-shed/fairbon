"""Legal information pages.

All operator details come from environment variables only — no personal
data is ever stored in the public repository. Both pages carry a permanent
``noindex`` directive, independently of ``STEALTH_MODE``.
"""

from __future__ import annotations

from html import escape
from typing import Final

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from ...config import get_settings

router = APIRouter(tags=["system"])

NOINDEX_META: Final = '<meta name="robots" content="noindex, nofollow">'
HEADERS: Final = {
    "X-Robots-Tag": "noindex, nofollow",
    "Cache-Control": "no-cache",
}

_PROVIDER_LABELS: Final = {
    "gemini": "Google Gemini",
    "mistral": "Mistral AI",
    "opencode": "OpenCode Go",
    "opencode_zen": "OpenCode Zen",
    "openai_compatible": "ein lokaler OpenAI-kompatibler Endpunkt",
}


def _esc(value: object) -> str:
    """Escape every configuration value before it enters the HTML."""

    return escape(str(value or "").strip(), quote=True)


def _address_lines(value: str) -> list[str]:
    raw = str(value or "").replace("\r\n", "\n").replace("|", "\n")
    return [_esc(line) for line in raw.splitlines() if line.strip()]


def _vision_provider_name() -> str:
    """Human-readable provider name — never a raw developer identifier."""

    settings = get_settings()
    configured = (settings.privacy_vision_provider or "").strip()
    known = {
        "gemini": "Google Gemini API",
        "mistral": "Mistral AI API",
    }
    if configured.lower() in known:
        return known[configured.lower()]
    if configured:
        return _esc(configured)
    names: list[str] = []
    for provider in (
        settings.vision_primary_provider,
        settings.vision_fallback_provider,
    ):
        label = known.get((provider or "").strip().lower())
        if label and label not in names:
            names.append(label)
    if names:
        return " und ".join(names)
    return "den vom Instanz-Betreiber konfigurierten Vision-API-Anbieter"


def _operator() -> str:
    settings = get_settings()
    name = _esc(settings.imprint_name)
    address = _address_lines(settings.imprint_address)
    if not name or not address:
        return (
            "<p>Private Test- oder selbstgehostete FairBon-Instanz – es wurden "
            "keine öffentlichen Betreiberdaten in der Konfiguration hinterlegt.</p>"
        )
    parts = [f"<dt>Name</dt><dd>{name}</dd>"]
    if settings.imprint_co:
        parts.append(f"<dt>c/o</dt><dd>{_esc(settings.imprint_co)}</dd>")
    parts.append("<dt>Anschrift</dt><dd>" + "<br>".join(address) + "</dd>")
    if settings.imprint_email:
        email = _esc(settings.imprint_email)
        parts.append(
            f'<dt>E-Mail</dt><dd><a href="mailto:{email}">{email}</a></dd>'
        )
    if settings.imprint_phone:
        parts.append(f"<dt>Telefon</dt><dd>{_esc(settings.imprint_phone)}</dd>")
    return "<dl>" + "".join(parts) + "</dl>"


def _contact_email() -> str:
    settings = get_settings()
    email = settings.privacy_contact_email or settings.imprint_email
    return _esc(email)


def _page(title: str, body: str) -> HTMLResponse:
    html = f"""<!DOCTYPE html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  {NOINDEX_META}
  <title>{escape(title)} · FairBon</title>
  <link rel="stylesheet" href="./css/styles.css">
  <script src="./js/legal-theme.js"></script>
</head>
<body>
  <main class="legal-page">
    <a class="legal-back" href="./">← Zurück zu FairBon</a>
    {body}
    <nav class="legal-links" aria-label="Rechtliches">
      <a href="./impressum">Impressum</a> · <a href="./datenschutz">Datenschutz</a>
    </nav>
  </main>
</body>
</html>"""
    return HTMLResponse(content=html, headers=HEADERS)


@router.get("/impressum", include_in_schema=False)
async def impressum() -> HTMLResponse:
    body = f"""
    <h1>Impressum</h1>
    <h2>Angaben gemäß § 5 DDG</h2>
    {_operator()}
    <h2>Projekt, Lizenz &amp; Unabhängigkeit</h2>
    <p>FairBon ist Open Source unter der Lizenz AGPL-3.0. Der Quellcode ist
      unter <a href="https://github.com/code-shed/fairbon">github.com/code-shed/fairbon</a>
      verfügbar.</p>
    <p>FairBon ist ein unabhängiges Open-Source-Projekt und steht in keiner
      Verbindung zu den genannten Supermärkten, Discountern oder Drogerien.
      Alle Preis- und Produktangaben ohne Gewähr.</p>
    <p>Details zur Verarbeitung personenbezogener Daten findest du in der
      <a href="./datenschutz">Datenschutzerklärung</a>.</p>
    """
    return _page("Impressum", body)


@router.get("/datenschutz", include_in_schema=False)
async def datenschutz() -> HTMLResponse:
    settings = get_settings()
    if settings.privacy_hoster:
        hoster = (
            f"Diese Instanz wird technisch von {_esc(settings.privacy_hoster)} "
            "gehostet; soweit zutreffend erfolgt die Auftragsverarbeitung "
            "gemäß Art. 28 DSGVO."
        )
    else:
        hoster = "Diese Instanz wird von der jeweils verantwortlichen Person gehostet."

    retention = _esc(settings.privacy_log_retention)
    vision = _vision_provider_name()
    if settings.privacy_vision_provider_details:
        vision_details = (
            "Angaben des Anbieters: "
            + _esc(settings.privacy_vision_provider_details)
            + "."
        )
    else:
        vision_details = (
            "Verarbeitungsland, etwaige Drittlandübermittlungen und "
            "Speicherfristen richten sich nach den Bedingungen des jeweils "
            "eingesetzten Anbieters."
        )
    contact = _contact_email()
    contact_html = (
        f'<a href="mailto:{contact}">{contact}</a>'
        if contact
        else "die im Impressum genannten Kontaktdaten"
    )
    if settings.require_community_sharing:
        sharing = (
            "Bei aktiver kostenloser Nutzung ohne eigenen API-Key sind "
            "anonymisierte Preise automatisch Bestandteil des Angebots; "
            "Rechtsgrundlage ist Art. 6 Abs. 1 lit. b bzw. lit. f DSGVO "
            "(Vertragserfüllung bzw. berechtigtes Interesse an einem "
            "offenen, kostenlosen Preisvergleich)."
        )
    else:
        sharing = (
            "Das Teilen ist vollständig freiwillig und erfolgt ausschließlich "
            "nach ausdrücklichem Opt-in; Rechtsgrundlage ist Art. 6 Abs. 1 "
            "lit. a DSGVO (Einwilligung)."
        )
    turnstile = ""
    if settings.turnstile_site_key:
        turnstile = """
    <h2>Cloudflare Turnstile (nur auf dieser Instanz aktiv)</h2>
    <p>Zum Schutz vor Bot-Missbrauch wird beim Scannen Cloudflare Turnstile
      eingesetzt. Dabei werden technische Verbindungsdaten (u. a. IP-Adresse
      und Browserkennung) an Cloudflare übertragen; Rechtsgrundlage ist
      Art. 6 Abs. 1 lit. f DSGVO (Missbrauchsschutz). Es werden keine Werbe-
      oder Analyse-Cookies gesetzt.</p>
    """
    authority = ""
    if settings.privacy_supervisory_authority:
        authority = (
            "Zuständig ist insbesondere: "
            + _esc(settings.privacy_supervisory_authority)
            + "."
        )
    body = f"""
    <h1>Datenschutzerklärung</h1>
    <p>Informationen gemäß Art. 13 DSGVO. Diese Erklärung passt sich der
      Konfiguration dieser FairBon-Instanz an.</p>

    <h2>1. Verantwortlicher</h2>
    {_operator()}
    <p>Kontakt für Datenschutzanfragen: {contact_html}</p>

    <h2>2. Kein Account, kein Tracking, keine Werbe-Cookies</h2>
    <p>FairBon kommt ohne Registrierung, ohne Analyse- und Werbe-Cookies und
      ohne Nutzer-Tracking aus. Für die ausdrücklich gewünschte App-Funktion
      werden folgende Werte ausschließlich im <code>localStorage</code> deines
      Browsers gespeichert: der anonyme <code>owner_token</code> (Zuordnung der eigenen
      Bons ohne Benutzerkonto), die gewählte Postleitzahl, Merkliste und
      Einkaufszettel, das lokale Monatsbudget sowie Erscheinungsbild und
      weitere Einstellungen. Diese Speicherung ist technisch zwingend
      erforderlich und nach § 25 Abs. 2 Nr. 2 TDDDG zulässig – ein
      Tracking-/Einwilligungs-Cookie-Banner ist daher nicht erforderlich.</p>
    <p><strong>Optionaler eigener API-Key (BYOK):</strong> Hinterlegst du
      freiwillig einen eigenen Vision-API-Key, wird er ausschließlich in deinem
      Browser gespeichert und nur bei aktiv ausgelösten Foto-Scans als Request-
      Header (<code>X-User-Vision-Key</code>) an das Backend übergeben. Der
      Server speichert und protokolliert den Key nicht. Du kannst ihn jederzeit
      in den Einstellungen entfernen oder durch Löschen der Website-Daten
      deines Browsers. Verantwortung für Auswahl und Bedingungen des externen
      Anbieters trägst in diesem Fall du.</p>

    <h2>3. Hosting &amp; Server-Protokolle</h2>
    <p>{hoster}</p>
    <p>Beim Aufruf werden technische Zugriffsdaten verarbeitet: IP-Adresse,
      Zeitstempel, abgerufene URL, HTTP-Statuscode und User-Agent. Zweck ist
      die sichere Auslieferung der Web-App, Fehleranalyse sowie Missbrauchs-
      und DoS-Schutz (Rate-Limiting). Rechtsgrundlage ist Art. 6 Abs. 1
      lit. f DSGVO (berechtigtes Interesse an sicherem und stabilem Betrieb).
      Die Speicherdauer beträgt {retention}; danach werden die Daten
      automatisch gelöscht oder anonymisiert, sofern keine sicherheitsrelevante
      Aufklärung erforderlich ist.</p>

    <h2>4. Kassenbon-Erfassung &amp; KI-Verarbeitung</h2>
    <p><strong>eBon-PDF, Text und manuelle Eingabe:</strong> Diese Daten werden
      ausschließlich auf dem Server dieser Instanz ohne Weitergabe an externe
      KI-Anbieter verarbeitet (lokaler PDF-/Textparser).</p>
    <p><strong>Papier-Foto-Scan (optional):</strong> Das im Browser verkleinerte
      und in Graustufen umgewandelte Bild wird serverseitig im Arbeitsspeicher
      geprüft, von EXIF-/GPS-Metadaten befreit, zur Texterkennung an
      {vision} übermittelt und nach Abschluss der Auswertung verworfen (keine
      dauerhafte Speicherung des Belegfotos durch FairBon). Rechtsgrundlage ist
      Art. 6 Abs. 1 lit. b DSGVO (Durchführung der von dir aktiv ausgelösten
      Belegauswertung). Übermittelt wird das bereinigte Belegfoto. {vision_details}
      Zahlungs-, EC- und TSE-Daten sowie genaue Uhrzeiten werden nicht
      gespeichert.</p>

    <h2>5. Anonyme Community-Preise</h2>
    <p>Gespeichert werden ausschließlich Produktbezeichnung/EAN, Preis,
      Handelskette, PLZ-Region und Datum – ohne <code>owner_token</code>, ohne
      <code>receipt_id</code> (kein verknüpfter Gesamt-Warenkorb), ohne genaue
      Uhrzeit und ohne Zahlungsdaten. Erfasst werden nur die
      preisvergleichsrelevanten Kategorien Lebensmittel, Getränke, Drogerie und
      Haushalt, um Rückschlüsse auf einzelne Personen zu vermeiden. {sharing}</p>

    <h2>6. Externe Schnittstellen &amp; Quellen</h2>
    <p><strong>Serverseitige EAN-/Preisabfragen:</strong> Für Barcode-Abgleich
      und Community-Preise fragt der FairBon-Server Open Food Facts / Open
      Prices ab. Übermittelt werden EAN bzw. Suchbegriff sowie die IP-Adresse
      des Servers – nicht deine IP-Adresse.</p>
    <p><strong>Produktbilder:</strong> Werden Bilder direkt im Browser von Open
      Food Facts geladen, übermittelt der Browser technisch bedingt deine
      IP-Adresse und übliche Request-Daten. Zweck ist die Anzeige frei
      lizenzierter Produktbilder, Rechtsgrundlage Art. 6 Abs. 1 lit. f DSGVO.
      Die Daten stehen unter der ODbL-Lizenz; ein Quellenhinweis erscheint bei
      den Produktangaben.</p>
    {turnstile}

    <h2>7. Deine Rechte</h2>
    <p>Du hast das Recht auf Auskunft, Berichtigung, Löschung, Einschränkung
      der Verarbeitung, Widerspruch und Datenübertragbarkeit. Richte deine
      Anfrage bitte an {contact_html}. Da FairBon ohne Benutzerkonten arbeitet,
      kannst du eigene Belege und lokal gespeicherte Daten jederzeit direkt in
      der App löschen oder exportieren. Für Anfragen an den Betreiber wird
      ggf. dein eigener anonymer <code>owner_token</code> benötigt. Bereits
      anonymisierte Community-Einzelpreise lassen sich mangels Personenbezug
      nachträglich keiner einzelnen Person mehr zuordnen (Art. 11 DSGVO).</p>
    <p>Du hast das Recht, dich bei einer Datenschutz-Aufsichtsbehörde zu
      beschweren (Art. 77 DSGVO) – insbesondere an deinem gewöhnlichen
      Aufenthaltsort, deinem Arbeitsplatz oder am Sitz des Verantwortlichen.
      {authority}</p>
    <p>Weitere Angaben findest du im <a href="./impressum">Impressum</a>.</p>
    """
    return _page("Datenschutz", body)
