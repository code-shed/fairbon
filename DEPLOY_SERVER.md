> **Hinweis (V1.0):** Diese Datei beschreibt den historischen Docker-Betrieb.
> Für den aktuellen, gehärteten Produktivbetrieb gilt
> **[`SECURITY_DEPLOYMENT.md`](SECURITY_DEPLOYMENT.md)** (Reverse Proxy,
> Upload-Limit, Turnstile, Backups, Firewall). Die früheren Harvester-/
> Marktguru-Variablen sind entfallen.

# Deployment auf einem Server

Die App laeuft als Docker-Container – identisch bei **Hostinger VPS, Hetzner,
Netcup und Strato**. Unterschiede gibt es nur bei Panel, Firewall und
Servernamen. OCR (Tesseract/Deutsch), Python 3.12 und alle Abhaengigkeiten
stecken im Image; auf dem Host ist nur Docker noetig.

## 1. Was du brauchst

- **VPS** mit Debian/Ubuntu und root-Zugang per SSH (1 vCPU, 1 GB RAM, 10 GB
  Disk reichen; OCR braucht kurz etwas CPU).
- **Docker + Compose-Plugin** (wird unten installiert) und die **Repo-URL**
  bzw. ein Upload per SFTP/`scp` (ohne `.venv/`, `data/`, `.env`). **Domain**
  optional: ohne Domain laeuft alles unter `http://SERVER-IP:8000`.

## 2. In 5 Minuten live (Docker)

Als root per SSH:

```bash
apt update && apt install -y docker.io docker-compose-plugin git
systemctl enable --now docker
git clone <REPO-URL> /opt/supermarkt && cd /opt/supermarkt
cp .env.example .env && nano .env
mkdir -p data && chown -R 1000:1000 data
docker compose up -d --build
docker compose ps
```

In `.env` mindestens `SITE_PASSWORD`, `SESSION_SECRET` (`openssl rand -base64 32`) und `HARVEST_ZIPS` setzen:

```bash
curl -fsS http://127.0.0.1:8000/health          # {"status":"ok",...}
docker compose logs -f app                      # Strg+C beendet nur das Log
```

`docker compose ps` muss `healthy` zeigen. Der Container laeuft als UID/GID
`1000` (`app`), daher gehoert `data/` dem Benutzer 1000. Fehlt das Compose-Plugin:
`curl -fsSL https://get.docker.com | sh`.

**Update:** `git pull && docker compose up -d --build`
(ohne Git: Dateien per SFTP ersetzen, dann derselbe Befehl).

## 3. Host-spezifische Hinweise

- **Hostinger VPS:** hPanel → VPS → **SSH-Zugang** (root, Port 22). Ports
  **22, 80, 443** in der hPanel-Firewall bzw. per `ufw` oeffnen.
- **Hetzner Cloud:** Server anlegen (CX22 genuegt), in der **Cloud-Firewall**
  inbound 22/80/443 freigeben; SSH-Key statt Passwort empfohlen.
- **Netcup:** Zugang ueber das **Servercontrol-Panel (SCP)**, root-Login per
  SSH; zusaetzliche IPv4 im SCP bestellen, Firewall dort bzw. per `ufw` setzen.
- **Strato:** **Power-Server** mit Root-Zugang; Verwaltung im Kundenbereich,
  Ports 22/80/443 in der Strato-Firewall freigeben (ggf. Passwort-Login aktivieren).

## 4. Passwort & Stealth

- **Login:** `https://DEINE-DOMAIN/login`, Passwort = `SITE_PASSWORD`, Session 30 Tage.
- **API:** HTTP Basic Auth, Benutzername beliebig, Passwort = `SITE_PASSWORD`:
  ```bash
  curl -u x:DEIN_PASSWORT https://DEINE-DOMAIN/api/v1/products/search?query=butter
  curl -i https://DEINE-DOMAIN/api/v1/products/search   # 401 + WWW-Authenticate
  ```
- **Oeffentlich bleiben:** `/health`, `/login`, `/logout`, `/robots.txt`,
  `/docs`, `/openapi.json`; alles andere ist gesperrt, solange
  `SITE_PASSWORD` gesetzt ist. Leer = Seite ist offen.
- **`STEALTH_MODE=true`**: `X-Robots-Tag: noindex, nofollow, noarchive`, `robots.txt` mit `Disallow: /`, Noindex-Meta im HTML.
- **`SESSION_SECRET`** signiert das Login-Cookie; leer = aus dem Passwort
  abgeleitet (Passwortwechsel loggt alle aus). `.env`-Aenderung: `docker compose up -d`.

## 5. Backup & Umzug in 2 Minuten

