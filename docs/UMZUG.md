# Umzug auf einen anderen Rechner

Dieses Paket ist ein vollständiger, aber **sauberer** Stand des Projekts:
Code, Tests, Deployment-Dateien und ein konsistenter Datenbank-Snapshot.
Nicht enthalten sind Dinge, die auf dem alten Rechner gebunden sind
(`.venv`, Caches) — die werden auf dem neuen Rechner neu erzeugt.

## 1. Was im Paket ist

```
supermarket-comparison/
├─ supermarket_comparison/     Anwendung (FastAPI, Scraper, Storage)
├─ tests/                      Testsuite inkl. Fixtures
├─ scripts/qa-ui.sh            UI-Prüfung (optional, braucht bun + frontend-Skill)
├─ data/supermarkt.db          konsistenter Snapshot (Produkte, Preise, Historie)
├─ docs/                       Design, Pläne, diese Anleitung
├─ Dockerfile, docker-compose.yml, DEPLOY_SERVER.md
├─ .env.example                Vorlage für Passwort/Harvester
├─ start.sh                    Start ohne PATH-Gefummel
├─ pyproject.toml, uv.lock     Abhängigkeiten (reproduzierbar)
└─ README.md, DESIGN.md, TASKS.md
```

**Bewusst nicht enthalten:** `.venv/`, `__pycache__/`, `.pytest_cache/`,
`.ruff_cache/`, `data/*-wal`, `data/*-shm`, `.env` (Geheimnisse).

## 2. Auf dem neuen Rechner einrichten

Voraussetzungen: Linux/macOS mit Python 3.12 (uv installiert es notfalls selbst).

```bash
# 1. uv installieren (falls nicht vorhanden)
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"

# 3. ins Projekt wechseln
cd ~/supermarket-comparison

# 3. Abhängigkeiten + virtuelle Umgebung erzeugen
uv sync

# 4. Starten
./start.sh
# → http://localhost:8000/
```

`uv sync` legt `.venv` neu an und lädt Python 3.12 bei Bedarf nach. Es gibt
keine maschinenabhängigen Pfade im Code; der Datenbankpfad ist relativ
(`data/supermarkt.db`).

## 3. Datenbank

`data/supermarkt.db` ist ein Snapshot per SQLite-Backup-API (WAL bereits
eingecheckpointet). Er enthält alles, was zählt: Produkte, Preispunkte,
Preishistorie, Community-Meldungen, Suchtrends.

Prüfen:

```bash
sqlite3 data/supermarkt.db "PRAGMA integrity_check; SELECT COUNT(*) FROM products;"
```

Wenn der neue Benutzer eine andere UID hat und Schreibfehler auftreten:

```bash
sudo chown -R "$USER":"$USER" data
```

Eigene Sicherung anlegen (empfohlen, bevor Sie viel ändern):

```bash
cp data/supermarkt.db data/supermarkt-vor-umzug.db
```

## 4. Passwortschutz (optional, aber empfohlen)

```bash
cp .env.example .env
# SITE_PASSWORD und SESSION_SECRET setzen
nano .env
./start.sh
```

Ohne `.env` ist die Seite offen. `/health` bleibt immer frei.

## 5. Was noch vom alten Rechner mit muss

| Sache | Pfad alt | Ziel |
|---|---|---|
| OpenCode-Agent `deepseek-worker` | `~/.opencode/agents/deepseek-worker.md` | gleicher Pfad auf dem neuen Rechner (Kopie liegt unter `docs/opencode/`) |
| Frontend-Skill (nur für `scripts/qa-ui.sh`) | `~/.agents/skills/frontend` | gleich Pfad; sonst QA-Skript überspringen |
| Eigene `.env` | Projektordner | nur kopieren, wenn Sie Passwort/Keys gesetzt hatten |

Die Projekt-Wrapper `spv-guard`/`spv-detect` liegen in `~/.local/bin` und
verweisen auf den Frontend-Skill — auf dem neuen Rechner neu anlegen oder
weglassen.

## 6. Optionale Systempakete

| Zweck | Paket |
|---|---|
| Foto-Kassenbons (OCR) | `tesseract-ocr`, `tesseract-ocr-deu` |
| Docker-Betrieb | Docker + Compose-Plugin |

## 7. Prüfen, ob alles angekommen ist

```bash
uv run pytest -q          # erwartet: alle Tests grün
./start.sh                # health: http://localhost:8000/health
curl -s localhost:8000/health
```

## 8. Wenn Sie stattdessen Docker nutzen

```bash
mkdir -p data && chown -R 1000:1000 data
docker compose up -d --build
```

Das `./data`-Verzeichnis wird gemountet; der Snapshot bleibt erhalten.
Details: `DEPLOY_SERVER.md`.
