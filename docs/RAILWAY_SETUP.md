# Railway worker setup from scratch

Use this if redeploy does nothing, or `curl` returns `"Application not found"`.

## Symptom

```bash
curl https://web-production-17436.up.railway.app/
# {"status":"error","code":404,"message":"Application not found"}
```

That means the **Railway service or its public domain no longer exists** — not that Django failed. Redeploying GitHub code cannot fix a deleted service.

---

## Fix: create ONE Railway service

### 1. Railway dashboard

1. Open [railway.com/dashboard](https://railway.com/dashboard)
2. Open your project (or **New Project** → **Deploy from GitHub repo**)
3. Select **`gkeating28/Mendreo-API`**
4. Use **one service only** — delete extra `web` / `scheduler` services if they exist

### 2. Service settings

| Setting | Value |
|---|---|
| Branch | `main` |
| Root Directory | **leave blank** |
| Builder | **Dockerfile** |
| Dockerfile path | `deploy/worker/worker.dockerfile` |
| Config file | `railway.toml` |

### 3. Environment variables

Copy the same values you use on Vercel (where noted):

```env
DEPLOYMENT_TARGET=worker
GENERAL_SECRET_KEY=<same as Vercel>
GENERAL_DEBUG=False
SUPABASE_DEV_DB_URL=postgresql://...pooler.supabase.com:5432/postgres
BROKER_URL=rediss://...upstash.io:6379
INTERNAL_API_SECRET=<same as Vercel>
GOOGLE_API_KEY=...
```

Do **not** set `AI_WORKER_URL` on Railway.

### 4. Generate a public domain

1. Service → **Settings** → **Networking**
2. **Generate Domain**
3. Copy the new URL, e.g. `https://mendreo-api-production-xxxx.up.railway.app`

### 5. Update Vercel

In Vercel project env vars:

```env
AI_WORKER_URL=https://<your-new-railway-domain>
INTERNAL_API_SECRET=<same as Railway worker>
```

Redeploy Vercel after changing `AI_WORKER_URL`.

### 6. Verify

```bash
curl https://<your-new-railway-domain>/
# {"service":"mendreo-api","status":"ok",...}

curl -sS -o /dev/null -w '%{http_code}\n' \
  -X POST https://<your-new-railway-domain>/internal/ai/message-response \
  -H "Content-Type: application/json" -d '{}'
# 403 = good (route exists)
```

Or:

```bash
bash scripts/verify_worker.sh https://mendreo-api.vercel.app https://<your-new-railway-domain>
```

---

## Enable auto-deploy from GitHub

Service → **Settings** → **Source**:

- Repo: `gkeating28/Mendreo-API`
- Branch: `main`
- **Wait for CI** → off (unless you want it)
- Pushes to `main` should trigger a new deployment automatically

If pushes do not deploy: click **Deploy** → **Redeploy** manually once after saving settings.

---

## Still stuck?

In the failed deployment, check **Deploy Logs** (not Build Logs) for:

- `Listening at: http://0.0.0.0:...` → Gunicorn started
- `SUPABASE_DEV_DB_URL is malformed` → fix DB URL
- `Health check failed` → check env vars and Deploy Logs above the failure
