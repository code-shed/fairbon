> **Archived:** historical German task log (pre-V1.0). Kept for reference; active docs are in English.

# Projekt-Aufgaben & Meilensteine

## Iteration 3 — Standardsortiment, Historie & Datenbank

- [x] **Milestone 9: Standardpreise, Persistenz und Preisverlauf**
  - [x] `services/standard_prices.py`: OFF-Katalog (`search.openfoodfacts.org`) → EAN → Open Prices, Filter auf `location.osm_address_country_code = DE`, Bevorzugung der PLZ-Region (`osm_address_postcode`), 1 Beobachtung pro Markt.
  - [x] Es werden ausschließlich **beobachtete** Preise ausgegeben (`offer_type="standard"`, `source="openprices"`); Katalogtreffer ohne Preis werden verworfen — keine Schätzungen.
  - [x] `NormalizedProduct` erweitert: `offer_type`, `source`, `leaflet_url`, `postal_code`, Property `is_standard_price`.
  - [x] Marktguru liefert `leaflet_url` (`https://www.marktguru.de/offers/{id}`, live 200) und `source="marktguru"`.
  - [x] SQLite-Schicht `storage/` (Schema v3): `products` (EAN- bzw. Text-Hash-Identität), `price_points`, `price_history`, `search_events`, `search_trends`.
  - [x] Preishistorie wird nur bei echter Preisänderung geschrieben (idempotente Wiederholungssuchen).
  - [x] Suchanfragen anonymisiert (normalisierter Begriff, PLZ, Trefferzahl, Zeitstempel — keine IP/Session/UA) und tagesweise aggregiert.
  - [x] Aggregator persistiert Suchergebnisse und -ereignisse best-effort (DB-Fehler brechen keine Suche ab).
  - [x] Neue Endpunkte: `GET /api/v1/products/history`, `GET /api/v1/stats/trends`, `GET /api/v1/stats/summary`.
  - [x] `include_standard` / `offers_only` in Suche und Basket; Limit von 100 auf **1000** erhöht (Marktguru-Paging über `offset`, 100 Zeilen je Seite).
  - [x] Standardpreise erhalten bei kleinem Limit garantierte Slots (max. ¼ der Seite), damit sie nicht hinter Prospektangeboten abgeschnitten werden.
  - [x] UI: Toggle „Gesamtes Sortiment inkl. Standardpreise", blaues Badge „Standardpreis · Dauersortiment", Erfassungsdatum, Deep-Link „Im Prospekt ansehen ↗".
  - [x] Tests: `tests/test_storage.py` (15), `tests/test_standard_prices.py` (9), `tests/test_history_api.py` (10), erweiterte UI-/API-Tests.
  - [x] `uv run pytest` – **364 passed**; `ruff check` und `ruff format --check` clean.

## Iteration 4 — UX-Bugfix: Mikrofon & kommalfreier Parser

