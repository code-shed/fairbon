#!/usr/bin/env bash
# Starts FairBon.
# Works from any directory, without uv/uvicorn on PATH.
#
#   ./start.sh              # http://localhost:8000/
#   PORT=8080 ./start.sh    # different port
#   RELOAD=1 ./start.sh     # auto-reload for development
set -euo pipefail

cd "$(dirname "$(readlink -f "$0")")"

if [ ! -x .venv/bin/uvicorn ]; then
  echo "The virtual environment is missing. Set it up once:"
  echo "  cd \"$(pwd)\""
  echo "  uv sync --python 3.12"
  exit 1
fi

# Load optional .env (passwords, vision keys, database path, ...)
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

echo "FairBon is running on http://localhost:${PORT}/"
if [ -n "${SITE_PASSWORD:-}" ]; then
  echo "Password protection active (SITE_PASSWORD set) – login at /login."
fi

exec ./.venv/bin/uvicorn supermarket_comparison.api.main:app "${ARGS[@]}" "$@"
