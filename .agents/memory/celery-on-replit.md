---
name: Celery on Replit (no broker/worker)
description: Why Celery runs eager on Replit, the dead Upstash broker, and what still doesn't run (periodic tasks)
---

# Celery strategy after Heroku → Replit migration

**Rule:** on Replit, Celery runs in eager mode — tasks execute inline in the web
process. `CELERY_TASK_ALWAYS_EAGER=True` is set as a shared env var and
`settings.py` honours it (`DEBUG or env flag`). Do not reintroduce broker-based
dispatch without also provisioning a broker AND a worker.

**Why:** the old Upstash Redis broker (`BROKER_URL` rediss:// in `.replit
[userenv.shared]`) no longer exists — its hostname doesn't resolve (NXDOMAIN).
On Autoscale only gunicorn runs, so there is no Celery worker/beat anyway; even
successful publishes would never execute. Broker connect failures inside
requests caused intermittent 500s on `POST /user/login` (login queues a
verification email when `user.email_verified` is False).

**Hardening:** `TransactionAwareTask.delay_on_commit` wraps `self.delay` in
try/except + `logger.exception("Failed to dispatch task ...")` — email/task
dispatch failure must never crash the triggering request. Watch prod logs for
that message.

**Still outstanding:**
- Periodic tasks (`check_subscriptions`, `update_daily_summaries`) do NOT run on
  Replit — no beat/worker. Needs a scheduler/cron or external worker if wanted.
- `SENDGRID_API_KEY` was requested from the user; without it, eager email sends
  fail (logged, non-fatal — celery eager does not propagate exceptions by
  default). Needed for verification-code and password-reset emails.
- Stale `BROKER_URL` still sits in `.replit [userenv.shared]`; harmless in eager
  mode but should be cleaned with the other plaintext creds there.
