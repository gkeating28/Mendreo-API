#!/usr/bin/env bash
set -e
cd "$(dirname "$0")/mendreo"

# Derive DATABASE_* from the Supabase dev connection URL if present,
# so the app's dev workflow uses Supabase. Falls back to whatever
# DATABASE_* is already in the environment otherwise.
#
# If SUPABASE_DEV_DB_URL is set but malformed, fail fast with a clear
# message rather than exporting empty values over a valid fallback.
if [ -n "$SUPABASE_DEV_DB_URL" ]; then
  DB_EXPORTS="$(../.venv/bin/python - <<'PY'
import os, shlex, sys, urllib.parse as u
p = u.urlparse(os.environ["SUPABASE_DEV_DB_URL"])
host = p.hostname or ""
user = u.unquote(p.username or "")
name = p.path.lstrip("/")
if p.scheme not in ("postgres", "postgresql") or not host or not user or not name:
    sys.stderr.write("SUPABASE_DEV_DB_URL is malformed (need scheme://user:pass@host:port/dbname)\n")
    sys.exit(3)
pairs = [
    ("DATABASE_HOST", host),
    ("DATABASE_PORT", str(p.port or 5432)),
    ("DATABASE_USER", user),
    ("DATABASE_PASSWORD", u.unquote(p.password or "")),
    ("DATABASE_NAME", name),
]
print("export " + " ".join(f"{k}={shlex.quote(v)}" for k, v in pairs))
PY
)"
  eval "$DB_EXPORTS"
  echo "run_dev: using Supabase dev DB at ${DATABASE_HOST}:${DATABASE_PORT}/${DATABASE_NAME}"
else
  echo "run_dev: SUPABASE_DEV_DB_URL not set; using existing DATABASE_* env"
fi

exec ../.venv/bin/gunicorn mendreo.wsgi --bind 0.0.0.0:5000 --workers 2 --access-logfile - --error-logfile -
