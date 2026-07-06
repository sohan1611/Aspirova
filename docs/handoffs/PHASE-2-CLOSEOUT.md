# PHASE 2 CLOSEOUT — Manual Prerequisite Setup

*Chief Architect → User. Phase 2 is engineering-complete, merged, and deployed (see [PHASE-2-REPORT.md](PHASE-2-REPORT.md)). Four external accounts gate final verification. **Payments (Razorpay) is deferred to last by the user's decision** — this doc covers the other three now, payments at the end.*

**Division of labor:** the User creates accounts + pastes keys (an agent cannot). Sonnet (engineer) runs the verification once keys are in place. Do NOT need a custom domain or any paid tier for any of this.

---

## The three key destinations (referenced below)

Every key goes into **`backend/.env`** (so it can be tested locally) **plus** one cloud location:

| Destination | How to reach it | Which keys live here |
|---|---|---|
| **`backend/.env`** (local file) | edit the file directly; it's gitignored, never committed | all of them (local testing) |
| **Render env vars** | dashboard.render.com → `aspirova-api` service → **Environment** → add variable → **Save** (auto-redeploys) | the ones the **live API** reads: `UPSTASH_*` (and later `RAZORPAY_*`) |
| **GitHub Actions secrets** | github.com/sohan1611/Aspirova → **Settings → Secrets and variables → Actions → New repository secret** | the ones the **cron workflows** read: `BACKUP_S3_*`, `RESEND_*` |

`DATABASE_URL` and `SUPABASE_*` already exist in both places. Add only the new ones.

---

## 1. Resend (start FIRST — DNS has lead time)

Powers the daily digest + (later) Pro instant alerts. `core/email_client.py` + `pipeline/notifications.py`.

**Account:** sign up at resend.com (free tier: 3,000 emails/mo, 100/day).

**Sending domain: `aspirova.org` (owned).** Full domain verification — satisfies the SPF/DKIM/DMARC deliverability gate (handoff §7).

1. Resend → **Domains → Add Domain** → enter `aspirova.org` (Resend provisions sending under a `send.` subdomain automatically).
2. Resend displays the exact DNS records to add — **add them verbatim** at wherever `aspirova.org`'s DNS is managed (your registrar's DNS panel, or Cloudflare if you moved the nameservers there). They will be roughly: an **MX** record + an **SPF `TXT`** on `send.aspirova.org`, and a **DKIM `TXT`** (`resend._domainkey`). Copy exactly what the dashboard shows — do not hand-type the values.
3. **Add DMARC yourself** (Resend may not auto-generate it, and §7 requires it): a `TXT` record at `_dmarc.aspirova.org` with value `v=DMARC1; p=none; rua=mailto:you@aspirova.org`. `p=none` is monitor-only — correct to start.
4. Click **Verify** in Resend. Propagation is minutes-to-hours; the status flips to *Verified* when the records are seen.

**Keys to grab:** Resend → **API Keys → Create API Key** (permission: *Sending access*). Copy it — shown once.
- `RESEND_API_KEY` = the `re_...` key
- `RESEND_FROM_EMAIL` = `noreply@aspirova.org` (any address at the verified domain)

**Paste into:** `backend/.env` **+ GitHub Actions secrets** (both keys).

**Done looks like (Sonnet verifies):** `uv run python -m scripts.notification_worker --digest` sends a real digest to a seeded opted-in user's address and the row lands `status='sent'`.

**✅ VERIFIED (2026-07-05).** Domain `aspirova.org` has every sending-relevant DNS record verified (DKIM, SPF, bounce-MX) — the dashboard's "Partially Verified" status refers only to an unrelated, optional inbound-mail-receiving MX, not a blocker. `RESEND_API_KEY` authenticates (confirmed via `resend.Domains.list()`). A real test email sent successfully via the direct API, and the actual production pipeline (`_render_digest()` + `send_email()`) was proven end-to-end with real data delivered to a real inbox, without touching the one existing production user. `RESEND_API_KEY`/`RESEND_FROM_EMAIL` confirmed present in GitHub Actions secrets and correctly referenced by `.github/workflows/notifications-digest.yml` and the instant-alerts step in `.github/workflows/crawl-tier1.yml`.

---

## 2. Upstash Redis (do SECOND — fastest win)

Powers rate limiting + read cache, and unblocks the cached-p95 re-measure that closes the Lever-2 decision. `core/redis_client.py`, `api/middleware.py`.

**Account:** sign up at upstash.com (GitHub/Google login; free tier is plenty).

