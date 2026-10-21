#!/usr/bin/env bash
# Start the demo server. Listens on 0.0.0.0 so tailnet peers can reach it.
set -euo pipefail
cd "$(dirname "$0")/.."
[ -d .venv ] && . .venv/bin/activate
PORT=$(grep -E '^PORT=' .env 2>/dev/null | cut -d= -f2 | cut -d' ' -f1); PORT=${PORT:-8080}
exec python -m uvicorn app.main:app --host 0.0.0.0 --port "$PORT"
