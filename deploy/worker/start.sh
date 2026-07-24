#!/usr/bin/env bash
# Railway worker entrypoint: keep Gunicorn alive even if Celery fails to start.
set -euo pipefail

cd /app/backend

# Railway injects PORT (usually 8080) and routes over IPv6; bind [::] for dual-stack.
LISTEN_PORT="${PORT:-8080}"
echo "worker: starting Gunicorn on [::]:${LISTEN_PORT}"
gunicorn mendreo.wsgi \
  --bind "[::]:${LISTEN_PORT}" \
  --workers 2 \
  --timeout 300 \
  --access-logfile - \
  --error-logfile - &
WEB_PID=$!

sleep 2

if [ -n "${BROKER_URL:-}" ] && [ "${BROKER_URL}" != "memory://" ]; then
  echo "worker: starting Celery worker"
  celery -A mendreo worker --loglevel=info --concurrency=2 &
  echo "worker: starting Celery beat"
  celery -A mendreo beat --loglevel=info &
else
  echo "worker: BROKER_URL not set — skipping Celery (AI HTTP still works)"
fi

echo "worker: Gunicorn pid ${WEB_PID}; waiting"
wait "$WEB_PID"
