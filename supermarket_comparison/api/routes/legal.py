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
    settings = get_settings()
    if settings.privacy_vision_provider:
        return _esc(settings.privacy_vision_provider)
    names: list[str] = []
    for provider in (
        settings.vision_primary_provider,
        settings.vision_fallback_provider,
    ):
        label = _PROVIDER_LABELS.get((provider or "").strip().lower(), provider)
        if label and label not in names:
            names.append(_esc(label))
    return " und ".join(names) if names else "ein konfigurierter Vision-Anbieter"


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
    hoster = _esc(settings.privacy_hoster or "der Betreiber dieser Instanz")
    vision = _vision_provider_name()
    contact = _contact_email()
    contact_html = (
        f'<a href="mailto:{contact}">{contact}</a>'
        if contact
        else "die im Impressum genannten Kontaktdaten"
    )
    sharing = (
        "Bei aktiver kostenloser Nutzung ohne eigenen API-Key sind anonymisierte "
        "Preise automatisch Bestandteil des Angebots."
        if settings.require_community_sharing
        else "Das Teilen ist vollständig freiwillig (Opt-in) und erfolgt nur, "
        "wenn du es ausdrücklich aktivierst."
    )
    turnstile = ""
    if settings.turnstile_site_key:
        turnstile = """
    <h2>Cloudflare Turnstile</h2>
    <p>Zum Schutz vor Bot-Missbrauch wird beim Scannen Cloudflare Turnstile
      eingesetzt. Dabei werden technische Verbindungsdaten an Cloudflare
      übertragen. Es werden keine Werbe- oder Analyse-Cookies gesetzt.</p>
    """
    body = f"""
    <h1>Datenschutzerklärung</h1>
    <p>Informationen gemäß Art. 13 DSGVO. Diese Erklärung passt sich der
      Konfiguration dieser FairBon-Instanz an.</p>

    <h2>1. Verantwortlicher</h2>
    {_operator()}
    <p>Kontakt: {contact_html}</p>

    <h2>2. Kein Account, kein Tracking, keine Werbe-Cookies</h2>
    <p>FairBon kommt ohne Registrierung, ohne Analyse- und Werbe-Cookies und
      ohne Nutzer-Tracking aus. Folgende Daten liegen ausschließlich lokal in
      deinem Browser (localStorage) und sind technisch notwendig, damit die App
      funktioniert: der anonyme Gast-Token (Zugriff auf deine Bons), Budget und
      Budgetbeginn, Merkliste, Postleitzahl, Darstellungs-Einstellungen sowie –
      falls du ihn selbst hinterlegst – dein eigener Vision-API-Key. Diese
      Speicherung ist nach § 25 Abs. 2 Nr. 2 TDDDG zulässig; ein Cookie-Banner
      ist daher nicht erforderlich.</p>

    <h2>3. Hosting &amp; Server-Protokolle</h2>
    <p>Diese Instanz wird gehostet von {hoster}. Beim Aufruf der Website werden
      kurzzeitig technische Zugriffsdaten verarbeitet (u. a. IP-Adresse,
      Zeitpunkt, abgerufene Seite), um die Auslieferung zu ermöglichen und den
      Missbrauchs- sowie Rate-Limit-Schutz zu betreiben.</p>

    <h2>4. Kassenbon-Erfassung &amp; KI-Verarbeitung</h2>
    <p><strong>eBon-PDF, Text und manuelle Eingabe:</strong> Diese Daten werden
      zu 100 % lokal auf dem Server verarbeitet – ohne externe KI-API.</p>
    <p><strong>Papier-Foto-Scan (optional):</strong> Das Bild wird bereits im
      Browser verkleinert und in Graustufen umgewandelt. Serverseitig erfolgen
      Magic-Byte-Prüfung und Entfernung von EXIF-/GPS-Metadaten ausschließlich
      im Arbeitsspeicher. Anschließend wird das Bild kurzzeitig an
      {vision} übertragen (bei eigenem API-Key direkt über deinen Schlüssel)
      und sofort nach der Auswertung verworfen – ohne Speicherung auf der
      Festplatte. Zahlungs-, EC- und TSE-Daten sowie genaue Uhrzeiten werden
      nicht gespeichert.</p>

    <h2>5. Anonyme Community-Preise</h2>
    <p>Preise aus Supermärkten, Discountern und Drogerien (Kategorien
      Lebensmittel, Getränke, Drogerie, Haushalt) können in den offenen
      Preisvergleich fließen. Sie werden vollständig ohne owner_token, ohne
      receipt_id und ohne Personenbezug gespeichert. {sharing}</p>

    <h2>6. Externe Schnittstellen &amp; Quellen</h2>
    <p>Für den optionalen Barcode-/EAN-Abgleich und Produktbilder werden Open
      Food Facts / Open Prices genutzt (Daten unter ODbL-Lizenz; Quellenhinweis
      bei den Produktangaben). Diese Abfragen erfolgen nur, wenn du die
      entsprechenden Funktionen verwendest.</p>
    {turnstile}

    <h2>7. Deine Rechte</h2>
    <p>Du hast das Recht auf Auskunft, Berichtigung, Löschung, Einschränkung
      der Verarbeitung und Widerspruch. Eigene Bons und lokal gespeicherte Daten
      kannst du jederzeit direkt in der App löschen. Außerdem besteht ein
      Beschwerderecht bei einer zuständigen Datenschutzaufsichtsbehörde.</p>
    <p>Weitere Angaben findest du im <a href="./impressum">Impressum</a>.</p>
    """
    return _page("Datenschutz", body)
