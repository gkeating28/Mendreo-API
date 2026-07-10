# Sourced (not executed): sets DATABASE_* from SUPABASE_DEV_DB_URL when present,
# keeping the password out of plain env/committed config. Falls back to whatever
# DATABASE_* is already in the environment when the secret is absent.
# Fails fast (exit 3) if the URL is set but malformed, rather than exporting
# empty values over a valid fallback.
_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -n "$SUPABASE_DEV_DB_URL" ]; then
  _DB_EXPORTS="$("$_ROOT/.venv/bin/python" - <<'PY'
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
)" || exit 3
  eval "$_DB_EXPORTS"
  echo "db_env: using Supabase dev DB at ${DATABASE_HOST}:${DATABASE_PORT}/${DATABASE_NAME}"
else
  echo "db_env: SUPABASE_DEV_DB_URL not set; using existing DATABASE_* env"
fi
