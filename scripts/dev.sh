#!/usr/bin/env bash
# Development: FastAPI on 127.0.0.1:8001 and Next dev server on 8000 (open http://localhost:8000).
# Ctrl+C stops both.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

uv run delivery-analysis serve --no-browser --port 8001 --origin-port 8000 &
API_PID=$!
trap 'kill "$API_PID" 2>/dev/null; exit 130' INT TERM

[ -d web/node_modules ] || (cd web && npm ci)
(cd web && exec npm run dev) &
WEB_PID=$!

wait -n "$API_PID" "$WEB_PID"
status=$?
kill "$API_PID" "$WEB_PID" 2>/dev/null
wait 2>/dev/null
exit "$status"
