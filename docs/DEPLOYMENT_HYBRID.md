# Hybrid deployment: Vercel + worker

This guide covers the recommended production layout:

- **Vercel** — public HTTP API (auth, CRUD, uploads metadata)
- **Worker service** (Railway/Fly/Render) — AI inference + Celery worker + beat
- **Supabase** — PostgreSQL (Session pooler)
- **Upstash Redis** — Celery broker

```
                    ┌─────────────────────┐
  Mobile / Web  ──► │  Vercel (Django)    │
                    │  DEPLOYMENT_TARGET= │
                    │  vercel             │
                    └─────────┬───────────┘
                              │ AI HTTP (sync)
                              │ Celery tasks (async)
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
     ┌─────────────┐  ┌─────────────┐  ┌─────────────┐
     │ Worker API  │  │ Redis       │  │ Supabase    │
     │ Gunicorn    │  │ (broker)    │  │ Postgres    │
     │ + Celery    │  └─────────────┘  └─────────────┘
     └─────────────┘
```

## Why hybrid?

| Concern | Vercel alone | Hybrid |
|---|---|---|
| AI chat latency | Function timeout / cold starts | Worker runs Gemini with 300s timeout |
| Celery beat | Cannot run | Worker runs beat |
| Email / article gen | Blocks or missing | Queued via Redis |
| CRUD endpoints | Good fit | Still on Vercel |

Client API contracts stay the same — `POST /messages` still returns the agent reply synchronously. Vercel forwards AI work to the worker over HTTP.

---

## 1. Shared infrastructure

### PostgreSQL (Supabase)

Use the **Session pooler** connection string (`*.pooler.supabase.com:5432`).

Set either:

```env
SUPABASE_DEV_DB_URL=postgresql://postgres.<ref>:<pass>@aws-0-<region>.pooler.supabase.com:5432/postgres
```

or individual `DATABASE_*` vars.

### Redis (Upstash)

```env
BROKER_URL=rediss://default:<token>@<host>.upstash.io:6379
```

Use the same `BROKER_URL` on both Vercel and the worker.

### Object storage (Supabase Storage)

All images, uploaded files, and consumer chat logs are stored in **Supabase
Storage**.

**Content Editor / public media uploads** use Supabase's native REST
**signed upload URLs** (not S3 presigns). The API needs either
`SUPABASE_SERVICE_ROLE_KEY` (preferred) or `SUPABASE_ANON_KEY` plus write
policies on the public bucket. Chat-log helpers may still use the
S3-compatible API via `boto3`.

1. Create **two buckets**:
   - one **public** bucket for images/files (served via public URLs and the image-render/transform endpoint)
   - one **private** bucket for chat logs (contains consumer PII — must not be public)
2. Copy the project URL and (optional) S3 keys from **Storage → S3**.
3. Set `SUPABASE_ANON_KEY` (Project Settings → API) or `SUPABASE_SERVICE_ROLE_KEY`
   on Vercel/Railway. Region must match the dashboard (this project: `eu-west-1`).

```env
SUPABASE_STORAGE_URL=https://<project_ref>.supabase.co
SUPABASE_STORAGE_S3_ENDPOINT=https://<project_ref>.storage.supabase.co/storage/v1/s3
SUPABASE_STORAGE_ACCESS_KEY_ID=<optional; S3 fallback / private logs>
SUPABASE_STORAGE_SECRET_ACCESS_KEY=<optional>
SUPABASE_STORAGE_REGION=<from Storage → S3, e.g. eu-west-1>
SUPABASE_STORAGE_BUCKET=<public bucket name>
SUPABASE_STORAGE_PRIVATE_BUCKET=<private bucket name>
SUPABASE_ANON_KEY=<project anon key>
# SUPABASE_SERVICE_ROLE_KEY=<project service_role key>  # preferred for writes
```

Use identical values on both Vercel and the worker.

