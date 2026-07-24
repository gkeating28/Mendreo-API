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

See **`docs/RAILWAY_SETUP.md`** for full setup. Quick checklist:

| Setting | Value |
|---|---|
| Config file path | `/railway.json` |
| Root Directory | **blank** |
| Dockerfile | repo-root `Dockerfile` |
| Backup env var | `RAILWAY_DOCKERFILE_PATH=Dockerfile` |

Build log must show **`Using detected Dockerfile!`** — not Railpack/Nixpacks.

## Common errors

| Log line | Cause | Fix |
|---|---|---|
| `Unknown instruction: "<<<<<<<"` | Git merge conflict in Dockerfile | Merge fix PR; never deploy conflict markers |
| `COPY backend: not found` | Wrong Root Directory | Clear Root Directory |
| `/app/.venv/bin/python: No such file` | Old start.sh sourced `set_db_env.sh` in Docker | Merge latest worker fix |
| `SUPABASE_DEV_DB_URL is malformed` | Bad DB URL env var | Use Session pooler URL |
| Health check failed / HTTP 499 (~95s) | Gunicorn on wrong port/address, or DB hang on `/` health check | Merge latest worker fix: bind `[::]:\${PORT}`, signed-cookie sessions; confirm Railway `PORT` is not overridden to `8000` |

## Verify locally (optional)

```bash
buildah bud -f deploy/worker/worker.dockerfile -t mendreo-worker .
```

## After a successful deploy

```bash
bash scripts/verify_worker.sh
```

Internal route should return **403**, not HTML **404**.
