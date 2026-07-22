#!/usr/bin/env bash
# Bootstrap local Mendreo API development.
# Usage:
#   bash scripts/setup_dev_env.sh          # install deps, migrate, collectstatic
#   bash scripts/setup_dev_env.sh --run    # same, then start gunicorn on :5000
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [ ! -f "$ROOT/.env.local" ]; then
  echo "Missing .env.local — copy defaults from the repo root or create one."
  exit 1
fi

set -a
# shellcheck disable=SC1091
source "$ROOT/.env.local"
set +a

# Avoid set -u errors when SUPABASE_DEV_DB_URL is unset (see set_db_env.sh)
export SUPABASE_DEV_DB_URL="${SUPABASE_DEV_DB_URL:-}"
# shellcheck disable=SC1091
source "$ROOT/set_db_env.sh"

if [ ! -x "$ROOT/.venv/bin/python" ]; then
  echo "Creating Python 3.13 virtualenv..."
  python3.13 -m venv "$ROOT/.venv"
  "$ROOT/.venv/bin/python" -m pip install --upgrade pip
  "$ROOT/.venv/bin/pip" install -r "$ROOT/requirements.txt"
fi

echo "Running migrations..."
cd "$ROOT/mendreo"
"$ROOT/.venv/bin/python" manage.py migrate --noinput

echo "Collecting static files..."
"$ROOT/.venv/bin/python" manage.py collectstatic --noinput

echo "Dev environment ready."
echo "  Health check: curl http://127.0.0.1:5000/"
echo "  Start server:  bash run_dev.sh"

if [ "${1:-}" = "--run" ]; then
  exec bash "$ROOT/run_dev.sh"
fi
