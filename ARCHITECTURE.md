# Architecture — FairBon

## Overview

FairBon is a privacy-first receipt tracker and community price comparison for
the DACH market. Users photograph or paste a receipt, review the extracted
line items, keep their expenses locally, and can optionally contribute
anonymised product prices to a shared price pool. There is **no leaflet
scraping** and no third-party supermarket content.

Stack: Python 3.12, FastAPI, Pydantic v2, SQLite (WAL), httpx, Pillow, pypdf,
openpyxl, pytest, ruff, and a modular vanilla-JS PWA (Capacitor-ready).

## Backend layout

```
supermarket_comparison/
├─ api/
│  ├─ main.py            app factory, auth/security middleware, static mounts
│  └─ routes/            products, basket, history, crowd, receipts, export,
│                        system, admin_db, images, stores
├─ services/
│  ├─ aggregator.py      fan-out + dedup for community/standardprices
│  ├─ receipt_vision.py  multimodal scan with provider failover + BYOK
│  ├─ upload_security.py magic bytes, size, RAM-only Pillow sanitising
│  ├─ receipt_import.py  text/PDF extraction (eBon path)
│  ├─ receipts.py        deterministic German receipt parser
│  ├─ price_validator.py plausibility checks / quarantine
│  ├─ rate_limit.py      per-IP windows + global daily counter
│  ├─ turnstile.py       optional Cloudflare bot protection
│  └─ auth.py            site gate, fail-closed admin gate
├─ storage/
│  ├─ database.py        SQLite wrapper (WAL, busy_timeout, foreign keys)
│  ├─ repository.py      products, price points/history, user receipts, aliases
│  ├─ community.py       anonymous community prices + confirmations
│  └─ schema.sql         full schema (versioned migrations)
└─ normalization/        units, brands, titles, matching, relevance
```

## Data model (core tables)

- `user_receipts` / `user_receipt_items` — personal receipts, keyed by an
  anonymous `owner_token`; amounts stored as integer cents; categories, VAT,
  discounts, deposit and a per-line `is_private` flag.
- `receipt_aliases` — self-learning mapping `(store, normalised raw text)` →
  canonical product fields with `hit_count`.
- `community_prices` — anonymised contributions (no owner token, no receipt
  id), validated and quarantined (`pending`, `pending_review`, `approved`,
  `verified`, `rejected`). Only approved/verified rows are visible.
- `products`, `price_points`, `price_history` — normalised catalogue and price
  series used by search, history and the basket optimiser.
- `search_events` / `search_trends` — anonymised aggregate search statistics.

## Receipt flow

1. Client downscales the photo (max 1200 px, grayscale, JPEG ~0.82).
2. `POST /api/v1/receipts/scan` sanitises the upload in RAM (magic bytes, 3 MB,
   EXIF strip), then calls the configured vision provider (Gemini, Mistral,
   OpenAI-compatible or OpenCode) with a strict JSON prompt. Provider failure
   falls back automatically. PDFs/text use the local parser (0 € API cost).
3. The user reviews/edits the extracted items.
4. `POST /api/v1/receipts` stores the personal receipt. Only with explicit
   opt-in are eligible lines forwarded to `community_prices` (no owner token,
   no receipt id, no deposit lines, no private lines). Demo receipts are
   excluded server-side.
5. Administrators approve prices in `/admin` (moderation queue); approved
   prices appear in search, history and the basket optimiser.

## Frontend

`frontend/` is a static PWA served by FastAPI:

- `index.html` — app shell with four tabs (Overview, Receipts, Prices, List)
- `css/styles.css` — existing design system (CSS variables, light/dark,
  serif headings, safe areas, bottom sheets)
- `js/api.js` — central API client (`API_BASE_URL`, owner token, BYOK headers)
- `js/state.js` — guest token, postal code, budget, basket persistence
- `js/platform.js` — camera/file abstraction + canvas compression (Capacitor)
- `js/views/*` — the four tabs
- `js/components/add-sheet.js` — receipt capture/preview
- `js/demo-receipt.js` — static demo data (no API calls)
- `manifest.webmanifest`, `sw.js` — installable/offline shell

No `innerHTML` for user/API content; DOM APIs and `textContent` only. ES5-style
JS, no build step.

## Security

- Fail-closed `ADMIN_PASSWORD` for `/admin`, backup/restore and moderation.
- Optional `SITE_PASSWORD` gate + stealth noindex mode; `/health` public.
- Rate limits (reads 60/min, scans 3/min + 15/day per IP, global 500/day).
- Upload sanitising, EXIF stripping, decompression-bomb guard, RAM-only.
- CSP, `X-Frame-Options: DENY`, `nosniff`, `Referrer-Policy`,
  `Permissions-Policy`; CORS credentials only with explicit origins.
- SQLite WAL + busy timeout; parameterised queries only.

## Deployment

Local: `./start.sh` (uvicorn). Production: hardened Docker image (non-root,
127.0.0.1 binding, 512 MB limit, read-only root) behind Caddy; see
[`SECURITY_DEPLOYMENT.md`](SECURITY_DEPLOYMENT.md).
