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
