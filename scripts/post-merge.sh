#!/bin/bash
set -e

# Post-merge reconciliation for the Mendreo Django/DRF backend.
# Runs automatically after a task merges. Keep it idempotent, fast, and
# non-interactive (stdin is closed).
#
# Scope is intentionally limited to syncing Python dependencies into the
# existing project virtualenv. Database schema is NOT touched here:
#   - the app runs against Supabase (see set_db_env.sh / run_dev.sh)
#   - production schema is handled by Replit's Publish flow
# Running DDL against Supabase on every merge would be unsafe, so it is omitted.

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [ ! -x ".venv/bin/pip" ]; then
  echo "post-merge: .venv not found at $ROOT/.venv — skipping dependency sync"
  exit 0
fi

echo "post-merge: syncing Python dependencies from requirements.txt"
.venv/bin/pip install --disable-pip-version-check --no-input -r requirements.txt

echo "post-merge: done"
