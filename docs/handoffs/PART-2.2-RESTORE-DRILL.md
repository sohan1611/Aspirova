# Part 2.2 — Backup & Restore Drill Record

*Doc 03 §8/9: "A backup you've never restored is a hope, not a backup." This
records the drill that proved `backend/scripts/backup_db.py` and
`backend/scripts/restore_from_backup.py` work end-to-end, and the one real
finding it produced.*

## What was run (2026-07-04, local Docker, no production data touched)

Real production reads were correctly withheld pending explicit authorization, so
this drill used a **schema-accurate synthetic source**, not the live Supabase
DB: a throwaway Postgres container migrated with the project's real Alembic
revision (`bf2369a490a6`) and seeded with a few synthetic rows, standing in for
"production" without touching it.

1. `source-pg` (Postgres 17, Docker) — `alembic upgrade head` applied, then
   seeded one `sources`/`companies`/`opportunities` row each.
2. `minio` (Docker) — stand-in for Cloudflare R2/Backblaze B2 (S3-compatible,
   so the exact same `boto3` code path applies unchanged).
3. Ran the real `scripts.backup_db` module against `source-pg`, uploading to
   `minio`. Result: `daily/aspirova-2026-07-04.dump` uploaded successfully.
4. `scratch-pg` (Postgres 17, Docker, empty) — the restore target.
5. Ran the real `scripts.restore_from_backup` module: downloaded the object
   from `minio`, `pg_restore`'d into `scratch-pg`. Exit 0, no errors.
6. Verified: all 13 tables present in `scratch-pg`; the seeded
   `opportunities`/`companies` rows matched the source **row for row**
   (slug, title, category, apply_url all identical).

**Result: the backup → object storage → restore pipeline is proven correct.**

## Finding: pg_dump/pg_restore version skew (fixed)

The first attempt (`source-pg`/`scratch-pg` on Postgres 16, matching the
existing `postgres:16` used elsewhere in this session) failed on restore:

```
pg_restore: error: could not execute query: ERROR:  unrecognized configuration parameter "transaction_timeout"
```