- [x] **Milestone 10: Spracheingabe abgesichert, Listen-Parser ohne Komma-Zwang**
  - [x] `normalization/terms.py`: `split_terms()` entfernt Füllwörter („ich brauche", „bitte", „noch" …), schützt mehrteilige Produktnamen („Coca Cola", „Gut und Günstig") und trennt an Komma, Semikolon, Zeilenumbruch, `und`/`sowie`/`plus`/`&`/`+`/`/`.
  - [x] Ohne Trennzeichen greift eine deutsche Substantiv-Heuristik: `"Nutella Butter Milch"` → 3 Begriffe, `"rote Linsen"` bleibt zusammen, komplett klein geschriebene Diktate werden wortweise getrennt.
  - [x] `POST /api/v1/basket/parse` (Server-Parser) und `text` als Alternative zu `items` in `POST /api/v1/basket/optimize`.
  - [x] Frontend `parseTerms()` spiegelt die Python-Regeln 1:1; Parität mit 25 Fällen automatisiert geprüft.
  - [x] Chips-Vorschau unter dem Einkaufszettel („3 Begriffe erkannt: …"), Aktualisierung bei jeder Eingabe.
  - [x] Mehrbegriff-Suche direkt im Suchfeld („Butter Milch" → zwei Ergebnisgruppen).
  - [x] Optimierer fällt auf den Einkaufszettel zurück, wenn die Merkliste leer ist.
  - [x] Zwei Mikrofon-Buttons (`#mic-search` im Suchfeld, `#mic` am Zettel) mit gemeinsamer Diktier-Logik.
  - [x] Verfügbarkeitsprüfung (`isSecureContext`, `SpeechRecognition`/`webkitSpeechRecognition`) mit sichtbarem Hinweis und deaktivierten Buttons statt stillem Fehlschlag.
  - [x] Zuhören-Zustand: rote Puls-Animation, `aria-pressed`, Labelwechsel; Transkript landet direkt im Zielfeld, bei mehreren Begriffen werden sie als Chips/Suche übernommen.
  - [x] Fehlercodes (`not-allowed`, `service-not-allowed`, `no-speech`, `audio-capture`, `network`) mit verständlichen deutschen Meldungen.
  - [x] Tests: `tests/test_terms.py` (21), UI-Tests erweitert; `uv run pytest` – **386 passed**, `ruff` clean.

## Iteration 15 — Markt-Ausbau: Rossmann, dm, Globus

- [x] **Milestone 39: Kuratierte Markt-Erweiterung**
  - [x] Rossmann als `RetailerScraper` über Marktguru (`scrapers/rossmann.py`, in `default_scrapers()`).
  - [x] dm und Globus über kaufDA; `SUPPORTED_STORES` filtert METRO, Denns, JYSK, MediaMarkt bewusst heraus (Preise nicht erreichbar bzw. kein Lebensmittel).
  - [x] `nahkauf` wird als Edeka-Banner auf `edeka` gemappt (Marktguru und kaufDA).
  - [x] UI-Store-Liste auf 10 Märkte erweitert (Badge-Farben, vorselektiert).
  - [x] Tests: Mapping (nahkauf→edeka), kaufDA-Filter (METRO/Denns/JYSK raus, Rossmann/dm/Globus rein), `default_scrapers()` enthält Rossmann, UI-Checkboxen für alle 10.
  - [x] `uv run pytest` – **629 passed**; `ruff` clean.
  - [x] Live: „shampoo" liefert dm und Rossmann, „butter" enthält Globus/dm, aber kein METRO.

## Iteration 14 — kaufDA-Fallback & Multi-Source-Deduplizierung

- [x] **Milestone 36: kaufDA-Provider**
  - [x] Live verifiziert: `GET https://www.kaufda.de/api/search?lat=&lng=&query=&limit=` liefert `searchResults.contents.offers[]` + `brochures[]`; PLZ-Geocoding über Nominatim (mit Cache).
  - [x] `services/kaufda.py`: `KaufdaProvider`, `parse_payload`, `canonical_retailer`, `parse_base_unit`, `drop_cross_source_duplicates`.
  - [x] Felder: Name, Marke, Preis (gerundet), Streichpreis, Menge/Einheit, Grundpreis, Kategorie, Gültigkeit, Prospektbild, Händlerseite; `source="kaufda"`.
  - [x] Händler-Mapping inkl. `E center`→edeka, `ALDI SÜD`→aldi, `Netto mit dem Scottie`→netto; unbekannte Ketten behalten einen Slug.
  - [x] Fehlerisolation: HTTP-/Geocoding-Fehler landen in `last_errors["kaufda"]`, die Suche läuft weiter.
- [x] **Milestone 37: Aggregation & Dedupe**
  - [x] kaufDA läuft parallel zum Marktguru-Fan-out; Store-Filter wird angewandt.
  - [x] Duplikate (Markt + normalisierter Name + Preis ±0,01 € + Gültigkeitstag) behalten den Marktguru-Eintrag.
  - [x] Harvester erbt die Quelle über `Aggregator.search`; Test bestätigt, dass kaufDA-Produkte gezählt werden.
- [x] **Milestone 38: Qualität**
  - [x] `tests/test_kaufda_provider.py` (31): Mapping, Grundpreis-Parsing, Feld-Mapping, Geocode-Cache, Fehler, Dedupe, Aggregator-Lücke/Filter/Ausfall, Harvester-Zählung.
  - [x] `uv run pytest` – **623 passed**; `ruff` clean.
  - [x] Live: „butter" PLZ 65618 liefert 13 kaufDA- + 7 Marktguru-Treffer, Bilder und Grundpreise inklusive, keine Fehler.

## Iteration 13 — QA-Werkzeuge für die Oberfläche

- [x] **Milestone 35: UI-QA in die Kette aufgenommen**
  - [x] `scripts/qa-ui.sh`: startet einen isolierten Server (temporäre DB, kein Passwort, Harvester aus), prüft `/` und `/admin` mit `detect`, lintet die Templates mit `check-draft-guard`, räumt per `trap` auf; Exit 0/1/2.
  - [x] Wrapper `spv-guard` und `spv-detect` in `~/.local/bin`, die die Skill-Skripte über `bun` aufrufen (funktionieren aus jedem Verzeichnis).
  - [x] `~/.bashrc` ergänzt `~/.local/bin` idempotent im `PATH` (behebt auch `uv: command not found`).
  - [x] README-Abschnitt „Development" um die UI-Prüfung und die Wrapper erweitert.
  - [x] Verifiziert: `./scripts/qa-ui.sh` → „sauber" (Exit 0), `spv-guard` aus `/tmp` → „2 file(s), clean".

## Iteration 12 — Admin-Datenbank & Inline-Bearbeitung

- [x] **Milestone 32: Admin-API**
  - [x] `GET /api/v1/admin/database/schema`: Tabellen, Spalten und editierbare Felder (Whitelist).
  - [x] `GET /api/v1/admin/database/records`: paginiert, Suche über Textspalten, Filter (`store`, `source`, `status`, `postal_code`), Sortierung, max. 100 Zeilen.
  - [x] `PUT /api/v1/admin/database/records/{table}/{id}`: nur erlaubte Felder, Typ-/Bereichsprüfung (Preis ≥ 0, Status-Enum), 422 bei Verstoß, 404 bei unbekannter ID.
  - [x] `DELETE /api/v1/admin/database/records/{table}/{id}`: hartes Löschen; Produkte kaskadieren auf Preispunkte/Historie.
  - [x] Kein SQL-Identifier aus Nutzereingaben: Tabellen/Spalten ausschließlich aus der Registry, Werte parametrisiert.
- [x] **Milestone 33: Admin-Oberfläche `/admin`**
  - [x] Eigenständige Seite im Projekt-Design (Tokens aus `DESIGN.md`), ES5, ohne externe Ressourcen.
  - [x] Tabellen-Tabs, Suche, Markt-/Status-Filter, Seitengröße, Pager.
  - [x] Bearbeiten-Dialog mit dynamischen Feldern, Speichern, Löschen mit Bestätigung, Toast „Eintrag erfolgreich aktualisiert ✓".
  - [x] Link „Datenbank öffnen" im bestehenden Admin-Modal.
  - [x] Geschützt durch die bestehende Passwort-Middleware (Browser → `/login?next=/admin`, API → 401 mit Basic-Auth-Challenge).
- [x] **Milestone 34: Qualität**
  - [x] `tests/test_admin_records.py` (13) und `tests/test_admin_api.py` (14): Auth 401/200, Pagination, Suche, Filter, Update/Delete, Typfehler, 404, Cascade, Admin-Seite.
  - [x] `uv run pytest` – **592 passed**; `ruff check`/`ruff format --check` clean.
  - [x] Live: 999,99-€-Meldung sichtbar in der Queue, Preis per API korrigiert, Löschung bestätigt, DOM-Test der Seite inkl. Toast.

## Iteration 11 — Plausibilitätsprüfung Community-Preise (Strict)

- [x] **Milestone 28: Validator & Warengruppen**
  - [x] `services/categories.py`: Keyword-Klassifikator (Kopfwort-Logik: „Kartoffelchips" → Süßes) + Grundpreis-Bänder je Warengruppe.
  - [x] `services/price_validator.py`: harte Grenzen (0,10–200 €), Warengruppen-Band, relativer Median ab n≥3 (1,8×/0,55×), deutsche Begründungen.
- [x] **Milestone 29: Statusmodell & Sichtbarkeit**
  - [x] Schema v8 (`review_reason`, `reviewed_at`, `reviewed_by`); `VISIBLE_STATUSES = {approved, verified}`.
  - [x] `pending`/`pending_review` unsichtbar in Median, Suche, Basket und Coverage; `rejected` wird nie wiederbelebt.
  - [x] Admin-Methoden `approve`, `reject`, `approve_all_pending`, `review_queue`, `review_counts`.
- [x] **Milestone 30: API & UI**
  - [x] Meldungen liefern `status` + `review_reason`; Kassenbon zählt `pending`/`pending_review` getrennt.
  - [x] Admin-Queue-API (Liste, Einzel-Freigabe, Ablehnung, Sammelfreigabe).
  - [x] Admin-Dialog: „Prüf-Queue" mit Zählern, Begründung, Freigeben/Ablehnen und „Alle plausiblen freigeben".
- [x] **Milestone 31: Qualität**
  - [x] Tests: `test_categories.py` (23), `test_price_validator.py` (12), `test_community_visibility.py` (9), `test_crowd_validation.py` (4), `test_crowd_review_api.py` (5), `test_community_basket.py` (3), `test_community_hardening.py` (12).
  - [x] `uv run pytest` – **563 passed**; `ruff` clean; Detect 0 Findings; Draft-Guard clean.
  - [x] Live: 999,99 € → `pending_review` (unsichtbar), plausibel → `pending` (unsichtbar), Sammelfreigabe → 1 sichtbar, Basket ignoriert die Anomalie.
  - [x] Review-Fix-Pass: Warengruppen-Band greift jetzt auch ohne `unit_price` (serverseitig abgeleitet), g/ml werden normalisiert, Sammelfreigabe revalidiert, `pending_review` ist admin-only, öffentliche Liste filtert, `approve` kann `rejected` nicht wiederbeleben.

## Iteration 10 — Bugfix: falsche Produktbilder & Müll-Marken

- [x] **Milestone 24: Marktguru-Originalbilder**
  - [x] Root Cause: Marktguru liefert im Such-JSON nur `images.count`; die Grafik liegt unter `https://cdn.marktguru.de/api/v1/offers/{id}/images/default/0/{size}.jpg` (live für Ginger, Cola, Käse, Butter geprüft).
  - [x] `OFFER_IMAGE_URL_TEMPLATE` + `image_url` in `parse_offer`, nur bei `images.count >= 1`.
  - [x] Leaflet-Quellen (`marktguru`, `lidl`, `rewe`, …) lösen **nie** eine OFF-Textsuche aus.

- [x] **Milestone 25: Strenger OFF-Filter**
  - [x] Namensmatch nur bei identischen produktdefinierenden Tokens (kein „XXL"→„XXL Nutrition", kein „Bio Ingwer"→„Bio Ingwer Shot").
  - [x] Marken müssen exakt übereinstimmen; Einheiten-Familie (kg/l) muss passen; loses Obst/Gemüse wird nie per Textsuche bebildert.
  - [x] EAN-Lookup bleibt erlaubt (autoritativ).

- [x] **Milestone 26: Marken- und DB-Bereinigung**
  - [x] `normalization/brands.py` filtert `thisisnobrand123`, `nobrand`, `none`, `null`, `unbekannt`, reine Zahlen; Modell-Validator + Frontend-Guard.
  - [x] Schema v7-Migration (`storage/cleanup.py`): Platzhaltermarken → `NULL`, OFF-Bilder ohne EAN → gelöscht, Obst/Gemüse-Bilder → gelöscht; zusätzlich `python -m supermarket_comparison.cli cleanup`.
  - [x] Bestehende `data/supermarkt.db` geprüft: 0 Müll-Marken, 0 unverifizierte OFF-Bilder, Schema 7.

- [x] **Milestone 27: Tests & Verifikation**
  - [x] `tests/test_image_fixes.py` (28 Tests): CDN-URL, exakte/abgelehnte Matches, Marken, Einheiten, Produkte, Migration.
  - [x] Live: „Bio Ingwer" (3×) und „Cola" liefern echte CDN-Bilder, Marke `null`, 0 Müll-Marken im DOM; Bildinhalte visuell geprüft.
  - [x] `uv run pytest` – **494 passed**; `ruff` clean; Detect 0 Findings; Draft-Guard clean.

## Iteration 9 — Bilder, 3×-Harvester, Backup & Cleanup

- [x] **Milestone 19: Spar-Rezepte entfernt**
  - [x] Frontend-Sektion, CSS und JS entfernt; `services/recipes.py` und `api/routes/recipes.py` gelöscht; Router-Wiring bereinigt.
  - [x] Testdatei auf `tests/test_share.py` reduziert: WhatsApp-/Clipboard-Formatierung bleibt vollständig getestet, plus 404-Test für die entfernten Rezept-Endpunkte.

- [x] **Milestone 20: Produktbilder & Fallbacks**
  - [x] Schema v6 mit `products.image_url` (+ idempotente Migration), Repository-API `set_product_image`/`image_for`.
  - [x] `services/image_resolver.py`: gespeicherte Bilder → OFF-Produkt-API per EAN → OFF-Suche per Name (Token-Match), Persistenz, TTL-Cache inkl. Negativ-Cache.
  - [x] `GET /api/v1/products/image`; Karten lösen fehlende Bilder nebenläufig (max. 3) nach.
  - [x] UI: 84-px-Medientile (`aspect-ratio 1/1`, `object-fit: contain`, `loading=lazy`, `referrerpolicy=no-referrer`), `onerror` → SVG-Kategorieplatzhalter (8 Kategorien + generisch).
  - [x] Detail-Modal mit großem Bild, Preis, Grundpreis und Prospekt-Link.

- [x] **Milestone 21: 3×/Woche-Harvester**
  - [x] `HARVEST_DAYS=mon,thu,sat`, `HARVEST_HOUR=4` (Legacy `HARVEST_CRON_*` bleibt lesbar).
  - [x] CronTrigger über alle Wochentage; Status-Endpoint zeigt den nächsten Lauf.

- [x] **Milestone 22: Backup & Restore**
  - [x] `GET /api/v1/system/backup-db` über `sqlite3.Connection.backup`, Download als `supermarkt-YYYY-MM-DD.db`.
  - [x] `POST /api/v1/system/restore-db` mit Header-/`integrity_check`-Validierung, Tabellenprüfung, automatischer `.bak`-Sicherung.
  - [x] Footer-Dialog „Admin": Download, Restore mit Bestätigung, Harvester-Status und manueller Trigger.

- [x] **Milestone 23: Deployment & QA**
  - [x] Dockerfile mit `pytesseract`/`pillow` (OCR-Build-Check), Compose mit `stop_grace_period` und Backup-Volume-Hinweis.
  - [x] `.env.example` auf `HARVEST_DAYS`/`HARVEST_HOUR` umgestellt; `DEPLOY_SERVER.md` für Hostinger VPS, Hetzner, Netcup, Strato inkl. 2-Minuten-Umzug.
  - [x] `uv run pytest` – **466 passed**; `ruff` clean; Detect 0 Findings; Draft-Guard clean.

## Iteration 8 — Harvester, Preisverlauf, Stealth & Deployment

- [x] **Milestone 14: Wochen-Harvester**
  - [x] `services/harvester.py` mit 100 Grundbegriffen, PLZ × Begriff, Fortschritt, Fehlerisolation, Lauf-Protokoll in `harvest_runs`.
  - [x] `cli.py` (`python -m supermarket_comparison.cli harvest`) mit `--zip`, `--limit`, `--terms`, `--json`.
  - [x] APScheduler im FastAPI-Lifespan (Montag 04:00 Europe/Berlin), degradiert ohne Paket.
  - [x] `GET /api/v1/system/harvest-status`, `POST /api/v1/system/harvest` (202).
  - [x] Live: CLI-Lauf mit 3 Begriffen → 10 Produkte, 10 Preispunkte, Status „ok"; Scheduler meldet `next_run` Montag 04:00.

- [x] **Milestone 15: Produkt-Detail & Preisverlauf**
  - [x] `GET /api/v1/products/price-insights` (Punkte, Tiefst-/Höchst-/Durchschnittspreis, Ampel, Märkte).
  - [x] Modal mit Zeitraum-Tabs (4W/3M/6M/1J/Max), SVG-Step-Chart, gestrichelter Durchschnittslinie, Tooltips, Kennzahlen-Kacheln und Ampel.
  - [x] Aufbau-Zustand bei 1–2 Messpunkten inkl. Hinweis „wird wöchentlich automatisch aktualisiert".
  - [x] Kartenklick und Produktname (Tastatur) öffnen das Modal; Escape/Backdrop schließen.

- [x] **Milestone 16: Stealth-Modus**
  - [x] `robots.txt` → `Disallow: /` bei `STEALTH_MODE`.
  - [x] Middleware setzt `X-Robots-Tag` und `<meta name="robots">`.
  - [x] Passwort-Gate (`SITE_PASSWORD`): Login-Seite mit signiertem Session-Cookie, Basic-Auth für API, `/health` öffentlich.
  - [x] Kurz-Aliase `STEALTH_MODE`, `SITE_PASSWORD`, `SESSION_SECRET`, `HARVEST_*` zusätzlich zu `SUPERMARKET_*`.

- [x] **Milestone 17: Hostinger-Paket**
  - [x] `Dockerfile` (python:3.12-slim, uv, tesseract-ocr-deu, non-root, Healthcheck).
  - [x] `docker-compose.yml` mit `./data:/app/data` und `restart: unless-stopped`.
  - [x] `.env.example`, `.dockerignore`, `DEPLOY_HOSTINGER.md` (VPS + Webhosting-Weg, Cron, Backups, Troubleshooting).
  - [x] Docker-Build und Container-Start verifiziert (healthy, non-root, Tesseract `deu`).

- [x] **Milestone 18: Qualität**
  - [x] Tests: `tests/test_harvester.py` (7), `tests/test_system_api.py` (4), `tests/test_stealth_insights.py` (17).
  - [x] `uv run pytest` – **454 passed**; `ruff check` / `ruff format --check` grün.
  - [x] Detect 0 Findings, Draft-Guard clean.

## Iteration 7 — Frontend-Überarbeitung (DESIGN.md)

- [x] **Milestone 13: Redesign nach `frontend`-Skill**
  - [x] `DESIGN.md` angelegt: Tokens (Farbe, Typo, Abstände), Komponenten-Inventar, Layout-Linie, Motion, Surfacing, Accepted Debt und Gap-Ledger (Branch 3: implizites System extrahiert).
  - [x] Typografie: Serifen-Display (`ui-serif/Georgia`) für H1/H2/Produktnamen, System-Sans für UI, Skala mit ≥1,25×-Schritten, `tabular-nums` auf Preisen und Summen.
  - [x] Farbe: eine Akzentfarbe, konsistente Neutralrampe, `--info`/`--info-bg` für Standardpreise, Header-Gradient entfernt (flache Fläche + Hairline).
  - [x] Draft-Guard: farbiger Seitenstreifen auf Standardpreis-Karten entfernt (tonale Fläche), Spinner ohne `border-top`-Trick, keine Emoji-Icons mehr.
  - [x] Icons: Inline-SVG-Sprite (Korb, Mikrofon, Kopieren, Teilen, Bon, Badges) statt Emoji.
  - [x] Browser-Flächen: `::selection`, `caret-color`, `scrollbar-color`, globaler `:focus-visible`-Ring, Unterstrich-Offset.
  - [x] A11y: Skip-Link, `main id="main"`, `text-wrap: pretty`, 44px-Touchziele auf Mobile, Platzhalter mit 4,5:1.
  - [x] Meta: Description, Theme-Color (hell/dunkel), Inline-SVG-Favicon.
  - [x] Karten-Rauschen reduziert: Schalter ohne Pillen-Chrome, Grundpreis als Datenzeile, Rezepte als Hairline-Sektion, Share-Leiste ohne zweite Karte.
  - [x] Verifikation: `detect` 0 Findings (1440 + 390), `check-draft-guard` clean, Kontrastpaare 16/16 AA, 426 Tests grün.

## Iteration 6 — Teilen & Spar-Rezepte

- [x] **Milestone 12: Smart-Basket-Sharing und Rezept-Optimierer**
  - [x] `services/sharing.py`: `format_plan_text()` erzeugt eine WhatsApp-taugliche Übersicht (Märkte, Artikel mit Mengen, Gesamt, Ersparnis, Alternative, fehlende Artikel) mit deutschen Dezimalkommas.
  - [x] `whatsapp_url()` baut den `https://wa.me/?text=…`-Link (vollständig URL-kodiert, inkl. Emojis und €).
  - [x] `BasketPlan` um `share_text` und `whatsapp_url` erweitert; der Aggregator befüllt beide in `optimize_basket()` – ein Request, identische Texte für alle Clients.
  - [x] UI: Share-Leiste unter dem Optimierer-Ergebnis mit **„WhatsApp teilen"** und **„In die Zwischenablage kopieren"** (Clipboard-API + `execCommand`-Fallback, Feedback „Kopiert! ✓").
  - [x] Zusätzliche kompakte Share-Buttons im Merklisten-Drawer, sichtbar nach der Berechnung.
  - [x] `services/recipes.py`: 5 Alltagsrezepte (Spaghetti Bolognese, Penne Arrabbiata, Kartoffelsuppe, Gemüsecurry, Käsespätzle) mit Zutaten, Mengen, Portionen, Zeit und Tags.
  - [x] API `GET /api/v1/recipes` und `GET /api/v1/recipes/{id}` inkl. `query_terms` für den Optimierer.
  - [x] UI-Sektion „Spar-Rezepte der Woche": Karten mit Zutaten, Button **„Rezept in den Smart Basket übernehmen"** → Zutaten in den persistenten Zettel, Drawer öffnet, Optimierung startet sofort.
  - [x] Responsiv (`auto-fit`-Grid, Mobile-Stacking) und barrierefrei (semantische Überschriften, `aria-label`, `role="button"` für den WhatsApp-Link).
  - [x] Tests: `tests/test_share_recipes.py` (13) für Formatierung, Sonderfälle, URL-Kodierung, Rezeptkatalog und Endpoint; UI-Tests ergänzt.
  - [x] `uv run pytest` – **426 passed**; `ruff check` & `ruff format --check` grün.

## Iteration 5 — Community-Crowdsourcing & Kassenbon-Import

- [x] **Milestone 11: Community-Preise, Kassenbon-Parser, Gamification**
  - [x] SQLite-Schema v4: `community_prices`, `community_confirmations`, `receipts` (Indizes auf Identity/PLZ/Scout).
  - [x] Aggregation per **Median** über Produkt/Markt/PLZ; Vertrauensstufen `pending` → `verified` ab 3 unterschiedlichen Bestätigungen (`INSERT OR IGNORE` verhindert Doppelzählung).
  - [x] Endpunkte: `POST/GET /api/v1/crowd/prices`, `/prices/{id}/confirm`, `/coverage`, `/scouts/{id}`, `/upload-receipt`, `/receipts/text`.
  - [x] Kassenbon-Parser (`services/receipts.py`): Markt- und PLZ-Erkennung, Positionszeilen, Folgereilen-Preis („Name" + „1,49"), `2 Stk x …`, EAN-Zeile, Einheiten (kg/l) inkl. Grundpreis, Ignorieren von Summen/MwSt./Zahlarten; Warnung bei stark abweichender Summe.
  - [x] Upload-Pipeline (`services/receipt_import.py`): Text/CSV, PDF-Textlayer (`pypdf`), Bilder nur mit lokalem OCR-Stack – sonst `503` mit klarem Hinweis statt Fake-OCR.
  - [x] Integration in Suche (`source="community"`, `offer_type="standard"`) und Smart Basket; `offers_only` blendet sie wie andere Standardpreise aus.
  - [x] UI: Deckungsanzeige unter der PLZ, „Preis melden"-Dialog je Karte, Kassenbon-Dialog (Datei oder eBon-Text) im Footer, Scout-ID + Badges im Merklisten-Drawer, blaues Badge „Community-Standardpreis".
  - [x] Datenschutz: keine IP/Session/UA, nur `Scout-#1234` aus `localStorage`, optional leer.
  - [x] Tests: `tests/test_crowd.py` (23) inkl. Median, Verify-Schwelle, Coverage-Level, Receipt-Parsing, Upload-Fälle (415/503), API-Validierung.
  - [x] `uv run pytest` – **411 passed**; `ruff check` / `ruff format --check` clean.

## Iteration 1–2 — Grundsystem und Ausbau

- [x] **Milestone 1: Project Setup & Environment**
  - [x] Initialize Python project with `uv` (`pyproject.toml`, dependencies: `fastapi`, `uvicorn`, `pydantic`, `httpx`, `pytest`, `pytest-asyncio`, `rapidfuzz`).
  - [x] Setup directory structure according to `ARCHITECTURE.md`.

- [x] **Milestone 2: Data Models & Normalization Engine**
  - [x] Implement Pydantic models in `supermarket_comparison/models/product.py`.
  - [x] Implement robust normalization logic in `supermarket_comparison/normalization/normalizer.py` (parsing quantities like "500g", "1,5 l", calculating unit prices per kg/l, discount calculation).
  - [x] Implement unit tests for normalizer (`tests/test_normalizer.py`).

- [x] **Milestone 3: Supermarket Scrapers & API Clients**
  - [x] Implement Base Scraper / Client (`supermarket_comparison/scrapers/base.py`).
  - [x] Implement Lidl client (`supermarket_comparison/scrapers/lidl.py`) using public Lidl Plus endpoints (`DE`, `de-DE`, postal code / coordinates).
  - [x] Implement Edeka client (`supermarket_comparison/scrapers/edeka.py`).
  - [x] Implement Rewe mobile API client (`supermarket_comparison/scrapers/rewe.py`) using EAN endpoints (`/products/ean/{ean}`) and categories (`/mobile/categories/`).
  - [x] Implement Marktguru client (`supermarket_comparison/scrapers/marktguru.py`) for offer search by postal code.
  - [x] Implement Open Food Facts Open Prices client (`supermarket_comparison/scrapers/openfoodfacts.py`).
  - [x] Implement unit tests for scrapers / mock responses (`tests/test_scrapers.py`).

- [x] **Milestone 4: Aggregator Service & Matching Pipeline**
  - [x] Implement Aggregator service (`supermarket_comparison/services/aggregator.py`) to query multiple sources concurrently and aggregate results.
  - [x] Implement product matching & deduplication (`supermarket_comparison/normalization/matcher.py`) based on EAN and fuzzy title matching (`rapidfuzz`).

- [x] **Milestone 5: FastAPI Backend & Documentation**
  - [x] Implement FastAPI app, CORS middleware, and API routes (`supermarket_comparison/api/routes/products.py`, `stores.py`).
  - [x] Expose `/docs` (Swagger UI) and `/redoc`.
  - [x] Add integration tests for API (`tests/test_api.py`).

- [x] **Milestone 6: Verification & Final Polish**
  - [x] Run full pytest test suite.
  - [x] Verify local server startup with `uvicorn`.
  - [x] `uv run pytest` – 186 passed.
  - [x] `uv run ruff check .` and `uv run ruff format --check .` – clean.
  - [x] Smoke-tested `/health`, `/docs`, `/redoc` and `/openapi.json` against a live `uvicorn` process.

- [x] **Milestone 8: Präzise Suche, Gültigkeits-Badges, Merkliste & Smart-Basket-Optimierer**

  **8.1 Relevanz-Ranking (Butter ≠ Buttermilch)**
  - [x] Neues Modul `normalization/relevance.py` mit dreistufigem Scoring:
    - Stufe 3 – *exakter Worttreffer* (`butter` als eigenes Wort) oder *Kompositions-Suffix* (`markenbutter`, `süßrahmbutter` – deutsches Grundwort steht hinten).
    - Stufe 2 – *Kategorie-Match* (Suchbegriff passt zur Produktkategorie, z. B. „Molkereiprodukte“/„Butter").
    - Stufe 1 – *Präfix-Zusatz* („Butter" ist Bestimmungswort eines anderen Produkts: `butter milch`, `butter keks`, `erdnuss butter`) – niemals gleichwertig zu Stufe 3.
  - [x] `ScoredProduct`-Datenklasse mit `score`, `tier`, `matched_as` (`exact`/`compound`/`category`/`modifier`), `matched_terms`, `counter_terms`.
  - [x] `rank_products()` + `keyword_stats()` (Häufigkeit von Stufe-3- vs. Stufe-1-Treffern).
  - [x] Generische `MODIFIER_EXCEPTIONS` für `butter`, `milch` und `wein` (u. a. Erdnussbutter, Kokosmilch, Weinbrand).
  - [x] Aggregator: `search(..., precise=True)`, `search_ranked(...)`; Stufe-1-Treffer werden bei `precise=True` verworfen.
  - [x] `quick_filters` werden aus dem ungefilterten Kandidatensatz gebildet, damit aktive Ausschluss-Chips sichtbar bleiben.
  - [x] Neue API `GET /api/v1/products/search/ranked` → `{query, postal_code, total, items:[{product, relevance}], quick_filters:[{term,count}], errors}`; bestehende Endpoints bleiben unverändert.
  - [x] Filter-Chips (`-Buttermilch`, `-Butterkeks`) im Frontend, Klick schließt Begriff aus (`exclude`-Parameter + lokaler Sofort-Filter).
  - [x] **Nachtrag Koordinator-Review:** Erkennung *getrennter* Komposita über die deutsche Großschreibung – „Butter-Mandel-Stollen" (Kopf: Stollen), „Butter-Karamell-Waffeln", „Milch Reis" werden als Stufe 1 gewertet, während Adjektive („Butter, gesalzen") und Mengenwörter („Butter Stück", „Butter Kilo") Stufe 3 bleiben; Chips zeigen dadurch das echte Grundwort (`-Stollen`, `-Waffeln`).
  - [x] **Nachtrag Koordinator-Review:** Die Frontend-Sortierung respektiert die Relevanzstufe als Primärschlüssel – auch bei „Genauere Suche = aus" landet kein „Buttermilch"-Treffer über echter Butter.

  **8.2 Gültigkeits-Badges**
  - [x] `services/validity.py`: `classify(valid_from, valid_to, now)` → `today` / `upcoming` / `expired` in **Europe/Berlin** (API liefert UTC, `…22:59:59Z` = lokaler Tageswechsel) + deutsches Label.
  - [x] Badge je Produktkarte (grün „Heute gültig", blau „Ab Montag, 09.11.") + Toggle „Nur heute gültige Angebote" (`today_only=true`).
  - [x] Tests für Zeitzonen-Grenzfälle.

  **8.3 Merkliste & Smart Basket**
  - [x] Backend `POST /api/v1/basket/optimize` (`items[]`, `postal_code`, `stores[]`, `max_stores`, `today_only`):
    - *Option A (Bester Split):* je Begriff global günstigstes Angebot, gruppiert nach Markt inkl. Zwischensummen, Gesamtsumme, Ersparnis gegenüber bestem Einzelmarkt.
    - *Option B (max. 1–2 Märkte):* Kombinationen bis `max_stores`, je Begriff günstigstes Angebot innerhalb der Kombination, mit Abdeckung/Summe/Ersparnis.
    - Preisvergleich über `unit_price` nur bei gleicher Einheiten-Familie, sonst `price`.
    - Teil-Baseline (`baseline_partial=true`, `savings=0`), wenn kein Einzelmarkt die ganze Liste abdeckt – keine erfundene Ersparnis.
  - [x] 5-Minuten-TTL-Cache im Marktguru-Client.
  - [x] Frontend: „+ Merken"-Button, Merklisten-Drawer (`localStorage spv.basket.v1`), Zähler-Badge.
  - [x] Frontend: Einkaufszettel-Modus (Mehrfachbegriffe) + Ergebnisdarstellung beider Optimierungs-Optionen.
  - [x] **Nachtrag Koordinator-Review:** Merkliste dedupliziert nach Suchbegriff und ersetzt einen reinen Wunsch-Eintrag („Milch" aus dem Zettel) durch das konkrete Produkt, statt beides doppelt zu führen.
  - [x] Spracheingabe (`SpeechRecognition`, `de-DE`) mit Zwischenergebnissen und Fallback ohne JS-Fehler.

  **8.4 Qualitätssicherung**
  - [x] `tests/test_relevance.py`, `tests/test_validity.py`, `tests/test_basket.py`, erweiterte API-/UI-Tests.
  - [x] `uv run pytest` / `ruff check` / `ruff format --check` grün.
  - [x] Live-Smoke-Test: „butter" rankt echte Butter vor „Buttermilch"; Optimierer liefert beide Optionen mit echten Preisen.

- [x] **Milestone 7: Live-Datenanbindung korrigiert + Web-UI**
  - [x] Marktguru-Client auf den verifizierten Endpoint `GET https://api.marktguru.de/api/v1/offers/search` umgestellt (`as=web`, `q`, `zipCode`, `limit`, `offset`, `retailers`) inkl. `x-apikey`/`x-clientkey`-Header, Retry bei 5xx/Timeout und `referencePrice` → `unit_price`.
  - [x] `lidl.py`, `rewe.py`, `edeka.py` als dünne Adapter über den Marktguru-Feed; `RetailerScraper` in `scrapers/retailer.py` mit dynamischer `retailers`-ID-Auflösung und Client-Side-Filter.
  - [x] `AldiScraper`, `PennyScraper`, `NettoScraper`, `KauflandScraper` ergänzt und in `default_scrapers()` registriert (kein doppelter Marktguru-Fan-out).
  - [x] `openfoodfacts.py` auf reale Open-Prices-Antworten umgestellt (EAN-Lookup, `location.osm_name`, `product_quantity_unit`, `price_per_unit`); Freitext liefert bewusst `[]`.
  - [x] `filter_by_query` tolerant gemacht (Token-Substring in Name/Marke, Umlaut-Faltung, Fuzzy ≥ 70 %).
  - [x] Deutsche Web-UI unter `GET /` (`api/templates/index.html`, inline CSS/JS, Karten, Grundpreis, Rabatt, Sortierung, Zustände).
  - [x] Tests aktualisiert/ergänzt (`tests/test_scrapers.py`, `tests/test_ui.py`); `uv run pytest` – 244 passed.
  - [x] `uv run ruff check .` und `uv run ruff format --check .` – clean.
  - [x] Live-Smoke-Test: `butter` / PLZ `65618` liefert echte Angebote (u. a. Lidl „Kaergarden Butter" 1,39 €, 0,25 kg, 5,56 €/kg); `GET /` → 200 `text/html`.
