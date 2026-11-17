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
# Hackathons merged into the daily email on 2026-11-08 for Resend's 100/day free limit.
for w in crawl-tier1 notifications-digest weekly-report backup enrich; do gh workflow disable "$w.yml"; done
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
for w in crawl-tier1 notifications-digest weekly-report backup enrich; do gh workflow enable "$w.yml"; done
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

**Done 2026-11-02.** Final archive: `archive/supabase-final-2026-11-02.dump` in R2 (279,989,515
bytes, sha256 `65302fe9cb95891e…`; read in full with 0 errors across 63 tables). The `public` tables
were dropped at about 16:45 UTC, leaving 13 MB, and the organisation moved to Free at about 16:52 UTC.
Google and GitHub sign-in and the password-reset email were tested afterwards. The rollback in
section 4 no longer works on its own: going back to Supabase now means restoring that archive first.

## 6. Disaster recovery

- **Bad change, droplet fine:** run `python -m scripts.restore_from_backup --key <r2-key> --target-database-url <url>` into a fresh database, then swap.
- **Droplet broken:** DigitalOcean → droplet → Backups → restore the latest daily image. The IP stays the same, so `DATABASE_URL` doesn't change.
- **Droplet gone:** step 1 → step 2 → restore the latest R2 backup with `restore_from_backup` → step 3e with the new IP.

## Account deletion, retention and cleanup retries

`POST /account/delete` commits a permanent `users.deleted_at` tombstone and
purges personal columns and user-owned rows before calling Supabase. Billing
records retain the account ID. `users.deletion_pending` contains only the names
of unfinished external steps (`storage`, `auth`), never addresses or credentials.
Resume Storage cleanup precedes Auth deletion because Supabase cannot delete a
user who still owns Storage objects. Missing objects/users (404) count as success.

After deploying and applying the migration, retry pending cleanup from the backend:

```bash
uv run python -m scripts.finish_account_deletions
```

Run this after any Supabase outage or failed deletion cleanup, and until it exits
zero. It is idempotent, clears each completed step, and exits nonzero if work is
still pending. It requires the app database and `SUPABASE_URL` /
`SUPABASE_SERVICE_KEY` in the server environment. Do not run it against production
as a test. Arrange a recurring operational run so pending cleanup is not forgotten.

`scripts/backup_db.py` retains 7 daily backups and the 4 newest weekly backups
for both the app DB and Supabase Auth. DigitalOcean keeps 7 daily droplet backups.
Rotation depends on successful backup runs. The final archive
`archive/supabase-final-2026-11-02.dump` is outside automatic retention and has no
configured expiry; do not promise users that every backup expires within a fixed
number of days. An archive expiry policy still needs an architect/owner ruling.

Before restoring an older backup into service, preserve the current tombstone IDs
and deletion times securely and reapply their purges to the restored DB before
enabling API traffic or email jobs. Otherwise a restore can undo a deletion and
re-enable mail. Never restore erased personal data into a live account.

