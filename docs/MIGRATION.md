# Migrating FairBon to another machine

This package is a complete but **clean** snapshot of the project: code, tests,
deployment files and a consistent database snapshot. Things bound to the old
machine (`.venv`, caches) are intentionally absent and are recreated on the new
machine.

## 1. What is included

```
fairbon/
├─ supermarket_comparison/     application (FastAPI, receipts, community)
├─ frontend/                   modular PWA (CSS, JS, manifest, service worker)
├─ tests/                      test suite incl. fixtures
├─ data/supermarkt.db          consistent SQLite snapshot
├─ docs/                       design/plan/migration docs
├─ Dockerfile, docker-compose.yml, SECURITY_DEPLOYMENT.md
├─ .env.example                template for passwords/vision keys
├─ start.sh                    local start without PATH fiddling
├─ pyproject.toml, uv.lock     reproducible dependencies
└─ README.md, PLAN.md, DESIGN.md
```

**Intentionally excluded:** `.venv/`, `__pycache__/`, `.pytest_cache/`,
`.ruff_cache/`, `data/*-wal`, `data/*-shm`, `.env` (secrets).

## 2. Set up on the new machine

Requirements: Linux/macOS with Python 3.12 (uv installs it if needed).

```bash
# 1. Install uv (if missing)
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"

# 2. Enter the project
cd ~/Projects/fairbon

# 3. Dependencies + virtual environment
uv sync --python 3.12

# 4. Start
./start.sh
# → http://localhost:8000/
```

`uv sync` recreates `.venv` and downloads Python 3.12 if necessary. There are
no machine-dependent paths in the code; the database path is relative
(`data/supermarkt.db`).

## 3. Database

`data/supermarkt.db` is a snapshot taken via the SQLite backup API (WAL already
checkpointed). Verify it:

```bash
sqlite3 data/supermarkt.db "PRAGMA integrity_check; SELECT COUNT(*) FROM products;"
```

If the new user has a different UID and writes fail:

```bash
sudo chown -R "$USER":"$USER" data
```

Create your own backup before changing data:

```bash
cp data/supermarkt.db data/supermarkt-before-migration.db
```

## 4. Password protection (optional, recommended)

```bash
cp .env.example .env
chmod 600 .env
# set SITE_PASSWORD, ADMIN_PASSWORD, SESSION_SECRET
./start.sh
```

Without `.env` the site is open. `/health` is always public.

## 5. What else may move from the old machine

| Item | Old path | Target |
|---|---|---|
| OpenCode agent `deepseek-worker` | `~/.opencode/agents/deepseek-worker.md` | same path (copy under `docs/opencode/`) |
| Frontend skill (only for `scripts/qa-ui.sh`) | `~/.agents/skills/frontend` | same path; otherwise skip the QA script |
| Your own `.env` | project folder | copy only if you had passwords/keys set |

## 6. Optional system packages

| Purpose | Package |
|---|---|
| Photo receipts (OCR fallback) | `tesseract-ocr`, `tesseract-ocr-deu` |
| Docker operation | Docker + Compose plugin |

## 7. Verify everything arrived

```bash
uv run pytest -q          # expected: all green
./start.sh                # health: http://localhost:8000/health
curl -s localhost:8000/health
```

## 8. Docker instead

See [`SECURITY_DEPLOYMENT.md`](../SECURITY_DEPLOYMENT.md):

```bash
mkdir -p data && chown -R 1000:1000 data
docker compose up -d --build
```
