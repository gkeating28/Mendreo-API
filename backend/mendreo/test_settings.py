"""Throwaway local Postgres for the API test suite.

Never reads SUPABASE_DEV_DB_URL or ambient DATABASE_* credentials.
Connects only to 127.0.0.1 (or localhost) as mendreo_test. Django
creates the test database on that server.

Postgres 18 cluster, with pgvector installed for that server:

    PW=/tmp/mendreo-test-pg.pw
    printf '%s' 'mendreo_test' > "$PW"
    /opt/homebrew/opt/postgresql@18/bin/initdb \
      -D /tmp/mendreo-test-pg -U mendreo_test \
      --pwfile="$PW" --auth=scram-sha-256
    {
      echo "port = 54329"
      echo "listen_addresses = '127.0.0.1'"
      echo "unix_socket_directories = '/tmp/mendreo-test-pg'"
    } >> /tmp/mendreo-test-pg/postgresql.conf
    /opt/homebrew/opt/postgresql@18/bin/pg_ctl \
      -D /tmp/mendreo-test-pg -l /tmp/mendreo-test-pg.log -w start
    PGPASSWORD=mendreo_test psql -h 127.0.0.1 -p 54329 \
      -U mendreo_test -d postgres \
      -c 'CREATE DATABASE mendreo_test;'

Or the same user, password, database, and port in Docker:

    docker run -d --name mendreo-test-pg \
      -e POSTGRES_USER=mendreo_test \
      -e POSTGRES_PASSWORD=mendreo_test \
      -e POSTGRES_DB=mendreo_test \
      -p 127.0.0.1:54329:5432 \
      pgvector/pgvector:pg15

    cd backend
    DJANGO_SETTINGS_MODULE=mendreo.test_settings \
      ../.venv/bin/python manage.py test api.tests
"""

import os

_LOCAL_HOSTS = {"127.0.0.1", "localhost"}

for _name in list(os.environ):
    if _name.startswith("SUPABASE_"):
        os.environ.pop(_name, None)

os.environ["BROKER_URL"] = "memory://"
os.environ["CELERY_TASK_ALWAYS_EAGER"] = "true"

_host = os.environ.get("TEST_DATABASE_HOST", "127.0.0.1")
if _host not in _LOCAL_HOSTS:
    raise RuntimeError(
        "mendreo.test_settings only connects to 127.0.0.1 or localhost."
    )

os.environ["DATABASE_ENGINE"] = "django.db.backends.postgresql"
os.environ["DATABASE_HOST"] = _host
os.environ["DATABASE_PORT"] = os.environ.get("TEST_DATABASE_PORT", "54329")
os.environ["DATABASE_NAME"] = "mendreo_test"
os.environ["DATABASE_USER"] = "mendreo_test"
os.environ["DATABASE_PASSWORD"] = "mendreo_test"

from mendreo.settings import *  # noqa: E402,F403

_database = DATABASES["default"]  # noqa: F405
_host_ok = _database.get("HOST") in _LOCAL_HOSTS
_name_ok = _database.get("NAME") == "mendreo_test"
if not _host_ok or not _name_ok:
    raise RuntimeError(
        "mendreo.test_settings refused a non-local test database."
    )

_database["TEST"] = {"NAME": "test_mendreo_throwaway"}
