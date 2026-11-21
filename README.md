# DACH Supermarket Price Comparison

Aggregates current offers and unit prices (EUR/kg, EUR/l) for **Lidl**,
**Rewe**, **Edeka**, **Aldi**, **Penny**, **Netto**, **Kaufland**,
**Rossmann**, **dm** and **Globus** for the German-speaking market and exposes
them through a FastAPI service with a built-in German-language web UI.
METRO is deliberately excluded (wholesale, membership card) — the app only
compares prices a normal customer can actually get.

Store offers are read from the **Marktguru** leaflet feed (the only publicly
reachable source for all seven retailers); **Open Food Facts – Open Prices**
adds crowd-sourced EAN price lookups.

## Quick start

```bash
uv sync
uv run uvicorn supermarket_comparison.api.main:app --reload
```

Then open:

* **Web UI:** <http://127.0.0.1:8000/>
* Swagger UI: <http://127.0.0.1:8000/docs>
* ReDoc: <http://127.0.0.1:8000/redoc>

## Web UI

`GET /` serves a single self-contained HTML page ("Supermarkt-Preisvergleich")
with inline CSS/JS – no CDN, no build step, dark/light friendly:

1. enter a search term (e.g. *Butter*), a postal code (default `65618`) and
   pick the retailers,
2. the page calls `GET /api/v1/products/search/ranked` via `fetch`,
3. results render as cards with store badge, price, struck-through old price,
   discount badge, **Grundpreis** (EUR/kg resp. EUR/l), pack size, category
   and validity period,
4. the list can be re-sorted client-side by **Preis**, **Grundpreis** or
   **Rabatt** (default: unit price, because that is the comparison metric).

Additional UI features:

* **Genauere Suche** (default on) hides modifier hits such as *Buttermilch*
  for *Butter*. **Nur heute gültige Angebote** restricts the result set to
  offers valid today in `Europe/Berlin`.
* **Compound-aware relevance**: besides one-word compounds (`Markenbutter` =
  butter, `Buttermilch` = milk), separated compounds are detected via German
  capitalisation — *Butter-Mandel-Stollen* and *Milch Reis* are modifiers
  because the head noun follows the query, while adjectives (*Butter,
  gesalzen*) and measure words (*Butter Stück*) keep the hit precise. Sorting
  always keeps the relevance tier on top, so no imprecise hit outranks a real
  match.
* **Filter-Chips** under the search bar (`− Buttermilch (3)`) exclude a
  compound immediately; active chips are highlighted and **Alle zurücksetzen**
  clears every exclusion. The state is mirrored in the URL
  (`?q=…&plz=…&exclude=…`).
* **Validity badges** on each card: green *Heute gültig*, blue
  *Ab Montag, 09.11.*, red *Abgelaufen*. With **Genauere Suche** off,
  imprecise hits carry an amber **unscharfer Treffer** tag.
* **Merkliste** drawer (`🛒 Merkliste (N)`, persisted in
  `localStorage` under `spv.basket.v1`) with remove/clear, a running total
  and **Günstigste Aufteilung berechnen**.
* **Einkaufszettel-Modus**: the textarea accepts `"Nutella, Butter, Milch"`,
  `"Nutella Butter Milch"`, `"Ich brauche Butter und Nutella"` and
  line breaks alike — commas are optional. Recognised terms appear instantly
  as chips under the field, and **Alle Begriffe suchen** renders one result
  group per term. Multi-term input in the main search field takes the same
  path. The server-side twin of the parser is
  `POST /api/v1/basket/parse` (`supermarket_comparison/normalization/terms.py`);
  both implementations are covered by the same 25-case parity test.
* **Spracheingabe** (🎤 next to the search field and next to the list,
  `SpeechRecognition`, `de-DE`, interim results). The buttons show a red
  pulsing listening state, the transcript is written straight into the focused
  field, and a visible hint explains when the browser/context cannot do
  speech (`isSecureContext`, Firefox).

The optimiser renders **Option A · Bester Split** (cheapest offer per item,
grouped by store) and **Option B · Max. 2 Märkte** (best combination of at
most two stores) including subtotals, total, savings versus the cheapest
single market, coverage and missing items.

**Community features** (anonymous, no account):

