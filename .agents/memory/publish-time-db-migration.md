---
name: Replit publish-time DB migration vs external DB
description: Why Publish can fail with "Failed to run database migration statement" even when the app uses an external DB (Supabase), and how to stop it.
---

# Publish-time DB migration when the app uses an external database

On Publish, Replit diffs the **Replit-managed** development database against its
production counterpart and applies the SQL diff to prod. This runs whenever a
Replit-managed Postgres is *provisioned*, regardless of whether the app actually
connects to it.

**Failure seen:** Publish fails with `Failed to run database migration statement`
on `CREATE VIEW public.geography_columns ... function postgis_typmod_dims(integer)
does not exist`. This is NOT a Django migration and NOT in the deploy build logs
(build's own `migrate` reports "No migrations to apply"). It is Replit's
publish-time schema diff choking on PostGIS objects.

**Why it happens here:** the app connects to Supabase (DATABASE_* from
SUPABASE_DEV_DB_URL) and has zero PostGIS/GeoDjango references. The Replit-managed
dev DB was only used as an intermediate restore target and still holds the prod
copy — including PostGIS objects that rode along from prod RDS. The publish diff
tries to recreate that PostGIS view in the Replit prod DB and fails.

**Fix / how to apply (correct approach):** if the app does not use the
Replit-managed DB, *remove the `postgresql-NN` module from `.replit`* so the repl
no longer uses Replit's managed Postgres at all. The Database pane often has NO
delete option, but the module is what provisions the DB and injects
`DATABASE_URL`. Use the package-management skill:
`uninstallProgrammingLanguage({ moduleId: "postgresql-16" })`. After removal
`.replit` `modules` drops it; the deploy/Publish flow reads the updated `.replit`,
sees no managed Postgres, and runs no DB migration. NOTE: the *current dev
session* may still show `DATABASE_URL` and `checkDatabase()` may still report
provisioned — that is stale session state that clears on a full env reboot; it
does not affect the deploy. Safe because the Django app connects to Supabase via
`DATABASE_*` from `set_db_env.sh`, never `DATABASE_URL`.
**Belt-and-suspenders:** emptying the Replit *dev* DB
(`DROP SCHEMA public CASCADE; CREATE SCHEMA public;`) when prod is already empty
also makes any lingering diff empty→empty. Data safe: `backups/*.dump` + Supabase.
**Why:** publish only runs a DB migration because the repl declares Replit-managed
Postgres; removing the module removes the trigger entirely.