Known limits requiring an architect ruling: `setup_resume_storage.sql` authorizes
direct Storage requests by `auth.uid()` alone. Supabase deletion invalidates
refresh tokens but already-issued access tokens remain valid until expiry
([Supabase user-management documentation](https://supabase.com/docs/guides/auth/managing-user-data#deleting-users)).
The app tombstone blocks every authenticated app endpoint, but cannot itself
prevent a retained token from uploading a new file directly to Storage after a
successful cleanup. Closing that window needs a Supabase-side session/RLS guard
or an amended cleanup design. No such external policy change is included here.
Similarly, mail already submitted to Resend cannot be recalled; sender locks
prevent new submissions after the tombstone commits, not later delivery of mail
already accepted by the provider. Deletion is blocked only by an active/trialing
Razorpay subscription within its period and grace window that is not scheduled
to cancel. Complimentary/manual subscriptions without a Razorpay ID and periods
ended beyond grace do not block deletion. Confirmation mail is attempted only
after the purge transaction commits, using the address captured before erasure.

## Cutover record — 2026-10-21

| Step | When (UTC) | Result |
|---|---|---|
| Droplet created + provisioned | 14:12 | PG 17.11, pgvector 0.8.7, ICU en-US; 5/5 outside-in access checks passed |
| Rehearsal | ~14:30 | Copy exact on all 25 tables; `compare_endpoints --exact` 26/26 |
| Writers frozen | 14:35 | The hackathon digest was mid-run (GitHub ran it 1.5 h late); waited for it (done 14:35:32) |
| Copy | 14:37–14:40 | Dump 81 s, restore 103 s; every table matched Supabase |
| Gate | 14:41 | 26/26, every total exact |
| GitHub `DATABASE_URL` + `SUPABASE_DB_URL` | 14:41:54 | Set from CR-free files |
| Render switched | 14:48:07 | First connection from Render (`74.220.52.217`, TLS) |
| Live check | 14:49 | 26/26 healthy on production |
| Lost writes | 14:50 | None: user tables fingerprint-identical on both sides (MD5 of all 40 users) |
| Backup on the new server | 14:51 | `daily/aspirova-2026-10-21.dump` uploaded to R2 |

Uncached DB time on production, before → after: search "engineer" 11–21 s (sometimes
HTTP 500) → **296 ms**; "data" internships 742 ms → 83 ms; competitions 276 ms → 58 ms;
company page 330 ms → 21 ms; main feed 571 ms → 531 ms.

Supabase Pro stays untouched as the rollback target until **2026-10-28**. Step 5 follows.

## Flag a scam or withdrawn listing

From `backend/`, with the founder's existing production environment configured, preview first:

```sh
uv run python -m scripts.flag_listing --slug <slug> --kind scam --note "Unauthorised fee request" --source-url https://example.com/safety-notice --dry-run
uv run python -m scripts.flag_listing --slug <slug> --kind scam --note "Unauthorised fee request" --source-url https://example.com/safety-notice
uv run python -m scripts.flag_listing --slug <slug> --clear
```

Use `--kind recalled` for a recalled listing. `--source-url` is optional but must be HTTPS when supplied; without it, the Aspirova listing page and founder note are the reference, with no external warning link. Repeating a command is safe. Flagged listings are retained by closed-listing cleanup so saved warnings and notice links remain available. Clearing restores the prior status and removes only the closure timestamp created by the flag. The command refreshes the API detail cache and then requests listing-page revalidation after commit; check both printed results. Saved notices run with the existing daily `--closing-soon` worker. Email follows the Saved listings preference; in-app warnings stay on. Closures settle for 24 hours. The breaker holds each candidate when catalogue-wide early closures within 24 hours either side of its own `closed_at` exceed `SAVED_CLOSURE_NOTICE_BREAKER` (default 1500); safety bypasses it. One query per run reads hourly counts from the last 8 days, covering the full window of every 7-day candidate. Held candidates get no in-app row or email, and stay held on later runs unless closures reopen. A held candidate's pending email is cancelled like any other ineligible event. The run logs one warning with the number held and the largest window count.

For flags and clears, the order is **DB commit → API detail refresh → listing-page revalidation**.
The refresh bypasses the cached detail and replaces it before Vercel regenerates the listing page.
When both requests succeed, the listing page updates at once on its next request. Founder commands
leave landing list pages alone so they cannot regenerate from still-cached feeds: feeds catch up
within the normal API window (15 minutes), and list pages within their normal window (up to 6 h).
Set both `REVALIDATE_URL` and `REVALIDATE_SECRET` in the founder's local `backend/.env`, using
**the same values as the GitHub Actions secrets**. If revalidation is unconfigured, the script prints
one warning that the listing page may stay stale for up to 7 days. A failed refresh or revalidation
leaves the DB change committed; repeat the command to retry the cache work.

Identity and slug matches preserve a flagged listing. A repost under a new source/external id appears as a new listing and must be flagged separately; fuzzy title matching considers active listings only, so an old withdrawal cannot absorb a later genuine opening.


## TRUST-05: report triage and public corrections

Run from `backend/` using the normal founder credentials. Never point tests at production.
The founder applies migration `d2f6a8c4e9b1` before merging/deploying this change. A database
receipt default keeps the old intake working during deployment; the new API generates full-alphabet
receipts and retries uniqueness collisions:

```sh
uv run alembic upgrade head
uv run python -m scripts.reports list
uv run python -m scripts.reports list --status all --category wrong_deadline --limit 100
uv run python -m scripts.reports show R-ABC234
uv run python -m scripts.reports triage R-ABC234 --note "Checking the official source."
uv run python -m scripts.reports triage R-ABC234 --dry-run
uv run python -m scripts.reports resolve R-ABC234 --resolution corrected --note "The official deadline is 1 December." --set-deadline 2026-12-01 --dry-run
uv run python -m scripts.reports resolve R-ABC234 --resolution corrected --note "The official deadline is 1 December." --set-deadline 2026-12-01
uv run python -m scripts.reports resolve R-ABC234 --resolution closed_listing --note "The source no longer accepts applications." --close-listing
uv run python -m scripts.reports resolve R-ABC234 --resolution withdrawn --note "A fee request was confirmed. Do not pay." --withdraw --kind scam
uv run python -m scripts.reports resolve R-ABC234 --resolution withdrawn --note "The organiser recalled this listing." --withdraw --kind recalled
uv run python -m scripts.reports resolve R-ABC234 --resolution duplicate --note "Use the original listing." --duplicate-of original-listing-slug
uv run python -m scripts.reports resolve R-ABC234 --resolution corrected --note "The employer attribution was corrected." --company correct-company-slug
uv run python -m scripts.reports resolve R-ABC234 --resolution no_change --note "The official source confirms the current details."
uv run python -m scripts.reports resolve R-ABC234 --resolution not_reproducible --note "The link currently works; no issue could be reproduced."
uv run python -m scripts.reports resolve R-ABC234 --resolution spam --note "No actionable listing issue was found."
uv run python -m scripts.reports stats --days 30
uv run python -m scripts.reports remind
```

Use a different unresolved receipt for each resolution example. A resolved outcome is immutable;
repeating its resolution and note is a no-op (no repeated correction or reporter email).
Each resolve accepts at most one listing action, supports `--dry-run`, and commits the report,
listing diff and in-app notice together. Resolving an open report records triage at the same time.
For a resolution with a listing action, the order is **DB commit → API detail refresh → listing-page
revalidation**. Both results are printed. The API refresh replaces the detail cache before Vercel
regenerates it, so the listing page updates at once on its next request when both calls succeed.
Actionless resolutions and triage do not refresh listings. Repeating a listing-action resolution
retries the cache work without changing the outcome or sending a second reporter email.
Founder corrections do not revalidate landing list pages: feeds catch up within the normal API
window (15 minutes), and list pages within their normal window (up to 6 h). Put `REVALIDATE_URL`
and `REVALIDATE_SECRET` in the founder's local `backend/.env`, with **the same values as the GitHub
Actions secrets**. If either is missing, the script warns that the listing page may stay stale for
up to 7 days. Crawler revalidation keeps its existing behavior, including landing list pages.
The one contact-email submission also happens after commit. An email failure is logged;
re-running a resolved command does not send a second email. Receipt codes are opaque; lookup at
`/report/status?ref=R-ABC234` exposes only status, dates, category, listing and public outcome.
All `--note` text (including triage notes) is public: never include names, contact details or
report text. `show` is a private founder command and includes the full report.

Targets are **triage within 48 hours of receipt** and **resolution within 7 days of receipt**,
for every plan. `OVERDUE` means open past 48 hours, or triaged and unresolved past 7 days.
Stats use the cohort received within `--days`: elapsed hours are measured from creation,
median and linearly interpolated p90 use completed milestones, and SLA percentages include
completed milestones plus pending reports already past the relevant target. Pending reports still
within target are excluded from that denominator. Empty samples report null, not 100%.
The open-overdue count includes the whole backlog, even older than the cohort.

The daily digest workflow calls `remind` after its existing steps, including after a prior failure;
it never fails the workflow. Each invocation sends one founder summary only when overdue reports
exist. Configure `WAITLIST_NOTIFY_EMAIL` as a GitHub Actions secret alongside the existing Resend
secrets. It sends no reporter reminder emails.

Manual closures ('user_report'/'duplicate'), deadlines and company assignments beat crawls.
Correction history stays on the listing; only date, field and fixed public copy are exposed.
Manual closures also survive cleanup, preventing a later crawl from recreating them.
Withdrawals reuse `scripts.flag_listing.flag_listing`; clearing a safety flag cannot reopen a
manual report closure. Account deletion still purges owned reports and notifications.
Reporting is never attributed publicly and never changes the reporter's account or plan.