* **Deckungsanzeige** under the postal code: *„PLZ 65618: N Standardpreise
  erfasst · X Produkte · Y Märkte · Z Scouts"* plus a level pill
  (`im Aufbau` / `aktiv` / `stark`).
* **„Preis melden"** on every product card opens a small dialog prefilled with
  name, store and price; the result is stored with the median shown live.
* **Kassenbon-Upload** in the footer and via *„Preise beisteuern"*: file
  (txt/csv/pdf/image) or pasted eBon text, with a per-item preview before the
  confirmation.
* **Scout-ID & Badges**: `spv.scout.v1` in `localStorage` generates
  `Scout-#1234`; badges (*Erster Preis*, *Kassenbon-Scout*,
  *Nachbarschafts-Helfer*, *Preis-Held*) appear in the basket drawer.
* Community prices render with a blue **Community-Standardpreis** badge and
  participate in the smart basket like any shelf price.

**Teilen:**

* The optimiser result carries a ready-to-share text
  (`share_text` / `whatsapp_url` in the API response) with stores, items,
  totals, savings and the 1–2-store alternative.
* **WhatsApp teilen** opens `https://wa.me/?text=…`; **In die Zwischenablage
  kopieren** uses the Clipboard API with an `execCommand` fallback and shows
  *„Kopiert! ✓"*. Both buttons also appear in the basket drawer after a
  calculation.
* **Produktbilder:** Karten und Detail-Modal zeigen ein Bild mit
  `aspect-ratio: 1/1`, `object-fit: contain` und `loading="lazy"`. Offers ohne
  Bild (Marktguru liefert keine Bild-URLs) werden per Open-Food-Facts-Lookup
  (EAN oder Namenssuche) aufgelöst; scheitert das oder bricht das Bild, greift
  ein kategoriebasierter SVG-Platzhalter (Milchprodukte, Fleisch, Obst, Getränke,
  Backwaren, Vorrat, Süßes, Drogerie).
* **Preisverlauf:** Klick auf eine Karte öffnet das Detail-Modal mit Bild,
  Preis, Grundpreis, Prospekt-Link, Zeitraum-Tabs und SVG-Stufenchart.

The UI also shows idle, loading, empty and error states. Query and postal code
can be passed as URL parameters for shareable links:
<http://127.0.0.1:8000/?query=butter&postal_code=65618>

## Datenquellen — verifizierter Live-Status

| Quelle | Status | Anmerkung |
| ------ | ------ | --------- |
| **kaufDA** (`www.kaufda.de/api/search`) | ✅ **Fallback** | Zweitquelle für Prospektangebote (Bonial): `lat`/`lng` + `query`, PLZ wird über Nominatim geokodiert. Liefert Preis, Streichpreis, Grundpreis, Bild, Gültigkeit und Händler. Ein Angebots-Deeplink existiert nicht (nur verifizierte Händlerseiten). |
| **Marktguru** (`api.marktguru.de/api/v1/offers/search`) | ✅ **primär** | Liefert Prospekt-Angebote je PLZ für Lidl, Rewe, Edeka, Aldi, Penny, Netto, Kaufland und Rossmann; `nahkauf` wird als Edeka-Banner auf `edeka` gemappt (verifiziert: `q=butter&zipCode=65618` → `totalResults=36`). Benötigt `x-apikey` + `x-clientkey`. Keine Bilder/EANs in der Antwort, aber ein Deep-Link (`leaflet_url` → `marktguru.de/offers/{id}`). |
| **Open Food Facts – Katalog** (`search.openfoodfacts.org/search`) | ✅ **Standardsortiment-Katalog** | Liefert echte EANs inkl. Eigenmarken (verifiziert: `milbona` → 3387 Treffer, `balea` → 229, `cien` → 93, `gut und günstig` → 6354). Keine Preise. |
| **Open Food Facts – Open Prices** (`prices.openfoodfacts.org/api/v1/prices`) | ✅ **Standardpreis-Beobachtungen** | EAN-Lookup mit `location.osm_address_country_code` und `osm_address_postcode`; daraus wird auf Deutschland gefiltert und die PLZ-Region bevorzugt. Coverage ist dünn (im Test: 1 von 6 Milbona-EANs hatte einen DE-Preis). |
| Lidl direkt (`www.lidl.de` / Lidl Plus) | ❌ `401` | Server-seitige Requests ohne Mobile-Client-Zertifikat werden abgewiesen. |
| Edeka direkt (`www.edeka.de`) | ❌ `403` | Akamai-Bot-Schutz. |
| Rewe direkt (`mobile.rewe.de`, `www.rewe.de`) | ❌ NXDOMAIN / `403` | Host löst nicht mehr auf; die Web-Shop-Seiten liegen hinter Cloudflare. |
| Kaufland / Netto / Aldi / dm / Rossmann (direkt) | ❌ `403` | Cloudflare bzw. reine SPA ohne offene JSON-API; Angebote kommen über Marktguru bzw. kaufDA. |
| METRO | ⚠️ bewusst nicht eingebunden | Großhandel mit Kundenkarte – Preise sind für Endkunden nicht erreichbar. |

