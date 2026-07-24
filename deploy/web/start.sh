#!/usr/bin/env bash
# Gunicorn only — use for a dedicated Railway "web" service.
# Set AI_WORKER_URL on Vercel to this service's public URL.
set -euo pipefail

cd /app/backend

echo "web: running migrations"
python manage.py migrate --noinput

echo "web: starting Gunicorn on :${PORT:-8000}"
exec gunicorn mendreo.wsgi \
  --bind "0.0.0.0:${PORT:-8000}" \
  --workers 2 \
  --timeout 300 \
  --access-logfile - \
  --error-logfile -
