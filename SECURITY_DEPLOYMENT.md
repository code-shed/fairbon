# FairBon — Production Deployment & Security

Kompakte Anleitung für einen produktiven, gehärteten Betrieb. Zielbild:

```
Internet ──► Cloudflare (optional, TLS/WAF) ──► Caddy (TLS, 3-MB-Limit)
                                                   │
                                                   ▼
                                    127.0.0.1:8000  FairBon (Docker, non-root)
                                                   │
                                                   ▼
                                        ./data/supermarkt.db (bind mount)
```

Der App-Container ist **nur auf localhost** erreichbar; TLS und das Upload-Limit
übernimmt der Reverse Proxy.

---

## 1. Voraussetzungen

- Linux-VPS (Debian/Ubuntu), 1 vCPU / 1 GB RAM / 10 GB Disk reichen.
- Docker + Compose-Plugin.
- Domain (optional, aber für TLS empfohlen).

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

Pflicht/Vernunft:

| Variable | Empfehlung |
|---|---|
| `SITE_PASSWORD` | starkes Passwort (`openssl rand -base64 24`) |
| `SESSION_SECRET` | `openssl rand -base64 32` |
| `ADMIN_PASSWORD` | **eigenes**, starkes Passwort (ohne → Admin/Moderation 503) |
| `SUPERMARKET_CORS_ORIGINS` | exakte Origin, z. B. `https://fairbon.example.org` |
| `TRUST_PROXY` | `true` **nur** hinter Caddy/Cloudflare |
| `MAX_SCANS_PER_DAY_PER_IP` | Default 15 |
| `MAX_GLOBAL_SCANS_PER_DAY` | Default 500 (Kostenbremse) |
| `VISION_PRIMARY_*` / `VISION_FALLBACK_*` | mindestens ein Provider + Key |

> `ADMIN_PASSWORD` ist fail-closed: Fehlt es, antworten `/admin`,
> Backup/Restore und die Moderations-Endpunkte mit **503**. Falsches Passwort
> → **401**. Der Vergleich ist constant-time (`hmac.compare_digest`).

## 3. Start

```bash
mkdir -p data
sudo chown -R 1000:1000 data      # Container läuft als UID/GID 1000 (app)
docker compose up -d --build
docker compose ps                 # muss "healthy" zeigen
curl -fsS http://127.0.0.1:8000/health
```

Die Compose-Datei setzt bereits:

- `ports: 127.0.0.1:8000:8000` (kein direkter Internet-Zugriff)
- `mem_limit: 512m`, `read_only: true`, `tmpfs: /tmp`
- `security_opt: no-new-privileges:true`, `cap_drop: ALL`
- `restart: unless-stopped`, `stop_grace_period: 30s`
- persistentes `./data`-Volume (SQLite + WAL)

## 4. Reverse Proxy (Caddy)

`/etc/caddy/Caddyfile`:

```caddy
fairbon.example.org {
    encode gzip zstd

    # Harte Obergrenze für Foto-/PDF-Uploads (App prüft zusätzlich 3 MB).
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

Caddy holt TLS-Zertifikate automatisch. Die App setzt zusätzlich
`X-Content-Type-Options`, `X-Frame-Options: DENY`, `Referrer-Policy`,
`Permissions-Policy` und eine restriktive `Content-Security-Policy`.

## 5. Cloudflare + Turnstile (optional)

1. Domain in Cloudflare anlegen, Proxy (orange Wolke) aktivieren.
2. **Turnstile** → Widget erstellen → Site-/Secret-Key in `.env`:
   `TURNSTILE_SITE_KEY`, `TURNSTILE_SECRET_KEY`.
3. `TRUST_PROXY=true` setzen, damit `CF-Connecting-IP` fürs Rate-Limiting zählt.
4. Ohne Turnstile-Keys wird der Bot-Schutz sauber übersprungen.

## 6. Firewall & fail2ban

```bash
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw enable
```

- **Port 8000 niemals öffentlich öffnen** — er ist an `127.0.0.1` gebunden.
- fail2ban: `sshd`-Jail aktivieren (`/etc/fail2ban/jail.local`), optional
  ein Caddy-Log-Jail für wiederholte 4xx/429.

## 7. Backups

Die SQLite-DB ist das Herzstück. Empfohlen: tägliches Backup + wöchentlicher
Restore-Test.

**Variante A — Admin-API (konsistent, WAL-safe):**

```bash
curl -fsS -u admin:"$ADMIN_PASSWORD" \
  https://fairbon.example.org/api/v1/system/backup-db \
  -o "/backup/fairbon-$(date +%F).db"
