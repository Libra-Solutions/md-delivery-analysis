#!/usr/bin/env bash
# Start the whole app in one container: FastAPI (API only, 127.0.0.1:8001) and the Next server
# (pages, and a rewrite of /api/* to FastAPI) on $PORT. If either process exits, stop the other
# and exit non-zero so the host restarts the container.
#
# Environment:
#   PORT       port the Next server listens on (default 8000)
#   API_PORT   port FastAPI listens on (default 8001; the Next rewrite is built for 8001)
#   WEB_DIR    folder holding the Next standalone server.js
#              (default: /app/web-server in the image, else web/.next/standalone)
#   DA_CMD     command that runs the CLI (default: delivery-analysis)
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="${PORT:-8000}"
API_PORT="${API_PORT:-8001}"
DA_CMD="${DA_CMD:-delivery-analysis}"

if [ -z "${WEB_DIR:-}" ]; then
  if [ -f "$ROOT/web-server/server.js" ]; then WEB_DIR="$ROOT/web-server"; else WEB_DIR="$ROOT/web/.next/standalone"; fi
fi
if [ ! -f "$WEB_DIR/server.js" ]; then
  echo "start.sh: $WEB_DIR/server.js not found; run 'cd web && npm run build' first" >&2
  exit 2
fi
# Standalone output leaves out the browser assets and public files; put them beside server.js.
if [ ! -d "$WEB_DIR/.next/static" ] && [ -d "$ROOT/web/.next/static" ]; then
  mkdir -p "$WEB_DIR/.next" && cp -r "$ROOT/web/.next/static" "$WEB_DIR/.next/static"
fi
if [ ! -d "$WEB_DIR/public" ] && [ -d "$ROOT/web/public" ]; then
  cp -r "$ROOT/web/public" "$WEB_DIR/public"
fi

BIND_HOST=127.0.0.1 $DA_CMD serve --no-browser --port "$API_PORT" --origin-port "$PORT" &
API_PID=$!
WEB_PID=""

stop_all() {
  for pid in "$API_PID" "$WEB_PID"; do
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then kill "$pid" 2>/dev/null; fi
  done
}
trap 'stop_all; exit 143' TERM INT

# Wait up to 30 s for FastAPI to answer /api/version before starting Next.
ready=""
for _ in $(seq 1 30); do
  if ! kill -0 "$API_PID" 2>/dev/null; then break; fi
  if node -e "fetch('http://127.0.0.1:${API_PORT}/api/version').then(r=>process.exit(r.ok?0:1),()=>process.exit(1))" 2>/dev/null; then
    ready=1; break
  fi
  sleep 1
done
if [ -z "$ready" ]; then
  echo "start.sh: FastAPI did not answer /api/version within 30 s" >&2
  stop_all; wait 2>/dev/null
  exit 1
fi

(cd "$WEB_DIR" && HOSTNAME=0.0.0.0 PORT="$PORT" exec node server.js) &
WEB_PID=$!

wait -n "$API_PID" "$WEB_PID"
status=$?
stop_all
wait 2>/dev/null
[ "$status" -eq 0 ] && status=1
exit "$status"
