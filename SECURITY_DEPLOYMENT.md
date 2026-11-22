# FairBon — Production Deployment & Security

Compact guide for a hardened production deployment. Target topology:

```
Internet ──► Cloudflare (optional, TLS/WAF) ──► Caddy (TLS, 3 MB limit)
                                                   │
                                                   ▼
                                    127.0.0.1:8000  FairBon (Docker, non-root)
                                                   │
                                                   ▼
                                        ./data/supermarkt.db (bind mount)
```

The app container is **only reachable on localhost**; TLS and the upload limit
are handled by the reverse proxy.

---

## 1. Prerequisites

- Linux VPS (Debian/Ubuntu), 1 vCPU / 1 GB RAM / 10 GB disk is enough.
- Docker + Compose plugin.
- A domain (optional, but recommended for TLS).

```bash
apt update && apt install -y docker.io docker-compose-plugin git ufw fail2ban
systemctl enable --now docker
```

## 2. Secrets & `.env`

```bash
cd /opt/fairbon
cp .env.example .env
chmod 600 .env
```

Required / recommended:

| Variable | Recommendation |
|---|---|
| `SITE_PASSWORD` | strong password (`openssl rand -base64 24`) |
| `SESSION_SECRET` | `openssl rand -base64 32` |
| `ADMIN_PASSWORD` | **separate** strong password (without it admin/moderation return 503) |
| `SUPERMARKET_CORS_ORIGINS` | exact origin, e.g. `https://fairbon.example.org` |
| `TRUST_PROXY` | `true` **only** behind Caddy/Cloudflare |
| `MAX_SCANS_PER_DAY_PER_IP` | default 15 |
| `MAX_GLOBAL_SCANS_PER_DAY` | default 500 (cost brake) |
| `VISION_PRIMARY_*` / `VISION_FALLBACK_*` | at least one provider + key |

> `ADMIN_PASSWORD` is fail-closed: if missing, `/admin`, backup/restore and
> moderation endpoints answer **503**. Wrong password → **401**. Comparison is
> constant-time (`hmac.compare_digest`).
>
> If `SITE_PASSWORD` is also set, `/admin` requires **both** gates: the site
> login cookie **and** HTTP Basic auth with `ADMIN_PASSWORD`. Browser flow:
> log in at `/login`, then open `/admin` and enter the admin password in the
> Basic-auth prompt. API clients: `POST /login` once, keep the cookie, then
> send the admin Basic header.

## 3. Start

```bash
mkdir -p data
sudo chown -R 1000:1000 data      # container runs as UID/GID 1000 (app)
docker compose up -d --build
docker compose ps                 # must show "healthy"
curl -fsS http://127.0.0.1:8000/health
```

`docker-compose.yml` already sets:

- `ports: 127.0.0.1:8000:8000` (no direct internet access)
- `mem_limit: 512m`, `read_only: true`, `tmpfs: /tmp`
- `security_opt: no-new-privileges:true`, `cap_drop: ALL`
- `restart: unless-stopped`, `stop_grace_period: 30s`
- persistent `./data` volume (SQLite + WAL)

## 4. Reverse Proxy (Caddy)

`/etc/caddy/Caddyfile`:

```caddy
fairbon.example.org {
    encode gzip zstd

    # Hard cap for photo/PDF uploads (the app additionally enforces 3 MB).
    request_body {
        max_size 3MB
    }

    header {
        Strict-Transport-Security "max-age=31536000; includeSubDomains"
    }

    reverse_proxy 127.0.0.1:8000
}
```

```bash
systemctl reload caddy
```

Caddy obtains TLS certificates automatically. The app also sets
`X-Content-Type-Options`, `X-Frame-Options: DENY`, `Referrer-Policy`,
`Permissions-Policy` and a restrictive `Content-Security-Policy`.

## 5. Cloudflare + Turnstile (optional)

1. Add the domain to Cloudflare and enable the proxy (orange cloud).
2. Create a **Turnstile** widget → put site/secret keys in `.env`:
   `TURNSTILE_SITE_KEY`, `TURNSTILE_SECRET_KEY`.
