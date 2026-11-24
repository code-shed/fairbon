# FairBon — Production Deployment & Security

Compact guide for a hardened production deployment on **Ubuntu 24.04 LTS**.
Target topology:

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

- VPS with 1 vCPU / 1 GB RAM / 10 GB disk (Ubuntu 24.04 LTS).
- Docker + Compose plugin, Caddy and fail2ban.
- A domain (optional, but strongly recommended for TLS).

```bash
apt update
apt install -y docker.io docker-compose-plugin git ufw fail2ban caddy
# On a stripped-down image, install Caddy on its own first:
apt install -y caddy
systemctl enable --now docker caddy fail2ban
```

If your Ubuntu mirror does not provide Caddy, install it from the official
Caddy repository first, then re-run the command above.

## 2. Secrets & `.env`

```bash
cd /opt/fairbon
cp .env.example .env
chmod 600 .env
```

Required / recommended:

| Variable | Recommendation |
|---|---|
| `SITE_PASSWORD` | strong, unique password (`openssl rand -base64 24`) |
| `SESSION_SECRET` | `openssl rand -base64 32` |
| `ADMIN_PASSWORD` | **separate** strong password (without it admin/moderation return 503) |
| `SUPERMARKET_CORS_ORIGINS` | exact origin, e.g. `https://fairbon.example.org` |
| `TRUST_PROXY` | `true` **only** behind Caddy/Cloudflare |
| `MAX_SCANS_PER_DAY_PER_IP` | default 15 |
| `MAX_GLOBAL_SCANS_PER_DAY` | default 500 (cost brake) |
| `VISION_PRIMARY_*` / `VISION_FALLBACK_*` | at least one provider + key |
| `VISION_OPENAI_BASE_URL` | only for `openai_compatible` providers (local endpoint) |

`ADMIN_PASSWORD` is fail-closed: if missing, `/admin`, backup/restore and
moderation endpoints answer **503**; wrong password → **401**. Comparison uses
`hmac.compare_digest`.

If `SITE_PASSWORD` is set, all non-public paths require the site login first.

## 3. Start

```bash
mkdir -p data
sudo chown -R 1000:1000 data      # container runs as UID/GID 1000 (app)
chmod 600 data/supermarkt.db      # DB is the core asset, not world-readable
docker compose up -d --build
docker compose ps                 # must show "healthy"
curl -fsS http://127.0.0.1:8000/health
```

`docker-compose.yml` already sets:

- `ports: 127.0.0.1:8000:8000` (no direct internet access)
- `cpus: "1.0"`, `mem_limit: 512m`, `read_only: true`, `tmpfs: /tmp`
- Docker log rotation: `json-file`, `max-size: "10m"`, `max-file: "5"`
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

Caddy obtains TLS certificates automatically. The app additionally sets
`X-Content-Type-Options`, `X-Frame-Options: DENY`, `Referrer-Policy`,
`Permissions-Policy` and a `Content-Security-Policy`.

**CSP status (checked):** the policy still contains
`style-src 'self' 'unsafe-inline'` and `script-src 'self' 'unsafe-inline'`.
It konnte **nicht entfernt werden**, because the standalone login and admin
templates ship inline `<style>`/`<script>` blocks. The modular PWA itself uses
only external scripts and `textContent`-based DOM building. Externalising those
two templates is the clean follow-up; until then do not drop `'unsafe-inline'`
without rewriting them.

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

**Never expose port 8000 publicly** — it is bound to `127.0.0.1`.

`/etc/fail2ban/jail.local` (minimal starting point):

```ini
[DEFAULT]
bantime  = 1h
findtime = 10m
maxretry = 5
backend  = systemd

[sshd]
enabled = true

[caddy]
enabled  = true
port     = http,https
logpath  = /var/log/caddy/access.log
maxretry = 5
```

Create `/var/log/caddy` and make Caddy log to a file if you enable that jail.
Then `systemctl restart fail2ban`.

## 7. Admin-Zugang

The admin entry is **deliberately absent from the normal settings sheet**. It
is documented here only, for the operator:

1. Log in normally at `/login` with `SITE_PASSWORD` (site gate).
2. Open `https://fairbon.example.org/admin/login` and enter `ADMIN_PASSWORD`.
3. This sets the separate `spv_admin_session` cookie (`HttpOnly`,
   `SameSite=Strict`, `Secure` whenever TLS is detected) and redirects to
   `/admin`. The Basic-auth gate remains as a second layer for API clients.
4. `POST /admin/logout` clears the admin session.

Without `ADMIN_PASSWORD` the whole admin area stays disabled (503).

## 8. Backups

The SQLite database is the core asset: daily backups plus a weekly restore
test. The admin API is WAL-safe and consistent; it requires **two gates**, so
the legacy one-liner with only `ADMIN_PASSWORD` does not work.

Use this script (no secrets in the process list or shell history; values are
loaded from `.env` in a subshell and passed via files/`--netrc-file`):

