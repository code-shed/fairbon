# Supermarkt-Preisvergleich V1.0 — Architektur-Umbau

**Status (2026-11-22):** Phasen 1–4 umgesetzt — Cleanup, Scanner/Export, PWA-Frontend & Deployment-Härtung; Tests und Lint grün.

**Strategische Neuausrichtung:** Weg von externen Prospekt-Scraping (Marktguru), hin zu einer
100 % legalen, datenschutzfreundlichen Open-Source-App zum Kassenbon- & Ausgaben-Tracking
mit 1-Klick-Excel-Export und Community-Preisvergleich (anonymisiertes Opt-in).

---

## Phase 1 — Cleanup, DB-Schema & Security-Basis

- Marktguru/Scraper/Harvester entfernen
- SQLite WAL + neue Tabellen (`user_receipts`, `user_receipt_items`, `receipt_aliases`)
- Fail-Closed `ADMIN_PASSWORD`, CORS, Security-Header
- Rate-Limiting/Circuit-Breaker-Grundgerüst
- `scripts/seed_demo.py`
- Alle Tests grün, `ruff check .` sauber

## Phase 2 — Scanner-Pipeline & Excel-Export (Backend)

- Upload-Sanitizing (Magic Bytes, 3 MB, Pillow EXIF-Strip im RAM)
- `services/receipt_vision.py` (Dual-Provider-Fallback + Prompt-Injection-Abwehr + eBon-Fallback)
- `api/receipts.py` (striktes Community-Opt-in, kein `owner_token`-Leak)
- `api/export.py` (3-Sheet-`.xlsx` & `.csv`)
- Tests grün

## Phase 3 — Frontend-Modularisierung & 4-Tab-App (PWA + Capacitor-ready)

- Zerlegung in `frontend/`-Struktur (App-Shell, CSS, JS-Module)
- `manifest.webmanifest` + `sw.js` (PWA)
- 4 Tabs: Übersicht, Bons, Preise, Liste
- Bottom-Sheet mit Canvas-Komprimierung
- Mobile-First (Safe Areas, Touch-Ergonomie, `100dvh`)

## Phase 4 — Deployment-Härtung & Abschluss-Check

- Non-Root Dockerfile, gehärtete `docker-compose.yml`
- `.env.example` mit allen neuen Variablen
- `SECURITY_DEPLOYMENT.md`
- Vollständiger `pytest`- + `ruff`-Durchlauf

---

## Mobile-First & Capacitor-Zusatz (gilt für Phase 3)

- Viewport: `viewport-fit=cover`, Apple-PWA-Meta, `safe-area-inset-*`
- Touch: 44×44 px, `touch-action: manipulation`, `16px` Inputs, `100dvh`
- Relative Pfade in `frontend/` (Capacitor `webDir`-kompatibel)
- Kamera/Datei-Zugriff in `frontend/js/platform.js` gekapselt

## Scope-Grenzen (NICHT in V1.0)

- Kein E-Mail-/Passwort-Login
- Keine Bon-Weiterleitung, kein QR-Reader, keine Händler-App-Integration
- Keine Prospekt-PDF-Scraper, kein DATEV-/ZIP-Bildarchiv