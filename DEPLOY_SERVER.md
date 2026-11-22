# Deployment (legacy)

This file described the pre-V1.0 Docker setup with the Marktguru harvester.

**The current, hardened production guide is
[`SECURITY_DEPLOYMENT.md`](SECURITY_DEPLOYMENT.md).**

Notes for V1.0:

- The weekly harvester and all leaflet-scraper variables (`HARVEST_*`,
  `MARKTGURU_*`, `KAUFDA_*`) are gone.
- The app container listens on `127.0.0.1:8000` only; put Caddy/Nginx in front.
- The SQLite database lives in `./data/supermarkt.db` (bind mount).
- Set `ADMIN_PASSWORD` explicitly; admin/moderation endpoints are fail-closed.
- The modular PWA frontend is served from `/` (`frontend/` is baked into the
  image via `SUPERMARKET_FRONTEND_DIR=/app/frontend`).

Quick start:

```bash
cp .env.example .env && chmod 600 .env   # set strong passwords
mkdir -p data && sudo chown -R 1000:1000 data
docker compose up -d --build
docker compose ps                        # healthy
curl -fsS http://127.0.0.1:8000/health
```
