# Aspirova database server — runbook

The app database moved from Supabase Pro (₹2,900/month) to a self-managed
Postgres 17 droplet on DigitalOcean (~₹810/month). Decision and evidence:
`docs/README.md` decision log, 2026-10-21.

## What lives where

| Piece | Where | Notes |
|---|---|---|
| All app data (`public` schema) | DigitalOcean droplet `aspirova-db`, Singapore (SGP1) | Same city as the Render API |
| Sign-in (Auth) | Supabase, Free plan | Code unchanged: `api/auth.py` calls `/auth/v1/user` |
| Resume PDFs (Storage) | Supabase, Free plan | Code unchanged: browser ↔ Storage directly |
| Backups | DO daily droplet backups (7 kept) **and** the nightly `pg_dump` to R2 (`backup.yml`) | `backup.yml` follows `DATABASE_URL`, so it needs no change |

The compatibility proof (2026-10-21) restored production into stock Postgres
17 capped at 1 CPU / 1 GB. Every table's row count matched. The full backend
suite passed (1,022). All 27 public endpoints returned 200, and every
scheduled job finished with exit 0 doing real work. Reads stayed error-free
during a live crawl, and memory peaked at 788 of 1,024 MiB.

## 1. Create the droplet (founder, ~5 minutes)

DigitalOcean → **Create → Droplets**:

- **Region:** Singapore (SGP1)
- **Image:** Ubuntu 24.04 (LTS) x64
- **Size:** Basic → Regular (SSD) → **$6/mo** (1 GB / 1 CPU / 25 GB / 1,000 GB transfer)
- **Backups:** enable, **daily** (+30%)
- **Authentication:** SSH key → paste the public key from the machine that will run step 2 (`~/.ssh/id_ed25519.pub`)
- **Monitoring:** tick the free metrics/alerting agent
- **Hostname:** `aspirova-db`

That comes to $7.80/month, about ₹810 with GST. Send the droplet's IPv4 address to whoever runs step 2.

Optional: under Monitoring → Alerts, set CPU > 90% for 10 min, memory > 90% for 10 min, and disk > 80%, emailing the founder.

## 2. Provision (~5 minutes)

```bash
ssh root@<ip> 'bash -s' < infra/db/provision.sh
```

The script is safe to re-run. Its closing check should show `server 17.x`, `locale i en-US / en_US.UTF-8`, `owner aspirova_app`, the
`citext / pg_stat_statements / pg_trgm / vector` extensions, `ssl on`, 2 GB of
swap, and ufw allowing only 22 and 5432. The app password is stored in
`/root/aspirova_app_password` and is never printed.

## 3. Cutover (~45 minutes; founder present for 3e)

Pick a slot with no scheduled job running. **18:00 UTC (23:30 IST)** is best.
The last digest is done by 13:10 UTC, and the 19:17 UTC nightly backup then
becomes the first real run against the new server.

**3a. Freeze writers.** User writes (bookmarks, page views) keep going to
Supabase until 3e. At this hour that should be close to nothing.

```bash
for w in crawl-tier1 notifications-digest notifications-hackathon weekly-report backup enrich; do gh workflow disable "$w.yml"; done
gh run list --status in_progress   # must be empty
```

**3b. Hand the droplet the source URL.** It goes through stdin, never onto a command line or the screen:

```bash
cd backend && uv run python -c "from core.config import get_settings as g; print(g().database_url.replace('postgresql+psycopg://', 'postgresql://', 1))" \
  | ssh root@<ip> 'umask 077 && cat > /root/.supabase_url'
```

The migration script strips `\r` from this file itself. On Windows, `print()`
into a pipe writes CRLF.

**3c. Copy and verify.**

```bash
ssh root@<ip> 'bash -s' < infra/db/migrate_from_supabase.sh
```

It must end with `RESULT: every table matches Supabase exactly`. Only the
page-view counter may differ. If anything else differs, stop. To reset and
retry: `ssh root@<ip> 'sudo -u postgres dropdb aspirova'`, then re-run step 2 and 3c.

**3d. Gate: the real API on the new server must match production.** Start a
local API pointed at the droplet (`DATABASE_URL` overridden in the
environment, mail/cache/payment keys blank, port 8100). Then:

```bash
cd backend && uv run python ../infra/db/compare_endpoints.py --exact
```

Every counted total must match. A failure on production's side, such as a
cold-search timeout, is a baseline problem and not a gate failure. Re-run it.
**Never run test suites or write scripts against the droplet from here on.
It is production.**

**3e. Switch.** The new URL is
`postgresql+psycopg://aspirova_app:<password>@<ip>:5432/aspirova?sslmode=require`.
Build it on the operator's machine from `/root/aspirova_app_password`,
without printing it. Then:

1. `gh secret set DATABASE_URL < <file>` (covers all six DB workflows). The file
   must hold the URL with **no `\r`**. Text written by Python on Windows ends in
   CRLF, and libpq keeps the `\r` as part of the database name. That broke the
   first rehearsal: Supavisor rejected database `"postgres\r"`.
2. Render → `aspirova-api` → Environment → `DATABASE_URL` → paste → **Save, rebuild and deploy**
3. Update the local `backend/.env`, then delete the temporary file

Leave `UNSUBSCRIBE_SECRET` alone. It's independent of the database since
PR #122, so emailed unsubscribe links keep working.

**3f. Verify live.** Check that `/health` returns 200 and that Render logs show
no DB errors. Run a few uncached reads and compare their `x-db-time-ms`.
`compare_endpoints.py --candidate https://aspirova-api.onrender.com --baseline http://127.0.0.1:8100`
should be clean.

**3g. Unfreeze.**

```bash
for w in crawl-tier1 notifications-digest notifications-hackathon weekly-report backup enrich; do gh workflow enable "$w.yml"; done
gh workflow run backup.yml   # a backup object must land in R2
```

**3h. Tidy the droplet.** Run `rm /root/.supabase_url`. Keep
`/var/lib/postgresql/migration/` until step 5, then delete it.

## 4. Rollback (first 7 days)

Supabase keeps the frozen pre-cutover data untouched. To roll back, set
`DATABASE_URL` back to the Supabase URL in GitHub and Render. Writes made on
the droplet after cutover are not on Supabase. Copy user tables back first
with a data-only `pg_dump` of `bookmarks`, `saved_searches`, `users`,
`subscriptions`, `dream_companies`, `resume_profiles` and `notifications`.

## 5. Retire Supabase Pro (after 7 clean days)

1. **Back up Auth separately.** Today's nightly dump covers the whole Supabase
   database, `auth` included. After the move it only covers the droplet, so
   the login accounts need their own nightly dump of Supabase's `auth` schema
   to R2. It doubles as the Free plan's keep-alive, since Free projects pause
   after 7 idle days. This needs its own change and the secret `SUPABASE_DB_URL`.
2. Take one final full `pg_dump` of Supabase to R2 as an archive.
3. Drop the `public` tables on Supabase. The Free plan's database cap is 500 MB.
4. Downgrade the organisation to Free **before the next billing date**.
5. Update CLAUDE.md "Where things stand" to say the DB is the droplet.

## 6. Disaster recovery

- **Bad change, droplet fine:** run `python -m scripts.restore_from_backup --key <r2-key> --target-database-url <url>` into a fresh database, then swap.
- **Droplet broken:** DigitalOcean → droplet → Backups → restore the latest daily image. The IP stays the same, so `DATABASE_URL` doesn't change.
- **Droplet gone:** step 1 → step 2 → restore the latest R2 backup with `restore_from_backup` → step 3e with the new IP.