```

**Variante B — lokal per SQLite-Backup:**

```bash
sqlite3 /opt/fairbon/data/supermarkt.db \
  ".backup '/backup/fairbon-$(date +%F).db'"
```

Danach offsite kopieren (z. B. `restic`, `rclone`) und Aufbewahrung
(7 täglich / 4 wöchentlich) regeln. `data/`-Rechte: `1000:1000`.

## 8. Monitoring

- UptimeRobot (oder ähnlich): HTTPS-Monitor auf
  `https://fairbon.example.org/health`, Keyword `"status":"ok"`.
- `/health` ist bewusst **ohne Auth** erreichbar.
- Docker-Healthcheck ist eingebaut (`docker compose ps`).

## 9. Updates

```bash
cd /opt/fairbon
git pull
docker compose up -d --build
docker compose ps
curl -fsS http://127.0.0.1:8000/health
```

Vorher ein Backup ziehen. Der Service-Worker-Cache wird über die
`CACHE`-Version in `frontend/sw.js` invalidiert; bei Frontend-Änderungen
die Version erhöhen.

## 10. Kosten- & Missbrauchsschutz

- Foto-Scan: **3/Minute** und **15/Tag pro IP** (konfigurierbar), zusätzlich
  globaler Tagesdeckel (`MAX_GLOBAL_SCANS_PER_DAY`, Default 500).
- BYOK (`X-User-Vision-Key`) umgeht die serverseitigen Limits; der Key wird
  nie gespeichert oder geloggt.
- eBon-/PDF-/Text-Import läuft **lokal** und verbraucht kein API-Budget.
- Uploads: Magic-Byte-Prüfung (JPEG/PNG/WebP/PDF), 3-MB-Limit,
  Pillow-Re-Encoding im RAM (EXIF/GPS werden entfernt), Decompression-Bomb-Guard.

## 11. Datenschutz & Recht

- Keine Prospekt-/Supermarkt-Scraper, keine fremden Logos oder Prospektbilder.
- Kassenbons bleiben lokal (Gast-Token im Browser); kein Account, kein Tracking.
- Community-Preise nur bei **explizitem Opt-in**, ohne `owner_token` und ohne
  `receipt_id`; Demo-Bons werden serverseitig vom Community-Pool ausgeschlossen.
- Preis-Plausibilität + Quarantäne (`pending_review`) verhindern Ausreißer.
- Keine EC-/Kartendaten, IBAN-Reste, Payback-/Kundennummern oder TSE-Daten.

## 12. Checkliste vor Go-Live

- [ ] `.env` mit starken, einzigartigen Passwörtern, `chmod 600`
- [ ] `ADMIN_PASSWORD` gesetzt, `/admin` getestet (401 ohne, 200 mit)
- [ ] Caddy mit TLS, `max_body_size 3MB`, HSTS
- [ ] `ufw` aktiv, Port 8000 nicht öffentlich
- [ ] `docker compose ps` → healthy
- [ ] UptimeRobot auf `/health`
- [ ] Backup-Job + Restore-Test
- [ ] `SITE_PASSWORD`/`STEALTH_MODE` bewusst gesetzt
- [ ] Vision-Provider-Keys gesetzt oder Foto-Scan deaktiviert (eBon/Text geht immer)

## 13. Troubleshooting

| Symptom | Ursache / Lösung |
|---|---|
| `/admin` → 503 | `ADMIN_PASSWORD` fehlt → in `.env` setzen, Container neu starten |
| `/admin` → 401 | Basic-Auth-Passwort falsch; Benutzername ist beliebig |
| 429 beim Scan | IP-/Tageslimit oder globaler Deckel erreicht; BYOK oder eBon nutzen |
| 413 beim Upload | Datei > 3 MB (App oder Caddy `request_body`) |
| 502 beim Scan | Vision-Provider nicht erreichbar/konfiguriert; `docker compose logs app` |
| `database is locked` | WAL + `busy_timeout=5000` sind aktiv; parallele Backups vermeiden |
| Schreibfehler auf `data/` | `sudo chown -R 1000:1000 data` |
| Frontend 404 | `frontend/` muss im Image sein (`SUPERMARKET_FRONTEND_DIR=/app/frontend`) |
