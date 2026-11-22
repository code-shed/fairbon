# FairBon V1.0 — Architecture Rebuild

**Status (2026-11-22):** Phases 1–4 complete — cleanup, scanner/export, PWA
frontend and deployment hardening; tests and lint green.

**Strategic direction:** FairBon is a 100% legal, privacy-friendly open-source
receipt and expense tracker with a 1-click Excel export. Users can optionally
contribute anonymised product prices to the community price comparison and the
smart-basket optimiser. No leaflet scraping, no third-party supermarket logos.

---

## Phase 1 — Cleanup, database schema & security baseline

- Remove Marktguru/kaufDA scrapers and the weekly harvester
- SQLite WAL + `busy_timeout=5000`, new tables (`user_receipts`,
  `user_receipt_items`, `receipt_aliases`)
- Fail-closed `ADMIN_PASSWORD`, CORS, security headers
- Rate-limiting / circuit-breaker foundation
- `scripts/seed_demo.py`
- All tests green, `ruff check .` clean

## Phase 2 — Scanner pipeline & Excel export (backend)

- Upload sanitising in RAM (magic bytes, 3 MB, Pillow EXIF strip)
- `services/receipt_vision.py` (dual-provider failover, prompt-injection
  defence, eBon fallback)
- `api/routes/receipts.py` (strict community opt-in, no owner-token leak)
- `api/routes/export.py` (2-sheet `.xlsx` and `.csv`)
- All tests green

## Phase 3 — Frontend modularisation & 4-tab app (PWA, Capacitor-ready)

- Split into `frontend/` (app shell, CSS, JS modules)
- `manifest.webmanifest` + `sw.js`
- Four tabs: Overview, Receipts, Prices, List
- Bottom sheets with canvas compression
- Mobile-first (safe areas, touch ergonomics, `100dvh`)
- Interactive demo receipt with live scan checklist and discount badges

## Phase 4 — Deployment hardening & final check

- Non-root Dockerfile, hardened `docker-compose.yml` (127.0.0.1, `mem_limit`)
- `.env.example` with all variables
- `SECURITY_DEPLOYMENT.md`
- Full `pytest` + `ruff` run

---

## Mobile-first & Capacitor notes (Phase 3)

- Viewport `viewport-fit=cover`, Apple PWA meta tags, `safe-area-inset-*`
- 44×44 px touch targets, `touch-action: manipulation`, 16 px inputs, `100dvh`
- Relative paths inside `frontend/` (Capacitor `webDir` compatible)
- Camera/file access encapsulated in `frontend/js/platform.js`

## Out of scope (V1.0)

- Email/password login (guest mode via `owner_token` + token backup)
- Receipt forwarding email, QR reader, retailer app integrations
- Leaflet PDF scrapers, DATEV/ZIP image archive
