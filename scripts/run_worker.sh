#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

if [ -f "$ROOT/.env.local" ]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env.local"
  set +a
fi

export SUPABASE_DEV_DB_URL="${SUPABASE_DEV_DB_URL:-}"
# shellcheck disable=SC1091
source "$ROOT/set_db_env.sh"

export DEPLOYMENT_TARGET="${DEPLOYMENT_TARGET:-worker}"
export PORT="${PORT:-8000}"

cd "$ROOT/backend"

echo "worker: starting Gunicorn on :${PORT}"
"$ROOT/.venv/bin/python" -m gunicorn mendreo.wsgi \
  --bind "0.0.0.0:${PORT}" \
  --workers 2 \
  --timeout 300 \
  --access-logfile - \
  --error-logfile - &
WEB_PID=$!

echo "worker: starting Celery worker"
"$ROOT/.venv/bin/python" -m celery -A mendreo worker --loglevel=info --concurrency=2 &
WORKER_PID=$!

echo "worker: starting Celery beat"
"$ROOT/.venv/bin/python" -m celery -A mendreo beat --loglevel=info &
BEAT_PID=$!

trap 'kill "$WEB_PID" "$WORKER_PID" "$BEAT_PID" 2>/dev/null || true' EXIT INT TERM

wait -n "$WEB_PID" "$WORKER_PID" "$BEAT_PID"