**Backup** (Browser oder curl): `https://DEINE-DOMAIN/api/v1/system/backup-db`
speichert eine `.db`-Datei, z. B. `supermarkt-2026-11-05.db`:

```bash
curl -u x:DEIN_PASSWORT -OJ https://DEINE-DOMAIN/api/v1/system/backup-db
```

**Auf dem neuen Server einspielen** (Code + `.env` liegen dort schon):

```bash
docker compose up -d
# Multipart-Feld heisst "file":
curl -u x:DEIN_PASSWORT -F "file=@supermarkt-2026-11-05.db" \
  https://NEUE-DOMAIN/api/v1/system/restore-db
```

Der Restore legt vorher automatisch `supermarkt.db.bak-<timestamp>` an.

**Alternativ die Datei direkt ersetzen** (z. B. per `scp`):
```bash
docker compose stop app                 # sauberer Stopp (30 s Grace)
cp supermarkt-2026-11-05.db data/supermarkt.db
rm -f data/supermarkt.db-wal data/supermarkt.db-shm
chown 1000:1000 data/supermarkt.db
docker compose start app
```
`-wal`/`-shm` nur bei gestopptem Container loeschen. Optional den Mount
`./backups:/app/backups` in `docker-compose.yml` aktivieren.

## 6. Harvester

Der Sammellauf startet automatisch **3x/Woche (Mo/Do/Sa, 04:00 Europe/Berlin)**;
Steuerung in `.env`:

```bash
HARVEST_ENABLED=true
HARVEST_DAYS=mon,thu,sat     # auch: tue,wed,fri,sun
HARVEST_HOUR=4               # 0-23
HARVEST_ZIPS=65618,56307
HARVEST_LIMIT=1000
```

`SUPERMARKET_HARVEST_DAYS` und `SUPERMARKET_HARVEST_HOUR` wirken ebenfalls
(Praefix hat Vorrang). Status und manueller Lauf:

```bash
curl -u x:PASSWORT https://DEINE-DOMAIN/api/v1/system/harvest-status
curl -u x:PASSWORT -X POST https://DEINE-DOMAIN/api/v1/system/harvest
```

Status: `last_run`, `next_run`, `scheduler_running`, `enabled`, `zips`. CLI statt Scheduler:

```bash
docker compose exec app python -m supermarket_comparison.cli harvest
docker compose exec app python -m supermarket_comparison.cli harvest --zip 65618 --limit 200 --json
```

Cron-Alternative (Host-Cron, falls der interne Scheduler deaktiviert ist):
```
0 4 * * 1,4,6 cd /opt/supermarkt && docker compose exec -T app python -m supermarket_comparison.cli harvest >> harvest.log 2>&1
```

## 7. HTTPS

**Caddy** (Let's Encrypt): `apt install -y caddy`, Datei
`/etc/caddy/Caddyfile`, danach `systemctl reload caddy`:
```
DEINE-DOMAIN {
    reverse_proxy 127.0.0.1:8000
}
```
**nginx-Kurzform** (`/etc/nginx/sites-available/supermarkt`):
```
server_name DEINE-DOMAIN;
location / { proxy_pass http://127.0.0.1:8000; proxy_set_header Host $host; }
```
Danach `certbot --nginx -d DEINE-DOMAIN` (nginx + certbot vorher installieren);
Port 8000 bleibt lokal, oeffentlich nur 80/443.

## 8. Troubleshooting

| Problem | Loesung |
| --- | --- |
| Container `unhealthy` | `docker compose logs --tail=100 app`; `curl -v http://127.0.0.1:8000/health`; Port 8000 belegt? `ss -tlnp \| grep 8000`. |
| Ueberall `401` | `SITE_PASSWORD` gesetzt? Login unter `/login` bzw. `curl -u x:PASSWORT`. Cookies im Browser loeschen, `SESSION_SECRET` pruefen. |
| OCR-Bild → `503` | `docker compose exec app tesseract --list-langs` (muss `deu` zeigen) und `docker compose exec app python -c "import pytesseract, PIL"`. Sonst Image neu bauen. |
| `readonly database` / `locked` | `docker compose stop app && chown -R 1000:1000 data && docker compose start app`; `ls -ln data` muss UID/GID 1000 zeigen. |
| `data/` leer nach Rebuild | Falscher Mount: in `docker-compose.yml` muss `./data:/app/data` stehen, und der Start erfolgt im Projektordner (dort liegt `./data`). |
| `uv sync --frozen` bricht ab | `uv.lock` passt nicht zu `pyproject.toml`: lokal `uv lock`, committen, Image neu bauen. |