**Konsequenz:** Die clients `lidl.py`, `rewe.py`, `edeka.py` sowie
`aldi.py`, `penny.py`, `netto.py`, `kaufland.py` sind dünne Adapter über den
Marktguru-Angebotsfeed (`scrapers/retailer.py`). Sie filtern die Antwort
clientseitig auf den jeweiligen Händler und nutzen – sofern vorhanden – die
numerische `retailers`-ID aus `filters.retailers` für serverseitige Filterung.
Ein Filial-/Standort-API gibt es dort nicht, daher liefert `fetch_stores()`
immer `[]` (es werden keine Filialen erfunden).

**Standardpreise:** Da kein deutscher Händler eine offene Regalpreis-API
bereitstellt, läuft das Dauersortiment über den OFF-Katalog → Open-Prices-EAN-
Lookup (`services/standard_prices.py`). Es werden **nur beobachtete Preise**
ausgegeben; fehlt eine Beobachtung, fehlt das Produkt. Der Toggle
„Gesamtes Sortiment inkl. Standardpreise" schaltet diese Quelle zu
(`include_standard=true`).

## API

| Method | Path | Description |
| ------ | ---- | ----------- |
| `GET` | `/` | Deutsche Such-Oberfläche (HTML) |
| `GET` | `/health` | Service health and version |
| `GET` | `/api/v1/products/search` | Search offers (`query`, `postal_code`, `stores`, `limit` ≤1000, `precise`, `today_only`, `exclude`, `include_standard`, `offers_only`) |
| `GET` | `/api/v1/products/search/ranked` | Ranked search with relevance tiers, quick filters and validity (`query`, `postal_code`, `stores`, `limit` ≤1000, `precise`, `exclude`, `today_only`, `include_standard`, `offers_only`) |
| `GET` | `/api/v1/products/compare` | Cheapest offer per store (`ean` **or** `query`, `postal_code`, `stores`) |
| `GET` | `/api/v1/products/history` | Recorded price changes (`ean` **or** `name`, `store`, `days`) |
| `POST` | `/api/v1/basket/optimize` | Cheapest split for a shopping list (`items`, `postal_code`, `stores`, `max_stores`, `today_only`, `include_standard`) |
| `GET` | `/api/v1/stats/trends` | Anonymised top search terms (`days`, `limit`, optional `postal_code`) |
| `GET` | `/api/v1/stats/summary` | Row counts of the local SQLite database |
| `GET` | `/api/v1/products/image` | Resolve a product image (`name`, optional `ean`) |
| `GET` | `/api/v1/system/backup-db` | Download a consistent SQLite backup |
| `POST` | `/api/v1/system/restore-db` | Restore a `.db` upload (validated, auto `.bak`) |
| `GET` | `/api/v1/stores/search` | Branches near a postal code (`postal_code`, `store`) |
| `POST` | `/api/v1/crowd/prices` | Report a shelf price anonymously (`name`, `store`, `price`, `postal_code`, optional `ean`, `unit`, `quantity`, `scout_id`) |
| `GET` | `/api/v1/crowd/prices` | Raw submissions + median per product/store (`postal_code`, `ean`, `name`, `store`) |
| `POST` | `/api/v1/crowd/prices/{id}/confirm` | Confirm a price as a distinct scout (3 → `verified`) |
| `GET` | `/api/v1/crowd/review` | Moderation queue (`status=pending\|pending_review\|all`) |
| `POST` | `/api/v1/crowd/prices/{id}/approve` | Publish one price |
| `POST` | `/api/v1/crowd/prices/{id}/reject` | Hide one price permanently |
| `POST` | `/api/v1/crowd/review/approve-all` | Batch-approve all plausible `pending` prices |
| `GET` | `/api/v1/crowd/coverage` | Community coverage for a postal code (`postal_code`) |
| `GET` | `/api/v1/crowd/scouts/{scout_id}` | Anonymous contribution stats + badges |
| `POST` | `/api/v1/crowd/upload-receipt` | Multipart receipt upload (text/PDF/image) → parsed shelf prices |
| `POST` | `/api/v1/crowd/receipts/text` | Same via pasted eBon text |

