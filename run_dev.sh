#!/usr/bin/env bash
set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"

# Load local dev overrides when present (gitignored; not used on Replit deploy).
if [ -f "$ROOT/.env.local" ]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env.local"
  set +a
fi

# Derive DATABASE_* from the Supabase dev connection secret (see set_db_env.sh),
# then launch gunicorn. Used by both the dev workflow and the deployment run step.
source "$ROOT/set_db_env.sh"

cd "$ROOT/mendreo"

# --preload imports the (heavy) app once in the master before forking workers,
# so cold start is faster/leaner and the autoscale startup probe gets a 200 sooner.
# Generous timeouts keep workers from being killed during the ~13s import.
exec "$ROOT/.venv/bin/python" -m gunicorn mendreo.wsgi \
  --bind 0.0.0.0:5000 \
  --workers 2 \
  --preload \
  --timeout 120 \
  --graceful-timeout 120 \
  --access-logfile - \
  --error-logfile -
