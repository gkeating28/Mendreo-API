#!/usr/bin/env bash
# Celery worker only — use for a dedicated Railway "worker" service.
set -euo pipefail

cd /app/backend

echo "celery-worker: starting"
exec celery -A mendreo worker --loglevel=info --concurrency=2
