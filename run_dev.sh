#!/usr/bin/env bash
set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"

# Derive DATABASE_* from the Supabase dev connection secret (see set_db_env.sh),
# then launch gunicorn. Used by both the dev workflow and the deployment run step.
source "$ROOT/set_db_env.sh"

cd "$ROOT/mendreo"
exec "$ROOT/.venv/bin/gunicorn" mendreo.wsgi --bind 0.0.0.0:5000 --workers 2 --access-logfile - --error-logfile -
