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


def _phase_note() -> str:
    """Honest note about the current (test vs. public) operating phase."""

    settings = get_settings()
    if not settings.privacy_test_mode:
        return (
            '<section class="legal-phase">'
            "<p><strong>Betriebsphase:</strong> Regulärer Betrieb. Die Angaben "
            "zu Verantwortlichem und Dienstleistern richten sich nach den "
            "hinterlegten Konfigurationswerten.</p>"
            "</section>"
        )
    active = [
        (
            "Zugriff nur mit Passwort (privater Testkreis)"
            if settings.site_password
            else "Zugriff ohne Passwortschutz"
        ),
        "eBon-/PDF-/Textimport und manuelle Eingabe",
        (
            "Foto-Scan per Vision-Anbieter verfügbar"
            if settings.vision_primary_api_key or settings.vision_fallback_api_key
            else "Foto-Scan derzeit nicht konfiguriert"
        ),
        (
            "Community-Preise automatisch Teil des Angebots"
            if settings.require_community_sharing
            else "Community-Preise nur nach ausdrücklichem Opt-in"
        ),
    ]
    if settings.turnstile_site_key:
        active.append("Bot-Schutz (Turnstile) aktiv")
    if not (settings.imprint_name and settings.imprint_address):
        active.append("Keine öffentlichen Betreiberdaten hinterlegt")
    items = "".join(f"<li>{_esc(text)}</li>" for text in active)
    return (
        '<section class="legal-phase">'
        "<p><strong>Geschlossener Testbetrieb:</strong> Diese FairBon-Instanz "
        "befindet sich in einer privaten Test-/Betriebsphase. Aktuell aktiv "
        "sind:</p>"
        f"<ul>{items}</ul>"
        "</section>"
    )


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
    {_phase_note()}
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
    hoster_value = _esc(settings.privacy_hoster)
    if hoster_value:
        hoster = (
            f"<dt>Anbieter und Standort</dt><dd>{hoster_value}</dd>"
            "<dt>Rolle</dt><dd>Technischer Dienstleister bzw. "
            "Auftragsverarbeiter gemäß Art. 28 DSGVO, soweit ein "
            "entsprechender Vertrag besteht.</dd>"
        )
    else:
        hoster = (
            "<dt>Anbieter und Standort</dt><dd>Diese Instanz wird von der "
            "jeweils verantwortlichen Person gehostet.</dd>"
        )

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
    if settings.privacy_byok_reaches_server:
        byok_route = (
            "wird der Key bei aktiv ausgelösten Foto-Scans als Request-Header "
            "(<code>X-User-Vision-Key</code>) an den FairBon-Server übermittelt "
            "und von dort aus an den selbst gewählten Anbieter weitergeleitet. "
            "Der Key wird vom Server nicht dauerhaft gespeichert und nicht in "
            "Logs protokolliert."
        )
    else:
        byok_route = (
            "verbleibt der Key im Browser; die Anfrage geht für den Scan direkt "
            "an den selbst gewählten Anbieter, ohne den FairBon-Server zu "
            "durchlaufen."
        )
    contact = _contact_email()
    contact_html = (
        f'<a href="mailto:{contact}">{contact}</a>'
        if contact
        else "die im Impressum genannten Kontaktdaten"
    )
    if settings.require_community_sharing:
        sharing = (
            "Bei kostenloser Nutzung ohne eigenen API-Key sind anonymisierte "
            "Preise automatisch Bestandteil des Angebots; Rechtsgrundlage ist "
            "Art. 6 Abs. 1 lit. b bzw. lit. f DSGVO (Vertragserfüllung bzw. "
            "berechtigtes Interesse an einem offenen Preisvergleich). Künftiges "
            "Teilen kannst du beenden, indem du einen eigenen API-Key "
            "verwendest oder FairBon selbst hostest."
        )
    else:
        sharing = (
            "Das Teilen erfolgt ausschließlich nach ausdrücklichem Opt-in "
            "(Rechtsgrundlage Art. 6 Abs. 1 lit. a DSGVO) und lässt sich in den "
            "Einstellungen für künftige Bons jederzeit abschalten."
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
    storage = [
        (
            "Gast-Token",
            "zufällig erzeugter Gast-Token, der den Zugriff auf die "
            "zugehörigen Bons ermöglicht",
        ),
        ("Budget", "Monatsbudget und Beginn des Abrechnungszeitraums"),
        ("Merkliste", "Einkaufszettel und gemerkte Produkte"),
        ("Postleitzahl", "gewählte PLZ für den lokalen Preisvergleich"),
        (
            "Oberflächeneinstellungen",
            "Darstellung, Farbschema und weitere Einstellungen",
        ),
    ]
    storage_items = "".join(
        f"<li><strong>{_esc(label)}</strong>: {_esc(purpose)}</li>"
        for label, purpose in storage
    )
    body = f"""
    <h1>Datenschutzerklärung</h1>
    <p>Informationen gemäß Art. 13 DSGVO. Diese Erklärung beschreibt die
      Verarbeitungen dieser FairBon-Instanz auf Basis ihrer Konfiguration.</p>

    <h2>1. Verantwortlicher und Betriebsphase</h2>
    {_operator()}
    <p>Kontakt für Datenschutzanfragen: {contact_html}</p>
    <p>Ein Hosting-Dienstleister – etwa STRATO, sofern er für diese Instanz
      genutzt wird – ist technischer Dienstleister bzw. Auftragsverarbeiter
      und nicht der Verantwortliche für FairBon. Verantwortlich ist die oben
      genannte Person bzw. Organisation.</p>

    <h2>2. Kein Werbe- oder Analytics-Tracking</h2>
    <p>FairBon setzt keine Werbe- oder Analyse-Cookies und kein Tracking des
      Nutzerverhaltens ein. Technisch kommen dennoch Verbindungen zustande:
      zum Hosting-Server (Auslieferung und Zugriffsprotokolle), bei aktiv
      ausgelöstem Foto-Scan zum Vision-Anbieter sowie – wenn du diese
      Funktionen nutzt – zu Open Food Facts / Open Prices (Barcode-Abgleich
      und Produktbilder). Diese Vorgänge sind in den folgenden Abschnitten
      beschrieben.</p>

    <h2>3. Lokal im Browser gespeicherte Daten (§ 25 Abs. 2 Nr. 2 TDDDG)</h2>
    <p>Für die von dir gewünschten App-Funktionen liegen folgende Werte im
      <code>localStorage</code> deines Browsers:</p>
    <ul>{storage_items}</ul>
    <p>Die ersten vier Einträge sind erforderlich, damit deine Bons, Budgets
      und Merkliste ohne Benutzerkonto funktionieren; die
      Oberflächeneinstellungen sind freiwillig und jederzeit änderbar. Für
      diese technisch bedingte Speicherung ist kein Einwilligungs-Cookie-Banner
      erforderlich. Du kannst alle Einträge in den App-Einstellungen
      zurücksetzen oder vollständig über die Website-Daten deines Browsers
      löschen.</p>
    <p><strong>Eigener API-Key (BYOK):</strong> Hinterlegst du freiwillig einen
      eigenen Vision-API-Key, wird er ausschließlich in deinem Browser
      gespeichert. Bei einem Foto-Scan {byok_route} Du kannst den Key jederzeit
      in den Einstellungen entfernen oder durch Löschen der Website-Daten
      deines Browsers. Verantwortung für Auswahl und Bedingungen des externen
      Anbieters trägst in diesem Fall du.</p>

    <h2>4. Hosting und Zugriffsdaten</h2>
    <dl>{hoster}</dl>
    <p><strong>Erfasste Daten:</strong> IP-Adresse, Zeitstempel, abgerufene URL,
      HTTP-Statuscode und User-Agent.</p>
    <p><strong>Zweck:</strong> sichere Auslieferung der Web-App, Fehleranalyse
      sowie Missbrauchs- und DoS-Schutz (Rate-Limiting). <strong>Rechtsgrundlage:
      </strong>Art. 6 Abs. 1 lit. f DSGVO (berechtigtes Interesse an sicherem
      und stabilem Betrieb).</p>
    <p><strong>Speicherdauer:</strong> {retention}. Danach werden die Daten
      gelöscht oder anonymisiert, sofern keine sicherheitsrelevante Aufklärung
      erforderlich ist.</p>

    <h2>5. Kassenbon-Erfassung und KI-Verarbeitung</h2>
    <p><strong>eBon-PDF, Text und manuelle Eingabe:</strong> Diese Daten werden
      ausschließlich auf dem Server dieser Instanz verarbeitet (lokaler
      PDF-/Textparser) und ohne Weitergabe an eine externe KI-API ausgewertet.</p>
    <p><strong>Papier-Foto-Scan – Browser:</strong> Das Foto wird bereits in
      deinem Browser verkleinert und in Graustufen umgewandelt.</p>
    <p><strong>Papier-Foto-Scan – FairBon-Server:</strong> Die Bereinigung
      (Magic-Bytes-Prüfung, EXIF-/GPS-Entfernung) läuft im Arbeitsspeicher;
      bei lokaler OCR werden vorübergehend angelegte temporäre Arbeitsdateien
      nach der Texterkennung wieder gelöscht. Für die Auswertung wird das Bild
      an {vision} übermittelt; nach Abschluss der Antwort wird es verworfen.
      FairBon speichert das Belegfoto nicht dauerhaft. Rechtsgrundlage ist
      Art. 6 Abs. 1 lit. b
      DSGVO (Durchführung der von dir aktiv ausgelösten Belegauswertung).
      Zahlungs-, EC- und TSE-Daten sowie genaue Uhrzeiten werden nicht
      gespeichert.</p>
    <p><strong>Papier-Foto-Scan – KI-Anbieter:</strong> {vision_details} Für die
      Verarbeitung beim Anbieter gelten dessen eigene Bedingungen,
      Speicherfristen und Regeln zur Verwendung des Bildes für Modellzwecke.</p>

    <h2>6. Anonyme Community-Preise</h2>
    <p>Geteilt werden ausschließlich Produktbezeichnung/EAN, Preis,
      Handelskette, PLZ-Region und Datum – ohne <code>owner_token</code>, ohne
      <code>receipt_id</code> (kein verknüpfter Gesamt-Warenkorb), ohne genaue
      Uhrzeit des Kassenbons (gespeichert wird der technische
      Erfassungszeitpunkt ohne Personen- oder Belegbezug) und ohne
      Zahlungsdaten. Erfasst werden nur die
      preisvergleichsrelevanten Kategorien Lebensmittel, Getränke, Drogerie und
      Haushalt. {sharing}</p>
    <p>Bereits ohne Zuordnung zu einem Nutzerkonto oder Beleg gespeicherte
      Preisdaten können nachträglich in der Regel nicht mehr individuell
      gelöscht werden, da kein Personenbezug zu deinem Gast-Token besteht
      (Art. 11 DSGVO).</p>

    <h2>7. Externe Schnittstellen und Quellen</h2>
    <p><strong>Serverseitige EAN-/Preisabfragen:</strong> Für Barcode-Abgleich
      und Community-Preise fragt der FairBon-Server Open Food Facts / Open
      Prices ab. Übermittelt werden EAN bzw. Suchbegriff sowie die IP-Adresse
      des Servers – nicht deine IP-Adresse. Zweck ist die Anzeige vergleichbarer
      Produkt- und Preisinformationen, Rechtsgrundlage Art. 6 Abs. 1 lit. f
      DSGVO (berechtigtes Interesse an aktuellen Preisinformationen).</p>
    <p><strong>Produktbilder:</strong> Werden Bilder direkt im Browser von Open
      Food Facts geladen, übermittelt der Browser technisch bedingt deine
      IP-Adresse und übliche Request-Daten. Zweck ist die Anzeige frei
      lizenzierter Produktbilder, Rechtsgrundlage Art. 6 Abs. 1 lit. f DSGVO.
      Die Daten stehen unter der ODbL-Lizenz; ein Quellenhinweis erscheint bei
      den Produktangaben.</p>
    {turnstile}

    <h2>8. Deine Rechte</h2>
    <p>Du hast das Recht auf Auskunft, Berichtigung, Löschung, Einschränkung
      der Verarbeitung, Widerspruch und Datenübertragbarkeit. Richte deine
      Anfrage bitte an {contact_html}. Da FairBon ohne Benutzerkonten arbeitet,
      kannst du eigene Belege und lokal gespeicherte Daten jederzeit direkt in
      der App löschen oder exportieren. Für Anfragen an den Betreiber wird
      ggf. dein zufällig erzeugter Gast-Token, der den Zugriff auf die
      zugehörigen Bons ermöglicht, benötigt. Bereits anonymisierte
      Community-Einzelpreise lassen sich mangels Personenbezug nachträglich
      keiner einzelnen Person mehr zuordnen (Art. 11 DSGVO).</p>
    <p>Du hast das Recht, dich bei einer Datenschutz-Aufsichtsbehörde zu
      beschweren (Art. 77 DSGVO) – insbesondere an deinem gewöhnlichen
      Aufenthaltsort, deinem Arbeitsplatz oder am Sitz des Verantwortlichen.
      {authority}</p>
    <p>Weitere Angaben findest du im <a href="./impressum">Impressum</a>.</p>
    """
    return _page("Datenschutz", body)