### Community-Preise

Community contributions are anonymous (only a random `Scout-#1234` id from
`localStorage`). **Strict mode:** a price is only visible after an admin
approves it or three distinct scouts confirm it — showing nothing beats showing
a wrong price.

Before anything enters the database, `services/price_validator.py` checks it:

1. **Hard limits** — 0,10 €–200,00 € and a positive quantity.
2. **Category band** — the unit price must sit inside the band of the inferred
   category (e.g. dairy 0,30–25,00 €/kg).
3. **Relative check** — with three confirmed prices for the same product/store,
   a deviation beyond 1,8× / below 0,55× of their median is suspicious.

A suspicious entry becomes `pending_review` with a stored reason and stays
invisible; plausible entries become `pending` and wait for approval. The admin
dialog has a **Prüf-Queue** with single approve/reject plus
**„Alle plausiblen freigeben"** (batch, anomalies excluded).

Receipt import supports `.txt`/`.csv`, PDFs with a text layer and — if the host
has Tesseract — photos. Without a local OCR stack an image upload answers
`503` with a clear hint instead of pretending it read the photo.

```bash
curl -X POST localhost:8000/api/v1/crowd/prices \
  -H 'Content-Type: application/json' \
  -d '{"name":"Bio Butter 250g","store":"lidl","price":1.39,"postal_code":"65618","quantity":0.25,"unit":"kg","scout_id":"Scout-#4812"}'

curl -X POST localhost:8000/api/v1/crowd/receipts/text \
  -H 'Content-Type: application/json' \
  -d '{"text":"REWE\n10115 Berlin\nJA! BUTTER 250G 2,19\nSUMME 2,19","scout_id":"Scout-#4812"}'
```

Examples:

```bash
curl "http://127.0.0.1:8000/api/v1/products/search?query=butter&postal_code=65618&limit=5"
curl "http://127.0.0.1:8000/api/v1/products/search/ranked?query=butter&postal_code=65618&precise=true&exclude=Buttermilch"
curl "http://127.0.0.1:8000/api/v1/products/search?query=butter&postal_code=65618&stores=lidl,rewe"
curl "http://127.0.0.1:8000/api/v1/products/compare?ean=3701002400177"
curl -X POST "http://127.0.0.1:8000/api/v1/basket/optimize" \
  -H 'Content-Type: application/json' \
  -d '{"items":["Butter","Nutella","Milch"],"postal_code":"65618","max_stores":2,"today_only":false}'
```

The `stores` parameter accepts a comma-separated list (`lidl`, `rewe`,
`edeka`, `aldi`, `penny`, `netto`, `kaufland`, `rossmann`, `dm`, `globus`,
`openfoodfacts`). When omitted,
all configured sources are queried concurrently. A source that fails is
skipped; the remaining results are still returned and the failure is exposed
via `Aggregator.last_errors` / the `errors` object of the ranked response.

Matching is deliberately tolerant: a product is relevant when any query token
(≥ 3 characters, umlaut-normalised) occurs in its name or brand, or when the
fuzzy title ratio reaches 70 %. `butter` therefore matches `Feine Butter`,
`Kaergarden Butter` and `Butter-Schmalz`.

Ranking then sorts those candidates into three tiers, following the German
head-last compound rule:

| Tier | `matched_as` | Example for `butter` |
| ---- | ------------ | -------------------- |
| 3 | `exact` / `compound` | `Butter`, `Markenbutter`, `Süßrahmbutter` |
| 2 | `category` | category/brand `Butter` |
| 1 | `modifier` | `Buttermilch`, `Butterkekse`, `Erdnussbutter` |

