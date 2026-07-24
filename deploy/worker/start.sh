#!/usr/bin/env bash
# Railway worker entrypoint: keep Gunicorn alive even if Celery fails to start.
set -euo pipefail

cd /app/backend

# Railway injects PORT (usually 8080) and routes over IPv6; bind both stacks.
LISTEN_PORT="${PORT:-8080}"
WORKERS="${WEB_CONCURRENCY:-1}"
echo "worker: starting Gunicorn (${WORKERS} worker(s)) on 0.0.0.0:${LISTEN_PORT} and [::]:${LISTEN_PORT}"
MENDREO_SKIP_CELERY_IMPORT=1 gunicorn mendreo.wsgi \
  --bind "0.0.0.0:${LISTEN_PORT}" \
  --bind "[::]:${LISTEN_PORT}" \
  --workers "${WORKERS}" \
  --preload \
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