**On-the-fly image resizing** (thumbnail/banner) uses Supabase's
[image transformation endpoint](https://supabase.com/docs/guides/storage/serving/image-transformations),
which requires the **Pro plan or above**. If you're on the Free plan, image
`thumbnail`/`banner` URLs will 400 until you upgrade — `original` still
works either way.

**Content Editor uploads:** `POST /images` and `POST /files` return
`pre_signed_url` **and** `content_type`. The browser should PUT the file
bytes with that `Content-Type` header (typically `file.type`).

**Migrating existing data from AWS S3:** run `python scripts/migrate_s3_to_supabase.py`
(see the script's docstring for required env vars and a `--dry-run` flag) to
copy every object from the old bucket into the new one before decommissioning AWS.

### Shared secrets

Generate strong random values for:

```env
INTERNAL_API_SECRET=<random>   # Vercel → worker AI calls
CRON_SECRET=<random>           # Vercel Cron → subscription check
GENERAL_SECRET_KEY=<random>    # Django (same on both services)
```

---

## 2. Deploy the worker (Railway)

### Option A: Railway (recommended)

1. Create a new Railway project from this repo.
2. Railway reads `railway.toml` and builds `deploy/worker/worker.dockerfile`.
3. Set environment variables (see below).
4. Note the public URL, e.g. `https://mendreo-worker.up.railway.app`.

### Option B: Local / Docker

```bash
docker build -f deploy/worker/worker.dockerfile -t mendreo-worker .
docker run --env-file .env.local -p 8000:8000 mendreo-worker
```

### Option C: Shell script (dev)

```bash
bash scripts/run_worker.sh
```

### Worker environment variables

```env
DEPLOYMENT_TARGET=worker
GENERAL_SECRET_KEY=<same-as-vercel>
GENERAL_DEBUG=False
GENERAL_HOST_DOMAIN=.railway.app,your-worker-domain.com
DATABASE_* or SUPABASE_DEV_DB_URL
BROKER_URL=rediss://...
GOOGLE_API_KEY=...
SUPABASE_STORAGE_URL=https://<project_ref>.supabase.co
SUPABASE_STORAGE_S3_ENDPOINT=https://<project_ref>.storage.supabase.co/storage/v1/s3
SUPABASE_STORAGE_ACCESS_KEY_ID=...
SUPABASE_STORAGE_SECRET_ACCESS_KEY=...
SUPABASE_STORAGE_BUCKET=...          # public bucket: images/files
SUPABASE_STORAGE_PRIVATE_BUCKET=...  # private bucket: chat logs (PII)
SUPABASE_ANON_KEY=...                # REST uploads (or SUPABASE_SERVICE_ROLE_KEY)
SENDGRID_API_KEY=...
STRIPE_SECRET_KEY=...
INTERNAL_API_SECRET=<same-as-vercel>
# Do NOT set AI_WORKER_URL on the worker (AI runs locally there)
```

The worker exposes:

| Endpoint | Purpose |
|---|---|
| `GET /` | Health check |
| `POST /internal/ai/message-response` | AI chat (called by Vercel) |
| `POST /internal/ai/session-greeting` | Exercise session opener |
| All public API routes | Available but normally unused |

Internal endpoints require header: `X-Internal-Secret: <INTERNAL_API_SECRET>`

---

## 3. Deploy the API (Vercel)

1. Import the GitHub repo at [vercel.com](https://vercel.com).
2. Framework preset: **Django** (auto-detected via `manage.py`).
3. Root directory: repository root.
4. Add environment variables:

```env
DEPLOYMENT_TARGET=vercel
GENERAL_SECRET_KEY=<same-as-worker>
GENERAL_DEBUG=False
GENERAL_HOST_DOMAIN=.vercel.app,your-api-domain.com
DATABASE_* or SUPABASE_DEV_DB_URL
DATABASE_CONN_MAX_AGE=0
BROKER_URL=rediss://...
AI_WORKER_URL=https://mendreo-worker.up.railway.app
INTERNAL_API_SECRET=<same-as-worker>
CRON_SECRET=<random-for-vercel-cron>
AI_WORKER_TIMEOUT=120
VERCEL_SUPPORT_LARGE_FUNCTIONS=1
GOOGLE_API_KEY=...
SUPABASE_STORAGE_URL=https://<project_ref>.supabase.co
SUPABASE_STORAGE_S3_ENDPOINT=https://<project_ref>.storage.supabase.co/storage/v1/s3
SUPABASE_STORAGE_ACCESS_KEY_ID=...
SUPABASE_STORAGE_SECRET_ACCESS_KEY=...
SUPABASE_STORAGE_BUCKET=...          # same values as worker
SUPABASE_STORAGE_PRIVATE_BUCKET=...  # same values as worker
SENDGRID_API_KEY=...
STRIPE_SECRET_KEY=...
# OAuth / survey vars as needed
```

5. Deploy. Vercel uses `backend/mendreo/wsgi.py` as the entrypoint, `requirements-vercel.txt`, and `vercel.json` for migrate/collectstatic/timeouts + cron.

### Vercel Cron

`vercel.json` schedules daily subscription validation at 1:00 AM UTC:

```
GET /internal/cron/check-subscriptions
Authorization: Bearer <CRON_SECRET>
```

Set `CRON_SECRET` in Vercel env vars (Vercel sends it automatically when configured).

---

## 4. Redeploy worker after merging to `main`

If Vercel is healthy but chat fails, the worker may still be running a pre-hybrid build (no `/internal/` routes).

1. Open your [Railway project](https://railway.com/dashboard).
2. Confirm the service is linked to **`gkeating28/mendreo-api`** on branch **`main`**.
3. **Redeploy** the latest deployment (or push an empty commit to `main` to trigger a build).
4. Railway builds `deploy/worker/worker.dockerfile` via `railway.toml` (repo root context; **do not** set Root Directory to `backend/`) and copies `backend/`.
5. After deploy finishes, run the smoke test below.

### Worker env checklist (Railway → Variables)

| Variable | Value |
|---|---|
| `DEPLOYMENT_TARGET` | `worker` |
| `GENERAL_SECRET_KEY` | same as Vercel |
| `GENERAL_DEBUG` | `False` |
| `GENERAL_HOST_DOMAIN` | `.railway.app` (optional; `.railway.app` is auto-allowed when `DEPLOYMENT_TARGET=worker`) |
| `SUPABASE_DEV_DB_URL` | Session pooler URL |
| `BROKER_URL` | `rediss://...` (Upstash TLS) |
| `INTERNAL_API_SECRET` | same as Vercel |
| `GOOGLE_API_KEY` | Gemini key |
| `SUPABASE_STORAGE_*` (object storage), `SENDGRID_*`, `STRIPE_*` | as needed |

Do **not** set `AI_WORKER_URL` on the worker.

Then on **Vercel**, confirm:

```env
AI_WORKER_URL=https://YOUR-SERVICE.up.railway.app
INTERNAL_API_SECRET=<same-as-worker>
```

---

## 5. Verify

```bash
# Quick smoke test (both services)
bash scripts/verify_worker.sh

# Or manually:
curl https://mendreo-api.vercel.app/
curl https://web-production-17436.up.railway.app/

# Internal route must exist (403 without secret — NOT 404)
curl -sS -o /dev/null -w '%{http_code}\n' \
  -X POST https://web-production-17436.up.railway.app/internal/ai/message-response \
  -H "Content-Type: application/json" \
  -d '{}'

# End-to-end chat (requires auth token)
curl -X POST https://mendreo-api.vercel.app/messages \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"text":"Hello","session":"<session_id>","consumer":"<consumer_id>"}'
```

---

## 6. Local development

Without a worker, AI runs inline (same as before):

```bash
cp .env.local.example .env.local
# Leave AI_WORKER_URL unset
bash scripts/setup_dev_env.sh
bash run_dev.sh
```

To test hybrid locally:

```bash
# Terminal 1
DEPLOYMENT_TARGET=worker bash scripts/run_worker.sh

# Terminal 2 — in .env.local:
# AI_WORKER_URL=http://127.0.0.1:8000
# INTERNAL_API_SECRET=dev-internal-secret
bash run_dev.sh
```

---

## Environment variable reference

| Variable | Vercel | Worker | Local |
|---|---|---|---|
| `DEPLOYMENT_TARGET` | `vercel` | `worker` | unset / `local` |
| `AI_WORKER_URL` | worker URL | unset | unset or worker URL |
| `INTERNAL_API_SECRET` | yes | yes | optional |
| `CRON_SECRET` | yes | no | no |
| `BROKER_URL` | yes | yes | `memory://` |
| `CELERY_TASK_ALWAYS_EAGER` | auto `False` | auto `False` | auto `True` if `DEBUG` |
| `DATABASE_CONN_MAX_AGE` | `0` (default) | `300` (default) | `300` (default) |

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `POST /messages` 403 from worker | Check `INTERNAL_API_SECRET` matches on both services |
| Chat timeout on Vercel | Increase `vercel.json` `maxDuration` and `AI_WORKER_TIMEOUT` |
| Emails not sending | Confirm `BROKER_URL` and worker Celery process are running |
| Subscriptions not checked | Confirm Vercel Cron is enabled and `CRON_SECRET` is set |
| DB connection errors on Vercel | Use Supabase Session pooler; keep `DATABASE_CONN_MAX_AGE=0` |
| `POST /internal/ai/*` returns HTML 404 | Redeploy Railway from `main` — worker is on a pre-hybrid build without internal routes |
| Build fails on `COPY backend` | Railway service **Root Directory** must be repo root (empty), not `backend/` |
| Build fails during `pip install` | Uses `requirements-worker.txt`; confirm build logs for OOM/timeout |
| Build fails on `gdal-bin` / `libgdal-dev` | Fixed in latest Dockerfile — GDAL removed (not used by this project) |
| Deploy fails / health check timeout | Gunicorn starts before migrations; confirm `SUPABASE_DEV_DB_URL` and `BROKER_URL=rediss://...` |
| `FUNCTION_INVOCATION_FAILED` / `No module named 'mendreo.settings'` | Redeploy latest commit. The Django app lives under `backend/` (not repo-root `mendreo/`) to avoid Python package shadowing on Vercel. Set `DEPLOYMENT_TARGET=vercel`. Do **not** set `PYTHONPATH`. |