With `precise=true` (the default) only tiers 2–3 are returned; the ranked
endpoint additionally reports tier-1 compounds as `quick_filters`
(`{"term": "Buttermilch", "count": 3}`) so the UI can offer exclusion chips.
The chips are derived from the **unfiltered** candidate set, so an active
exclusion stays visible and can be undone. `MODIFIER_EXCEPTIONS` is generic and
ships with `butter`, `milch` and `wein` families: `Erdnussbutter`,
`Kakaobutter`, `Kokosbutter`, `Sheabutter`, `Bodybutter`, `Kokosmilch`,
`Sojamilch`, `Weinbrand` and `Weinessig` are always penalised to tier 1.

The basket optimiser compares `unit_price` **only within the same unit family**
(kg, l, piece). Across families it falls back to the absolute `price`, because
EUR/kg and EUR/piece are not comparable. It returns option A (cheapest offer
per item, possibly many stores), option B (best combination of at most
`max_stores` markets), unmatched items, per-source errors and savings versus
the cheapest single market.

If no single market carries the whole list, the response reports the best
**partial** single-store total for reference but sets `baseline_partial=true`
and `savings=0`; the UI then states that no single-market comparison is possible
instead of inventing a saving. An item without any candidate is always listed
under `unmatched` and never replaced by a substitute product.

## Configuration

Settings are read from `SUPERMARKET_*` environment variables:

| Variable | Default | Purpose |
| -------- | ------- | ------- |
| `SUPERMARKET_HTTP_TIMEOUT` | `15.0` | HTTP timeout in seconds |
| `SUPERMARKET_HTTP_USER_AGENT` | browser-like UA | User agent for all clients |
| `SUPERMARKET_CACHE_TTL_SECONDS` | `300` | Marktguru offer cache TTL (5 min; `0` disables it) |
| `SUPERMARKET_DEFAULT_POSTAL_CODE` | – | Default postal code |
| `SUPERMARKET_CORS_ORIGINS` | `*` | Comma-separated CORS origins |
| `SUPERMARKET_MARKTGURU_BASE_URL` | `https://api.marktguru.de` | Marktguru API base URL |
| `SUPERMARKET_MARKTGURU_API_KEY` | public web-client key | `x-apikey` header |
| `SUPERMARKET_MARKTGURU_CLIENT_KEY` | public web-client key | `x-clientkey` header |
| `SUPERMARKET_DEBUG` | `false` | FastAPI debug mode |

The Marktguru defaults are the keys the public web frontend
(`www.marktguru.de`) sends; they can be overridden without a code change —
either with the `SUPERMARKET_` prefix or with the short names
`MARKTGURU_API_KEY` / `MARKTGURU_CLIENT_KEY` (prefixed wins).

## Betrieb

* **Harvester 3×/Woche:** APScheduler läuft im FastAPI-Lifespan
  (Mo/Do/Sa 04:00 Europe/Berlin, `HARVEST_DAYS`/`HARVEST_HOUR`) und
  sammelt 100 Grundbegriffe × `HARVEST_ZIPS`. Manuell:
  `POST /api/v1/system/harvest`, Status unter `GET /api/v1/system/harvest-status`,
  per CLI `python -m supermarket_comparison.cli harvest`.
* **Stealth-Modus:** `STEALTH_MODE=true` liefert `robots.txt` mit
  `Disallow: /`, `X-Robots-Tag` und ein `noindex`-Meta. `SITE_PASSWORD` aktiviert
  die Login-Maske (Session-Cookie) plus HTTP Basic für API-Clients; `/health`
  bleibt offen. Beide Werte akzeptieren die kurzen Namen oder `SUPERMARKET_*`.
* **Admin-Datenbank:** `/admin` (hinter dem Passwort-Gate) zeigt `products`,
  `price_points`, `price_history` und `community_prices` tabellarisch, mit
  Suche, Filtern, Pagination und Inline-Bearbeitung inklusive Löschen.
  API: `GET /api/v1/admin/database/schema`, `GET …/records`,
  `PUT/DELETE …/records/{table}/{id}` — nur whitelisted Felder, alle
  Identifier aus der Registry, Werte parametrisiert.