3. Set `TRUST_PROXY=true` so `CF-Connecting-IP` is used for rate limiting.
4. Without Turnstile keys the bot protection is skipped cleanly.

## 6. Firewall & fail2ban

```bash
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw enable
```

- **Never expose port 8000 publicly** — it is bound to `127.0.0.1`.
- fail2ban: enable the `sshd` jail (`/etc/fail2ban/jail.local`), optionally a
  Caddy log jail for repeated 4xx/429.

## 7. Backups

The SQLite database is the core asset. Recommended: daily backups plus a weekly
restore test.

**Option A — admin API (consistent, WAL-safe):**

```bash
curl -fsS -u admin:"$ADMIN_PASSWORD" \
  https://fairbon.example.org/api/v1/system/backup-db \
  -o "/backup/fairbon-$(date +%F).db"
```

**Option B — local SQLite backup:**

```bash
sqlite3 /opt/fairbon/data/supermarkt.db \
  ".backup '/backup/fairbon-$(date +%F).db'"
```

Then copy offsite (e.g. `restic`, `rclone`) and apply retention
(7 daily / 4 weekly). `data/` permissions: `1000:1000`.

## 8. Monitoring

- UptimeRobot (or similar): HTTPS monitor on
  `https://fairbon.example.org/health`, keyword `"status":"ok"`.
- `/health` is deliberately reachable **without auth**.
- A Docker healthcheck is built in (`docker compose ps`).

## 9. Updates

```bash
cd /opt/fairbon
git pull
docker compose up -d --build
docker compose ps
curl -fsS http://127.0.0.1:8000/health
```

Take a backup first. The service-worker cache is invalidated via the `CACHE`
version in `frontend/sw.js`; bump it on frontend changes.

## 10. Cost & abuse protection

- Photo scan: **3/minute** and **15/day per IP** (configurable), plus a global
  daily cap (`MAX_GLOBAL_SCANS_PER_DAY`, default 500).
- BYOK (`X-User-Vision-Key`) bypasses server-side limits; the key is never
  stored or logged.
- eBon/PDF/text import runs **locally** and consumes no API budget.
- Uploads: magic-byte validation (JPEG/PNG/WebP/PDF), 3 MB limit,
  Pillow re-encoding in RAM (EXIF/GPS stripped), decompression-bomb guard.

## 11. Privacy & legal

- No leaflet/supermarket scrapers, no third-party logos or leaflet images.
- Receipts stay local (guest token in the browser); no account, no tracking.
- Community prices only with **explicit opt-in**, without `owner_token` and
  without `receipt_id`; demo receipts are excluded server-side.
- Price plausibility checks + quarantine (`pending_review`) prevent outliers.
- No card data, IBAN remnants, loyalty-card numbers or TSE data.

## 12. Go-live checklist

- [ ] `.env` with strong, unique passwords, `chmod 600`
- [ ] `ADMIN_PASSWORD` set, `/admin` tested (401 without, 200 with)
- [ ] Caddy with TLS, `max_body_size 3MB`, HSTS
- [ ] `ufw` active, port 8000 not public
- [ ] `docker compose ps` → healthy
- [ ] UptimeRobot on `/health`
- [ ] Backup job + restore test
- [ ] `SITE_PASSWORD`/`STEALTH_MODE` set deliberately
- [ ] Vision provider keys set, or photo scan disabled (eBon/text always works)

## 13. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `/admin` → 503 | `ADMIN_PASSWORD` missing → set it in `.env`, restart |
| `/admin` → 401 | wrong Basic-auth password; username is arbitrary |
| 429 on scan | IP/day limit or global cap reached; use BYOK or eBon |
| 413 on upload | file > 3 MB (app or Caddy `request_body`) |
| 502 on scan | vision provider unreachable/misconfigured; see `docker compose logs app` |
| `database is locked` | WAL + `busy_timeout=5000` are active; avoid parallel backups |
| write errors on `data/` | `sudo chown -R 1000:1000 data` |
| frontend 404 | `frontend/` must be in the image (`SUPERMARKET_FRONTEND_DIR=/app/frontend`) |
