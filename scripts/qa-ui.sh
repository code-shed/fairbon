#!/usr/bin/env bash
# UI-Qualitätsprüfung: Draft-Guard-Lint + gerenderte Seite prüfen.
#
#   ./scripts/qa-ui.sh
#   QA_PORT=8300 ./scripts/qa-ui.sh
#
# Startet einen isolierten Server (temporäre DB, ohne Passwort), prüft `/` und
# `/admin` mit `detect`, lintet danach die Templates. Exit 0 = sauber,
# 1 = Findings, 2 = Werkzeug/Startfehler.
set -uo pipefail

ROOT="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
SKILL_DIR="${FRONTEND_SKILL_DIR:-$HOME/.agents/skills/frontend}"
GUARD="$SKILL_DIR/scripts/perfection/check-draft-guard.ts"
DETECT="$SKILL_DIR/scripts/detect/cli.ts"
BUN_BIN="${BUN:-bun}"

if ! command -v "$BUN_BIN" >/dev/null 2>&1; then
  echo "qa-ui: bun fehlt (wird für detect und check-draft-guard benötigt)." >&2
  exit 2
fi
if [ ! -f "$GUARD" ] || [ ! -f "$DETECT" ]; then
  echo "qa-ui: Frontend-Skill nicht gefunden unter $SKILL_DIR" >&2
  exit 2
fi
if [ ! -x "$ROOT/.venv/bin/uvicorn" ]; then
  echo "qa-ui: .venv fehlt – bitte einmalig 'uv sync' im Projekt ausführen." >&2
  exit 2
fi

port="${QA_PORT:-8250}"
is_busy() { ss -ltn 2>/dev/null | grep -q ":$1 "; }
for _ in $(seq 0 20); do
  is_busy "$port" || break
  port=$((port + 1))
done

tmpdir="$(mktemp -d /tmp/spv-qa.XXXXXX)"
log="$tmpdir/server.log"
pid=""

cleanup() {
  if [ -n "$pid" ]; then
    kill "$pid" 2>/dev/null || true
    wait "$pid" 2>/dev/null || true
  fi
  rm -rf "$tmpdir"
}
trap cleanup EXIT

echo "qa-ui: starte Server auf Port $port (temporäre Datenbank)"
(
  cd "$ROOT" || exit 1
  # exec: die Subshell wird zu uvicorn, damit `kill $pid` wirklich den Server trifft.
  exec env SITE_PASSWORD= SUPERMARKET_SITE_PASSWORD= \
    SUPERMARKET_DATABASE_PATH="$tmpdir/qa.db" \
    SUPERMARKET_HARVEST_ENABLED=false \
    ./.venv/bin/uvicorn supermarket_comparison.api.main:app \
      --host 127.0.0.1 --port "$port" >"$log" 2>&1
) &
pid=$!
pid=$!

ready=0
for _ in $(seq 1 40); do
  if curl -fsS "http://127.0.0.1:$port/health" >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 0.25
done
if [ "$ready" -ne 1 ]; then
  echo "qa-ui: Server startete nicht. Log:" >&2
  tail -20 "$log" >&2
  exit 2
fi

status=0

echo
echo "== check-draft-guard (statisch)"
"$BUN_BIN" "$GUARD" "$ROOT/supermarket_comparison/api/templates" || status=1

echo
echo "== detect (gerendert, 1440 + 390)"
for path in / /admin; do
  echo "-- $path"
  "$BUN_BIN" "$DETECT" "http://127.0.0.1:$port$path" || status=1
done

echo
if [ "$status" -eq 0 ]; then
  echo "qa-ui: sauber."
else
  echo "qa-ui: Findings vorhanden (siehe oben)."
fi
exit "$status"