* **Deployment:** `Dockerfile` + `docker-compose.yml` (persistentes
  `./data`-Volume, `restart: unless-stopped`, Tesseract inkl. `deu`).
  Anleitung: `DEPLOY_SERVER.md`.

## Design

`DESIGN.md` carries the design system extracted from the UI: the colour tokens
(one green accent, one cool-neutral ramp, both themes), the type scale (system
serif display + system sans UI, tabular numerals for prices), the component
inventory with its states, the layout line, motion and surfacing rules, and the
open debt. Any UI change must trace its colours, sizes and spacing to a token
there.

Verification for the UI: `detect` (frontend skill) reports 0 findings at 1440
and 390, the draft-guard lint is clean, and all text/background pairs used by
the interface clear WCAG AA (16/16 pass; most reach AAA).

## Architecture

The pipeline is:

1. **Scrapers** (`supermarket_comparison/scrapers/`) fetch JSON from the
   verified public endpoints and map records to `NormalizedProduct`.
   `RetailerScraper` adapts the Marktguru feed per retailer.
2. The **normalizer** parses package sizes such as `500 g` or `6 x 0,33 l`
   and calculates unit prices and discounts.
3. The **aggregator** fans out concurrently with `asyncio.gather`, isolates
   failures, filters by relevance and deduplicates offers.
4. The **relevance engine** (`normalization/relevance.py`) scores hits into
   three tiers and derives the quick-filter chips; `services/validity.py`
   classifies offer windows on Berlin local dates.
5. The **matcher** groups equivalent products by exact EAN and fuzzy title
   similarity (`rapidfuzz`), while keeping store diversity for comparisons.
6. The **basket optimiser** resolves every item concurrently and evaluates
   all store subsets up to `max_stores` for the cheapest feasible plan.
7. **Standardpreise** (`services/standard_prices.py`): OFF-Katalog → EAN →
   Open Prices, gefiltert auf Deutschland und die PLZ-Region. Nur beobachtete
   Preise werden ausgegeben (`offer_type="standard"`).
8. **Persistenz** (`storage/`): SQLite mit `products`, `price_points`,
   `price_history`, `search_events` und `search_trends`; Preisänderungen werden
   nur bei echter Änderung historisiert, Suchanfragen anonymisiert aggregiert.
9. **Community** (`storage/community.py`, `services/receipts.py`): anonyme
   Preis-Meldungen, Median-Aggregation, Vertrauensstufen und Kassenbon-Import
   (Text/PDF, optional OCR). Community-Preise fließen als `source="community"`
   in Suche und Smart Basket ein.
10. **kaufDA** (`services/kaufda.py`): Fallback-Provider, parallel zu Marktguru
    abgefragt; identische Angebote (Markt + normalisierter Name + Preis +
    Gültigkeitsfenster) werden zugunsten von Marktguru verworfen.
11. The **FastAPI** routes validate parameters and expose the unified schema;
    `/` serves the HTML search UI.

Database file: `data/supermarkt.db` (override with `SUPERMARKET_DATABASE_PATH`).

See `ARCHITECTURE.md` for the full component diagram.

## Development

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
./scripts/qa-ui.sh        # UI: Draft-Guard-Lint + detect (1440/390)
```

`scripts/qa-ui.sh` startet einen isolierten Server (temporäre Datenbank, ohne
Passwort), prüft `/` und `/admin` mit `detect` und lintet danach die Templates
mit `check-draft-guard`. Exit 0 = sauber, 1 = Findings, 2 = Werkzeug-/Startfehler.

Bequeme Wrapper (nach `source ~/.bashrc` bzw. neuem Terminal):

```bash
spv-guard supermarket_comparison/api/templates   # statischer Lint
spv-detect http://127.0.0.1:8000/                # gerenderte Seite prüfen
```

Die Wrapper liegen in `~/.local/bin`; `~/.bashrc` ergänzt dieses Verzeichnis um
`PATH` (damit auch `uv` in normalen Terminals gefunden wird).

Live smoke test:

```bash
uv run python -c "
import asyncio
from supermarket_comparison.services.aggregator import Aggregator

async def main():
    async with Aggregator() as agg:
        for p in await agg.search(query='butter', postal_code='65618'):
            print(p.store, p.name, p.price, p.unit_price, p.unit)

asyncio.run(main())
"
```