Root cause: the `postgresql-client` package Debian/Ubuntu installs by default
resolves to **17.x**, and PG17's `pg_dump` emits a `SET transaction_timeout =
0;` preamble command — a GUC that doesn't exist before Postgres 17. Restoring
that dump into anything older than PG17 fails on this line.

This isn't a synthetic-test artifact — it would hit the **real** nightly
workflow the same way, since GitHub Actions' `ubuntu-latest` also resolves
`postgresql-client` to 17.x by default. If Supabase's actual server is on an
older major version, every real restore attempt would fail identically.

**Fix:** `.github/workflows/backup.yml` pins `postgresql-client-16`
explicitly via the official PGDG apt repository (verified locally in a
throwaway `ubuntu:24.04` container — see commit) instead of relying on
whatever version the distro's default package happens to resolve to. A
client version below 17 cannot emit a GUC that only exists in 17, so this is
safe against any Postgres 14/15/16/17 target. Re-running the drill on
Postgres 17 end-to-end (client and both servers aligned) confirmed the
scripts themselves have no other issues — exit 0, clean restore.

**Open item for the user:** confirm the actual Postgres major version your
Supabase project runs (Supabase dashboard → Project Settings → Infrastructure)
and adjust `postgresql-client-16` in `backup.yml` if needed — 16 was chosen as
a safe default (works against 15/16/17 targets), not a confirmed match to your
specific project.

## Addendum: real production drill confirms server is Postgres 17, client pin corrected (2026-07-05/06)

With R2 credentials live, ran the real thing (not synthetic data this time,
with explicit user authorization for both the production `pg_dump` and the
local restore of that real dump — Doc 08's production-read gate) in a Docker
worker matching the GH Actions environment exactly:

1. `uv run python -m scripts.backup_db` against the **real production**
   `DATABASE_URL` — succeeded, uploaded `daily/aspirova-2026-07-05.dump` +
   `weekly/aspirova-2026-W27.dump` (today rolled a weekly snapshot too) to
   the **real** Cloudflare R2 bucket. Confirmed present via a real
   `list_objects_v2` call (19,117,020 bytes each).
2. **First attempt used `postgresql-client-16`** (matching the then-current
   `backup.yml` pin) and failed immediately: `pg_dump: error: aborting
   because of server version mismatch: server version: 17.6, pg_dump
   version: 16.14`. This is the **opposite direction** of the version-skew
   bug found in the original drill above — `pg_dump` refuses outright to
   dump from a server *newer* than its own major version (it can only dump
   *older* servers, never newer ones). **This means the "safe default" of
   client 16 was actually wrong and would have failed every real nightly
   backup run in production** — this was never exercised before because
   every prior drill used synthetic Docker Postgres instances, never the
   real Supabase server.
3. **Fixed:** installed `postgresql-client-17` instead (matching the real
   confirmed server version, 17.6) — `backup.yml` corrected accordingly.
   Re-ran the backup: succeeded.
4. Restored the real dump into a throwaway **Postgres 17** container
   (matching the source, for a realistic same-version disaster-recovery
   scenario). `pg_restore` reported 254 ignored errors — every one of them
   Supabase-managed infrastructure noise (`supabase_vault` extension,
   `anon`/`authenticated`/`service_role`/`supabase_*` roles, `auth`/
   `extensions`/`realtime`/`storage`/`vault`/`graphql` schema grants) that
   simply don't exist in a vanilla Postgres container — none touched the
   application's own `public` schema.
5. Verified all 17 tables restored, and compared row counts against real
   production (COUNT-only queries, no PII) for every application table:
   `sources` 4, `companies` 111, `opportunities` 2996, `raw_listings` 3033,
   `users` 1, `bookmarks` 0, `plans` 5, `subscriptions` 0,
   `dream_companies` 0, `notifications` 0 — **exact match on every table**.
6. Tore down both containers immediately after verification, removing the
   local copy of real production data from the machine.

**Confirmed: the real Supabase Postgres server is 17.6.** `backup.yml` now
pins `postgresql-client-17` (was 16). Manual prerequisite (R2 bucket +
credentials) is now fully closed — see [PHASE-2-CLOSEOUT.md](PHASE-2-CLOSEOUT.md).

## Addendum 2: real GitHub Actions run caught a second, environment-specific bug (2026-07-06)

With `BACKUP_S3_*` added to GitHub Actions secrets, triggered the real
`Nightly Backup` workflow (`workflow_dispatch`, user-authorized) to prove it
works in the actual CI environment, not just the local Docker drill above.

**First real run failed** with the exact same error the local drill had
already fixed: `pg_dump: error: aborting because of server version
mismatch: server version: 17.6, pg_dump version: 16.14` — even though the
workflow's "Install PostgreSQL 17 client tools" step had already run
`apt-get install -y postgresql-client-17` successfully. Root cause:
**`ubuntu-latest` ships a `pg_dump` 16 binary already on `PATH`, baked into
the runner image itself**, not installed by this workflow. PGDG's
version-suffixed packages (`postgresql-client-17`) install their binaries
to `/usr/lib/postgresql/17/bin/`, never to `/usr/bin/` directly — so
installing the correct package doesn't override which `pg_dump` the shell
actually finds; the pre-existing image binary still wins by `PATH` order.
This didn't show up in the local Docker drill (Addendum above) because a
vanilla `ubuntu:24.04` container has no such pre-baked binary to compete
with.

**Fixed:** `backup.yml` now appends `/usr/lib/postgresql/17/bin` to
`$GITHUB_PATH` right after the apt install, so it's first on `PATH` for
every subsequent step in the job (including the actual backup script) —
plus a small `Verify pg_dump resolves to 17` step that fails loudly if this
ever regresses, instead of failing deep inside a stack trace.

**Re-ran the real workflow after the fix — succeeded.** `which pg_dump`
resolved to `/usr/lib/postgresql/17/bin/pg_dump` (17.10); the real
production backup uploaded `daily/aspirova-2026-07-05.dump` +
`weekly/aspirova-2026-W27.dump` to the real R2 bucket, entirely within the
actual GitHub Actions environment (not simulated). The nightly cron
(`17 19 * * *` UTC) is now confirmed working end-to-end, unattended.

## Running the drill again yourself

```bash
# 1. Point BACKUP_S3_* at your real R2/B2 bucket (backend/.env or GH secret)
uv run python -m scripts.backup_db

# 2. Restore into a THROWAWAY database only - this script has no notion of
#    "production" and will overwrite whatever --target-database-url points at
uv run python -m scripts.restore_from_backup \
  --key daily/aspirova-<date>.dump \
  --target-database-url postgresql://<scratch-db-connection-string>
```

## Retention

Confirmed via unit tests (`tests/test_backup.py`, since real S3 object ages
can't be manipulated in a live test): daily objects older than 7 days are
pruned by `LastModified`; only the newest 4 weekly objects are kept. Weekly
snapshots are additionally uploaded on the Sunday daily run
(`WEEKLY_DUMP_WEEKDAY` in `scripts/backup_db.py`).
