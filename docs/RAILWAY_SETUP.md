# Railway worker setup

## Build log: what success looks like

A **good** Railway build log includes:

```
Using detected Dockerfile!
railway-build: installing python dependencies
railway-build: python dependencies installed
```

A **bad** build log (wrong builder) shows:

```
Railpack
nixpacks
railpack-plan.json
```

If you see Railpack/Nixpacks, Railway is **not** using our Dockerfile. Fix the settings below.

---

## Required service settings

| Setting | Value |
|---|---|
| GitHub repo | `gkeating28/Mendreo-API` |
| Branch | `main` |
| Root Directory | **blank** (repo root) |
| Config file path | `/railway.json` |
| Builder (UI may show Railpack) | overridden by `railway.json` → **DOCKERFILE** |
| Dockerfile | repo-root **`Dockerfile`** |

### Backup env var (if build still uses Railpack)

Add this **service variable** in Railway:

```env
RAILWAY_DOCKERFILE_PATH=Dockerfile
```

For a clean first build:

```env
NO_CACHE=1
```

Remove `NO_CACHE` after the first successful deploy.

---

## One service only

Use **one** Railway service (Gunicorn + Celery worker + beat). Vercel is the public web API.

Delete extra `web` / `scheduler` services unless you merged PR #5 and configured each with its own config file.

---

## Environment variables

```env
DEPLOYMENT_TARGET=worker
GENERAL_SECRET_KEY=<same as Vercel>
GENERAL_DEBUG=False
SUPABASE_DEV_DB_URL=postgresql://...pooler.supabase.com:5432/postgres
BROKER_URL=rediss://...upstash.io:6379
INTERNAL_API_SECRET=<same as Vercel>
GOOGLE_API_KEY=...
AI_SECRETS_MASTER_KEY=...   # Fernet key; encrypts AI provider API keys in Postgres
# Optional seeds when ai_provider table is empty:
# OPENAI_API_KEY=...
# ANTHROPIC_API_KEY=...
```

**Important:**
- `DEPLOYMENT_TARGET` must be exactly `worker` (not `worker.railway.internal` or similar)
- `BROKER_URL` must use **`rediss://`** (TLS) for Upstash, not `redis://`
- Do **not** set `AI_WORKER_URL` on Railway
- `AI_SECRETS_MASTER_KEY` is required on the worker (decrypts provider keys). Generate with:
  `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
- If chat returns “Sorry, I had an issue understanding your message…”, check message `reasoning` / worker logs. A common cause is a missing `AI_SECRETS_MASTER_KEY` (cannot decrypt `api_aiprovider` keys). With `GOOGLE_API_KEY` set, the worker falls back to the env key so chat still works; then set the master key and run `python manage.py seed_ai_providers --refresh-from-env` to re-encrypt DB keys.
- `GOOGLE_API_KEY` remains used for Google Play receipt validation; it also seeds a default Google AI provider on first boot when none exist, and is the runtime fallback when DB keys cannot be decrypted.

---

## Public domain + Vercel

1. Service → **Settings** → **Networking** → **Generate Domain**
2. Copy URL, e.g. `https://mendreo-api-production-xxxx.up.railway.app`
3. On Vercel:

```env
AI_WORKER_URL=https://<your-new-railway-domain>
INTERNAL_API_SECRET=<same as Railway>
```

4. Redeploy Vercel

---

## Verify

```bash
curl https://<your-railway-domain>/
# {"service":"mendreo-api","status":"ok",...}

curl -sS -o /dev/null -w '%{http_code}\n' \
  -X POST https://<your-railway-domain>/internal/ai/message-response \
  -H "Content-Type: application/json" -d '{}'
# 403 = good
```

```bash
bash scripts/verify_worker.sh https://mendreo-api.vercel.app https://<your-railway-domain>
```

---

## "Application not found"

If Railway returns:

```json
{"status":"error","code":404,"message":"Application not found"}
```

The service or domain was deleted. Generate a **new domain** and update Vercel `AI_WORKER_URL`.

---

## Build succeeds but deploy fails

Check **Deploy Logs** (not Build Logs):

| Log | Fix |
|---|---|
| `Invalid HTTP_HOST header: 'healthcheck.railway.app'` | Set `DEPLOYMENT_TARGET=worker` exactly; merge latest `main` (adds `healthcheck.railway.app` to ALLOWED_HOSTS) |
| `service unavailable` on health check | Gunicorn must bind to `$PORT`; check Deploy Logs for `Listening at:` |
| Celery connection errors | Set `BROKER_URL=rediss://...` (TLS) |
| `SUPABASE_DEV_DB_URL is malformed` | Fix DB URL in Railway variables |
| Container exits after Celery starts | Latest `start.sh` keeps Gunicorn alive even if Celery fails — redeploy from `main` |
