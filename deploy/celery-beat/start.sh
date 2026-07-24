#!/usr/bin/env bash
# Celery beat only — run exactly ONE Railway "scheduler" replica.
set -euo pipefail

cd /app/backend

echo "celery-beat: starting"
exec celery -A mendreo beat --loglevel=info