**Steps:**
1. **Create Database → Redis.**
2. Name it (e.g. `aspirova`). **Primary Region: choose `AWS ap-southeast-1 (Singapore)`** — the live API is on Render Singapore, so this minimizes the rate-limit/cache round-trip.
3. Free/pay-as-you-go tier is correct.
4. On the database page, scroll to the **REST API** section. Copy the two values (they're named exactly like our env vars):
   - `UPSTASH_REDIS_REST_URL`
   - `UPSTASH_REDIS_REST_TOKEN`

**Paste into:** `backend/.env` **+ Render env vars** (both keys). Render will auto-redeploy.

**Done looks like (Sonnet verifies):** in production, a burst of requests returns `429` with `Retry-After`; a repeated `/feed` returns `X-Cache: HIT` with `X-DB-Time-Ms ≈ 0`; `measure_latency.py` re-run shows the cached p95.

**✅ VERIFIED (2026-07-05).** Credentials live in `backend/.env` + Render env vars. Real SET/GET round trip against Upstash succeeded. Production cache-hit proven (`/feed?limit=3` twice: MISS at `X-DB-Time-Ms: 301.17`/`X-Total-Time-Ms: 1553.94`, then HIT at `X-DB-Time-Ms: 0.00`/`X-Total-Time-Ms: 6.88`). Rate limiting proven exact: a 65-request burst against `/feed` returned 60×`200` then 5×`429`, matching the configured `60/min` limit precisely (the `429`'s own `Retry-After` header wasn't re-captured live, since the fixed window had already rolled over by the follow-up check — the burst result alone is conclusive). Cached p95 re-measured across all three endpoints: **7.9-8.1ms**, down from the uncached 192-293ms (see the addendum in [PART-2.3-LEVER-2-MEASUREMENT.md](PART-2.3-LEVER-2-MEASUREMENT.md)). Reaffirms the Lever-2 no-migrate ruling.

---

## 3. Cloudflare R2 or Backblaze B2 (do THIRD — no lead time)

Powers the independent nightly backup + real restore drill. `scripts/backup_db.py`, `.github/workflows/backup.yml`. Pick **one** — the code is S3-compatible either way.

### Option A — Cloudflare R2
1. Cloudflare dashboard → **R2** → **Create bucket** → name `aspirova-backups` (private).
2. **R2 → Manage R2 API Tokens → Create API Token** → permission **Object Read & Write**, scoped to that bucket. Copy the **Access Key ID** and **Secret Access Key** (shown once).
3. Your **endpoint** is `https://<ACCOUNT_ID>.r2.cloudflarestorage.com` — the account ID is on the R2 overview page.
4. Values:
   - `BACKUP_S3_ENDPOINT_URL` = `https://<ACCOUNT_ID>.r2.cloudflarestorage.com`
   - `BACKUP_S3_ACCESS_KEY_ID` = the Access Key ID
   - `BACKUP_S3_SECRET_ACCESS_KEY` = the Secret Access Key
   - `BACKUP_S3_BUCKET` = `aspirova-backups`

### Option B — Backblaze B2
1. Backblaze → **B2 Cloud Storage → Create a Bucket** (private) → name `aspirova-backups`. Note the **region** shown (e.g. `us-west-004`).
2. **App Keys → Add a New Application Key**, scoped to that bucket. Copy **keyID** and **applicationKey** (shown once).
3. Values:
   - `BACKUP_S3_ENDPOINT_URL` = `https://s3.<REGION>.backblazeb2.com`
   - `BACKUP_S3_ACCESS_KEY_ID` = keyID
   - `BACKUP_S3_SECRET_ACCESS_KEY` = applicationKey
   - `BACKUP_S3_BUCKET` = `aspirova-backups`

**Paste into:** `backend/.env` **+ GitHub Actions secrets** (all four keys).

**Done looks like (Sonnet verifies):** `uv run python -m scripts.backup_db` lands a real object in the bucket; `scripts.restore_from_backup` restores it into a throwaway DB and the rows match.

**✅ VERIFIED (2026-07-05/06), with a real bug caught and fixed.** Ran the real backup against real production, with your explicit authorization: `pg_dump` uploaded `daily/aspirova-2026-07-05.dump` + a weekly snapshot to the real R2 bucket, confirmed present via a real listing (19MB each). **Found:** the backup workflow's `postgresql-client-16` pin was wrong — your Supabase server is actually **Postgres 17.6**, and `pg_dump` refuses to dump from a server newer than itself, so the real nightly cron would have failed every run. Fixed by pinning `postgresql-client-17` instead (`.github/workflows/backup.yml`). Re-ran the backup successfully, then restored the real dump into a throwaway Postgres 17 container (with your explicit authorization) — all 17 tables restored, and every application table's row count matched production exactly (`sources` 4, `companies` 111, `opportunities` 2996, `raw_listings` 3033, `users` 1, plus 6 more all matching). Containers torn down immediately after. Full writeup: [PART-2.2-RESTORE-DRILL.md](PART-2.2-RESTORE-DRILL.md) addendum.

**GitHub Actions secrets added and confirmed working (2026-07-06).** Triggered the real `Nightly Backup` workflow twice: the first run hit a second real bug — `ubuntu-latest` ships a pg_dump 16 binary already on `PATH`, which shadowed the correctly-installed `postgresql-client-17` package (fixed by prepending `/usr/lib/postgresql/17/bin` to `$GITHUB_PATH`). The second run succeeded end-to-end in the real GitHub Actions environment: `pg_dump` resolved to 17.10, backup uploaded to the real R2 bucket. The nightly cron is now fully verified, unattended. **All three non-payments manual prerequisites (Resend, Upstash, R2) are now closed.**

---

## After the three land — flip to Sonnet

`/model claude-sonnet-4-6`, then have Sonnet verify each gate above end-to-end and record the results. That takes Phase 2 to **"everything verified except payments."**

## Deferred to last: Payments (Razorpay)
When ready: create a Razorpay account (test mode), then Sonnet runs the 3-step wire (keys → `scripts/setup_razorpay_plans.py` → register webhook URL `https://aspirova-api.onrender.com/payments/webhook` → capture `RAZORPAY_WEBHOOK_SECRET`), verifies a real test-mode checkout, and folds in the **webhook out-of-order/replay fix** flagged in the Phase-2 review. That is the final Phase-2 gate; once green, Phase 3 (AI) can be handed off.

## Optional, account-free
CI shows a Node-20 deprecation warning — bumping the workflow action versions (`actions/checkout@v4`→v5, etc.) is trivial housekeeping Sonnet can do anytime.
