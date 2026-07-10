---
name: Supabase connections from Replit
description: Why Supabase direct connection fails from Replit and which connection string to use
---

# Connecting to Supabase from Replit

Replit's environment has **no IPv6 outbound**. Supabase's **direct connection** host
(`db.<ref>.supabase.co`) is **IPv6-only** — it has no A record — so psql/pg_dump/Django
fail with an empty/silent connection error.

**Rule:** always use the Supabase **Session pooler** connection string for anything running
on Replit. Host looks like `aws-0-<region>.pooler.supabase.com`, port `5432`, username
`postgres.<ref>`. It resolves to IPv4 and supports full SQL (restores, DDL) unlike the
Transaction pooler (port 6543).

**Why:** confirmed via `getent ahostsv4 db.<ref>.supabase.co` returning nothing; the pooler
host returns an AWS ELB IPv4. Cost us several round-trips because the direct string looks
correct but silently can't connect.

**How to apply:** when a user pastes a Supabase URL, verify the host contains `pooler`. If it
says `db.<ref>.supabase.co`, ask for the Session pooler string (Supabase dashboard -> Connect
-> Session pooler), or have them enable the paid Dedicated IPv4 add-on.

**Restore note:** local pg_restore is v17; restoring a PG16 custom dump emits a PG17-only
`SET transaction_timeout` — restore without `--exit-on-error` (it skips that one line). A
`permission denied for table spatial_ref_sys` error during restore is benign (PostGIS
system table Supabase owns and pre-populates).

**Secrets note:** the agent cannot overwrite/delete an existing Replit *secret*
programmatically (deleteEnvVars only touches env vars, not global secrets). If a secret holds
a wrong value, the user must edit/delete it in the Secrets tab UI — the requestEnvVar prompt
won't overwrite an existing key.