```bash
#!/usr/bin/env bash
set -euo pipefail
umask 077
cd /opt/fairbon
set -a; . ./.env; set +a

jar=$(mktemp); pw=$(mktemp); netrc=$(mktemp)
trap 'rm -f "$jar" "$pw" "$netrc"' EXIT
printf '%s' "$SITE_PASSWORD" > "$pw"

# 1) Site login (303) -> cookie jar
curl -sS -o /dev/null -c "$jar" \
  --data-urlencode "password@$pw" \
  --data-urlencode "next=/" \
  -w '%{http_code}' https://fairbon.example.org/login | grep -q '303'

# 2) Admin Basic auth via netrc file, using the site cookie
printf 'machine fairbon.example.org login admin password %s\n' \
  "$ADMIN_PASSWORD" > "$netrc"
curl -fsS -b "$jar" --netrc-file "$netrc" \
  https://fairbon.example.org/api/v1/system/backup-db \
  -o "/backup/fairbon-$(date +%F).db"
```

Local alternative (no HTTP gates involved):

```bash
sqlite3 /opt/fairbon/data/supermarkt.db \
  ".backup '/backup/fairbon-$(date +%F).db'"
```

Copy offsite (e.g. `restic`, `rclone`) and keep 7 daily / 4 weekly backups.

**Timer** — `/etc/systemd/system/fairbon-backup.service`:

```ini
[Unit]
Description=FairBon SQLite backup

[Service]
Type=oneshot
WorkingDirectory=/opt/fairbon
ExecStart=/usr/local/bin/fairbon-backup.sh
```

`/etc/systemd/system/fairbon-backup.timer`:

```ini
[Unit]
Description=Daily FairBon backup

[Timer]
OnCalendar=daily
Persistent=true

[Install]
WantedBy=timers.target
```

```bash
systemctl daemon-reload
systemctl enable --now fairbon-backup.timer
systemctl list-timers fairbon-backup.timer
```

Perform a **restore test weekly** into a throwaway database; the export/import
in the app settings covers user data, `POST /api/v1/system/restore-db` covers
the full server database.

## 9. Monitoring & log rotation

- UptimeRobot (or similar): HTTPS monitor on
  `https://fairbon.example.org/health`, keyword `"status":"ok"`.
- `/health` is deliberately reachable **without** the site password.
- Docker healthcheck + `json-file` rotation are built in.
- Caddy logs: `/etc/logrotate.d/caddy`:

```text
/var/log/caddy/*.log {
    daily
    rotate 14
    compress
    missingok
    notifempty
    create 0640 www-data adm
}
```

- Journald: `SystemMaxUse=200M` in `/etc/systemd/journald.conf.d/limits.conf`.

## 10. Updates

```bash
cd /opt/fairbon
git pull
docker compose up -d --build
docker compose ps
curl -fsS http://127.0.0.1:8000/health
```

Take a backup first. The service-worker cache version is
`CACHE` in `frontend/sw.js`; it must be bumped whenever shell assets change
(the CI does not do this automatically).

## 11. Cost & abuse protection

- Photo scan: **3/minute** and **15/day per IP** (configurable), plus a global
  daily cap (`MAX_GLOBAL_SCANS_PER_DAY`, default 500).
- BYOK (`X-User-Vision-Key`) bypasses server-side limits; the key is never
  stored or logged.
- eBon/PDF/text import is parsed on the server without an external AI API and
  consumes no vision budget.
- Uploads: magic-byte validation (JPEG/PNG/WebP/PDF), 3 MB limit,
  Pillow re-encoding in RAM (EXIF/GPS stripped), decompression-bomb guard.

## 12. Privacy & legal

- No leaflet/supermarket scrapers, no third-party logos or leaflet images.
- Receipts stay in the browser (random guest token); no account, no tracking.
- Community prices have no `owner_token` and no `receipt_id`; demo receipts
  are excluded server-side.
- Price plausibility checks + quarantine (`pending_review`) prevent outliers.
- No card data, IBAN remnants, loyalty-card numbers or TSE data.

## 13. Go-live checklist

- [ ] `.env` with strong, unique passwords, `chmod 600`
- [ ] `chmod 600 data/supermarkt.db`, owner `1000:1000`
- [ ] `ADMIN_PASSWORD` set; `/admin/login` tested (303 + cookie → 200)
- [ ] Caddy with TLS, `request_body { max_size 3MB }`, HSTS
- [ ] `ufw` active, port 8000 not public
- [ ] fail2ban `jail.local` active (sshd + Caddy)
- [ ] Docker log rotation and Caddy/journald logrotate configured
- [ ] `docker compose ps` → healthy
- [ ] UptimeRobot on `/health`
- [ ] Backup timer enabled **and** a restore test performed
- [ ] `SITE_PASSWORD`/`STEALTH_MODE` set deliberately
- [ ] Vision provider keys set, or photo scan disabled (eBon/text always works)
- [ ] `PRIVACY_TEST_MODE=false` and real `IMPRINT_*`/`PRIVACY_*` values filled on the server

## 14. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `/admin` → 503 | `ADMIN_PASSWORD` missing → set it in `.env`, restart |
| `/admin` → 401 | no admin session / wrong Basic password → use `/admin/login` |
| 429 on scan | IP/day limit or global cap reached; use BYOK or eBon |
| 413 on upload | file > 3 MB (app or Caddy `request_body`) |
| 502 on scan | vision provider unreachable/misconfigured; see `docker compose logs app` |
| `database is locked` | WAL + `busy_timeout=5000` are active; avoid parallel backups |
| write errors on `data/` | `sudo chown -R 1000:1000 data` |
| frontend 404 | `frontend/` must be in the image (`SUPERMARKET_FRONTEND_DIR=/app/frontend`) |
