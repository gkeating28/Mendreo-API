# Railway build / deploy debugging

Railway often labels a failed **deploy** as a failed build. Use these steps to see the real error.

## Where to find logs

1. Open [railway.com/dashboard](https://railway.com/dashboard)
2. Select your **project** → **worker service**
3. Click **Deployments**
4. Click the failed deployment row
5. Open two tabs:
   - **Build Logs** — Docker image build (`FROM`, `COPY`, `pip install`)
   - **Deploy Logs** — container startup (`worker: starting Gunicorn`, migrations, Celery)

If Build Logs show `Successfully built` / `COMMIT`, the build succeeded and the failure is in **Deploy Logs**.

## Required Railway settings

### Option A — one service (recommended)

Use a **single** Railway service. It runs Gunicorn, Celery worker, and Celery beat together via `./start-all.sh`.

| Setting | Value |
|---|---|
| Source branch | `main` |
| Root Directory | **empty** (repo root) |
| Config file | `railway.toml` (default) |
| Builder | Dockerfile |
| Dockerfile path | `deploy/worker/worker.dockerfile` |

**Do not** create separate Railway `web` and `scheduler` services unless you configure them (Option B). Vercel is already your public web API.

### Option B — three Railway services (advanced)

If you already have separate **web**, **worker**, and **scheduler** services, each must point at a different config file:

| Railway service | Config file (Settings → Config file path) | Start command | Health check |
|---|---|---|---|
| **web** | `/deploy/railway/web.toml` | `./start-web.sh` | `/` |
| **worker** | `/deploy/railway/worker.toml` | `./start-celery-worker.sh` | none |
| **scheduler** | `/deploy/railway/scheduler.toml` | `./start-celery-beat.sh` | none |

All three use the same Dockerfile: `deploy/worker/worker.dockerfile`. Root Directory must be **empty** on every service.

Set `AI_WORKER_URL` on Vercel to the **web** service's public URL (not the celery worker service).

Run **exactly one** scheduler replica (Celery beat).

If web/scheduler fail to build, they are usually missing the config file path above and Railway falls back to Railpack/Nixpacks instead of Docker.

## Common errors

| Log line | Cause | Fix |
|---|---|---|
| `Unknown instruction: "<<<<<<<"` | Git merge conflict in Dockerfile | Merge fix PR; never deploy conflict markers |
| `COPY backend: not found` | Wrong Root Directory | Clear Root Directory |
| `/app/.venv/bin/python: No such file` | Old start.sh sourced `set_db_env.sh` in Docker | Merge latest worker fix |
| `SUPABASE_DEV_DB_URL is malformed` | Bad DB URL env var | Use Session pooler URL |
| Health check failed | Gunicorn not listening | Check Deploy Logs for crash before `Listening at:` |

## Verify locally (optional)

```bash
buildah bud -f deploy/worker/worker.dockerfile -t mendreo-worker .
```

## After a successful deploy

```bash
bash scripts/verify_worker.sh
```

Internal route should return **403**, not HTML **404**.
