#!/usr/bin/env bash
# Startet den Supermarkt-Preisvergleich.
# Funktioniert aus jedem Verzeichnis, ohne uv/uvicorn im PATH.
#
#   ./start.sh              # http://localhost:8000/
#   PORT=8080 ./start.sh    # anderer Port
#   RELOAD=1 ./start.sh     # Auto-Reload für Entwicklung
set -euo pipefail

cd "$(dirname "$(readlink -f "$0")")"

if [ ! -x .venv/bin/uvicorn ]; then
  echo "Die virtuelle Umgebung fehlt. Einmalig einrichten:"
  echo "  cd \"$(pwd)\""
  echo "  ~/.local/bin/uv sync"
  exit 1
fi

# Optionale .env laden (Passwort, Harvester, Datenbankpfad ...)
if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi

HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8000}"
ARGS=(--host "$HOST" --port "$PORT")
if [ "${RELOAD:-0}" = "1" ]; then
  ARGS+=(--reload)
fi

echo "Supermarkt-Preisvergleich läuft auf http://localhost:${PORT}/"
if [ -n "${SITE_PASSWORD:-}" ]; then
  echo "Passwortschutz aktiv (SITE_PASSWORD gesetzt) – Login unter /login."
fi

exec ./.venv/bin/uvicorn supermarket_comparison.api.main:app "${ARGS[@]}" "$@"
