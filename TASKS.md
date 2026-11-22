# FairBon — Tasks & Roadmap

**Status:** V1.0 architecture rebuild complete (Phases 1–4). The app runs
locally and in Docker; all tests and lint checks are green.

## Done

- [x] Remove Marktguru/kaufDA scrapers and the weekly harvester
- [x] SQLite WAL + `busy_timeout`, receipt/alias schema
- [x] Fail-closed admin auth, security headers, CORS hardening
- [x] Rate limiting + global daily scan cap
- [x] Receipt scanning: vision provider failover (Gemini/Mistral/OpenAI-compatible/OpenCode), BYOK, eBon/PDF/text fallback
- [x] Upload hardening: magic bytes, 3 MB limit, Pillow EXIF strip in RAM
- [x] Personal receipts with anonymous guest token
- [x] Self-learning `receipt_aliases`
- [x] Community opt-in with price validation and quarantine
- [x] 2-sheet Excel/CSV export (raw rows + VAT/category summary)
- [x] Modular PWA frontend (4 tabs, bottom sheets, safe areas)
- [x] Interactive demo receipt with live checklist and discount badges
- [x] Branding: logo, banners, PWA icons, favicons
- [x] Hardened Dockerfile/Compose and `SECURITY_DEPLOYMENT.md`

## Next

- [ ] End-to-end run with a real receipt and vision provider
- [ ] Polish: receipt list error vs. empty state, export button states, copy feedback, BYOK hint
- [ ] Docker build on a machine with Docker group access
- [ ] Always-on deployment (systemd/Docker restart policy, backups, monitoring)
- [ ] Price trends over real community data (6+ months)
- [ ] Monthly reports, price alerts, recurring receipts
- [ ] Optional local OCR fallback (Tesseract) for photo scans without an API key

## Notes

- The app UI is German (target market DACH). Repository documentation is English.
- No third-party supermarket logos; only own SVG category icons and Open Food
  Facts images for exact EAN matches.
- See [`PLAN.md`](PLAN.md) for the full phase description and
  [`SECURITY_DEPLOYMENT.md`](SECURITY_DEPLOYMENT.md) for production.
