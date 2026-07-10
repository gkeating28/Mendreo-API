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

**Fix / how to apply:** if the app does not use the Replit-managed DB, make the
publish diff a no-op. There is no agent tool to delete a Replit DB (skill only
exposes checkDatabase/createDatabase/executeSql) and the Database pane often shows
NO delete option. What worked: empty the Replit *dev* DB via
executeSql(development) with `DROP SCHEMA public CASCADE; CREATE SCHEMA public;`
(+ re-grant to current_user and PUBLIC). When the Replit *prod* DB is already
empty (verify with executeSql environment:"production"), the diff becomes
empty→empty = clean no-op with zero destructive prod ops. Data is safe: backed up
in `backups/*.dump` and seeded into Supabase; nothing in the app touches this DB.
**Why:** publish only runs a DB migration because a Replit DB is provisioned;
emptying it (can't delete it) neutralizes the diff.
