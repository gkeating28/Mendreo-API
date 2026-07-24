#!/usr/bin/env bash
set -euo pipefail

cd /app/backend

echo "worker: starting Gunicorn on :${PORT:-8000}"
gunicorn mendreo.wsgi \
  --bind "0.0.0.0:${PORT:-8000}" \
  --workers 2 \
  --timeout 300 \
  --access-logfile - \
  --error-logfile - &
WEB_PID=$!

sleep 2

echo "worker: running migrations"
python manage.py migrate --noinput

echo "worker: starting Celery worker"
celery -A mendreo worker --loglevel=info --concurrency=2 &
WORKER_PID=$!

echo "worker: starting Celery beat"
celery -A mendreo beat --loglevel=info &
BEAT_PID=$!

trap 'kill "$WEB_PID" "$WORKER_PID" "$BEAT_PID" 2>/dev/null || true' EXIT INT TERM

wait -n "$WEB_PID" "$WORKER_PID" "$BEAT_PID"
