# Mendreo API

Django/DRF backend for Mendreo. See [`docs/API.md`](docs/API.md) for endpoint reference.

## Requirements

- **Python 3.13** (see `runtime.txt`)
- **PostgreSQL 15+** (local or Supabase Session pooler)
- **GDAL** (system lib; CI installs `gdal-bin`)

Optional for full feature parity:

- **Redis** — only if running Celery worker/beat (`Procfile`); local dev uses `CELERY_TASK_ALWAYS_EAGER=True` instead
- **AWS S3 / CloudFront** — file and image uploads
- **SendGrid** — transactional email
- **Stripe** — subscriptions
- **Google API key** — Gemini AI chat and image generation
- **OAuth keys** — Google, Apple, Facebook social login
- 

## Quick start (local)

```bash
# 1. System deps (Ubuntu/Debian example)
sudo apt-get install python3.13 python3.13-venv postgresql gdal-bin

# 2. Local Postgres (matches CI defaults)
sudo service postgresql start
sudo -u postgres psql -c "ALTER USER postgres WITH PASSWORD '1234';"
sudo -u postgres createdb mendreo

# 3. Python env
python3.13 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 4. Config
cp .env.local.example .env.local

# 5. Migrate and run
bash scripts/setup_dev_env.sh
bash run_dev.sh
```

Health check: `curl http://127.0.0.1:5000/` → `{"service":"mendreo-api","status":"ok",...}`

## Environment variables

| Variable | Required | Purpose |
|---|---|---|
| `DATABASE_*` or `SUPABASE_DEV_DB_URL` | Yes | PostgreSQL connection |
| `GENERAL_SECRET_KEY` | Yes | Django secret key |
| `GENERAL_DEBUG` | No | `True` enables debug toolbar + eager Celery |
| `GENERAL_HOST_DOMAIN` | No | Allowed hosts (comma-separated) |
| `CELERY_TASK_ALWAYS_EAGER` | No | Run async tasks inline (default in dev) |
| `BROKER_URL` | No | Celery broker (`memory://` for local) |
| `GOOGLE_API_KEY` | For AI | Gemini models for chat/sessions |
| `AWS_*` | For uploads | S3 storage and CloudFront CDN |
| `SENDGRID_API_KEY` | For email | Password reset, verification |
| `STRIPE_SECRET_KEY` | For billing | Subscriptions |
| OAuth / Apple / survey vars | Optional | Social login and survey flows |

`set_db_env.sh` parses `SUPABASE_DEV_DB_URL` into `DATABASE_*` when set (used on Replit). Locally, set `DATABASE_*` directly in `.env.local`.

## Processes

| Command | Description |
|---|---|
| `bash run_dev.sh` | Gunicorn web server on `:5000` |
| `cd mendreo && ../.venv/bin/python manage.py migrate` | Apply DB migrations |
| `cd mendreo && ../.venv/bin/celery -A mendreo worker` | Celery worker (needs Redis) |
| `cd mendreo && ../.venv/bin/celery -A mendreo beat` | Celery scheduler |

## Tests

```bash
source .env.local
cd mendreo
../.venv/bin/python manage.py test api.tests
```

CI uses PostGIS Postgres and GitHub environment secrets (see `.github/workflows/django.yml`).

## Production deployment (hybrid)

Recommended layout: **Vercel** for the public API + **Railway/Fly worker** for AI and Celery.

See [`docs/DEPLOYMENT_HYBRID.md`](docs/DEPLOYMENT_HYBRID.md) for step-by-step setup.

| Service | Role | Key env |
|---|---|---|
| Vercel | HTTP API | `DEPLOYMENT_TARGET=vercel`, `AI_WORKER_URL`, `BROKER_URL` |
| Worker | AI + Celery | `DEPLOYMENT_TARGET=worker`, `INTERNAL_API_SECRET` |
| Supabase | Postgres | Session pooler URL |
| Upstash | Redis broker | `BROKER_URL` |

```bash
# Run worker locally
bash scripts/run_worker.sh
```
