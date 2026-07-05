# PHASE 2 REPORT — Production-Ready Platform

*From: Lead Engineer (Claude Sonnet) · To: Chief Architect (Opus) · Status: ENGINEERING COMPLETE, merged to `master` and deployed live — 4 of 8 parts' full acceptance criteria remain gated on manual prerequisites (external accounts) only the user can create*

---

## 1. What was built

All 8 parts of [PHASE-2-HANDOFF.md](PHASE-2-HANDOFF.md), in the sequence the hard constraints required (Lever-1 before new adapters; rate limiting early).

| Part | Outcome |
|---|---|
| 2.1 Rate limit + cache | Upstash-backed per-IP/per-user rate limiting + short-TTL read cache; fails open by design; §11 addendum pinned the open design questions before build |
| 2.2 Backups | Independent nightly `pg_dump` → S3-compatible storage (R2/B2-agnostic); real drill (Docker, MinIO, throwaway Postgres) caught and fixed a pg_dump/pg_restore version-skew bug before it could hit production |
| 2.3 Latency instrumentation | `X-Total-Time-Ms`/`X-DB-Time-Ms` on every response; **the Lever-2 measurement is now taken against live production** (§3 below) |
| 2.4 Crawler bulk ops (Lever 1) | Per-listing round trips replaced with one bulk board-state read; measured 78.8% round-trip reduction for the realistic steady-state re-crawl case |
| 2.5 Lever + Ashby + aggregator | Two new ATS adapters + RemoteOK (first best-effort aggregator) with dynamic company resolution; verified end-to-end against real live APIs in a throwaway-DB drill |
| 2.6 Plans, payments, gating | `plans`/`subscriptions`/`dream_companies` schema; `can(user, feature)` the single gating seam; Razorpay checkout + webhook built and tested (signature verification is real, fully local) |
| 2.7 Notifications | Daily digest + Pro instant dream-company alerts, both gated through `can()`, capped/deduped via `notifications`; Resend wrapped behind one seam |
| 2.8 Test-infra hardening | Session-scoped shared engine fixed the carried-forward Supabase-pooler connection flake; unique per-test slugs make `test_runner_isolation.py` robust to interruption |

**9 commits since the Phase-2 handoff** (including the architect's own Part 2.1 addendum), all authored solely as `sohan1611` — no co-author trailers, no Dependabot. Merged to `master` via fast-forward (linear history, no conflicts) and pushed; CI green (both `backend` and `frontend` jobs); Render's auto-deploy picked it up within minutes of the push, confirmed live.

---

## 2. Gate evidence (PHASE-2-HANDOFF.md §7, verified against live production and the real dev DB, not assumed)

1. **Payments work end-to-end in Razorpay test mode** — ⚠️ **partially blocked.** Checkout-creation and webhook-handling code is built and correctly integrated with the real `razorpay` SDK; the webhook's signature verification is genuinely tested (a real HMAC-SHA256 signed payload, verified exactly as Razorpay's own client does it) covering activated/charged/cancelled/halted events and rejecting invalid/missing signatures. **What's not verified: an actual Razorpay checkout completing end-to-end**, because no Razorpay account exists yet (manual prerequisite, §10) — `scripts/setup_razorpay_plans.py` is written and ready but has never run.
2. **Gating is data-driven via `can()`** — ✅ verified. `test_gating.py` (10 tests) covers free/pro_lite/pro resolution, lapsed-subscription fallback, trialing grants access, most-recent-subscription-wins, missing-key-resolves-false. `test_dream_companies.py` (7 tests) proves the Free/Pro limit split end-to-end against real Postgres via `dependency_overrides`, not mocks: a Free user is blocked at 1, a Pro user is unlimited, re-adding an already-tracked company is a no-op not a limit violation.
3. **A Pro user receives a real instant alert; a Free user receives a daily digest; caps work** — ⚠️ **partially blocked.** The worker logic is fully built and tested (10 tests) against real Postgres: eligibility via `can()`, frequency caps, suppression via the `notifications` table, and a real bug the tests themselves caught (the digest's generic fallback could leak back in an opportunity that was correctly excluded via the dream-company path — fixed). **What's not verified: an actual email landing in an inbox**, because no Resend account/verified sending domain exists yet (manual prerequisite, §10).
4. **≥3 ATS adapters + 1 aggregator ingesting via the seam; cross-source dedup verified** — ✅ verified live. A full drill (Docker, throwaway Postgres, real live APIs) ingested Greenhouse (12 companies, 2,328 opportunities), Lever (3 companies, 67), Ashby (3 companies, 233), and RemoteOK (100 listings, 93 new companies dynamically resolved — including correct HTML-entity unescaping). Sources + companies are now seeded in the real production DB too (`lever`/`ashby`/`remoteok` sources created; 6 new + 12 updated companies).
5. **Lever-1 landed: crawl comfortably under the timeout at the new source count** — ✅ verified. Round-trip counting (not guessed) against a throwaway Postgres: the realistic steady-state re-crawl (200 unchanged listings + 1 new posting — what a real 2-hourly re-crawl actually looks like once a board is seeded) dropped from a theoretical 1,005 round trips to 213 — a 78.8% reduction. Honestly recorded: the pure cold-start case (all-new listings) shows no improvement (1,007 vs 1,000) — expected and acceptable, since cold-starting a board happens once per company ever, not on the repeated crawl this fix targets.
6. **Backups running with one restore actually tested** — ⚠️ **partially blocked.** The full pipeline (dump → S3 upload → retention pruning → download → restore) was proven correct in a live drill using a real Alembic-migrated schema and a local MinIO standing in for R2/B2 — all 13 tables and every row matched exactly after restore. That same drill caught a real pg_dump/pg_restore version-skew bug (Debian's default `postgresql-client` resolves to 17.x, whose `pg_dump` emits a GUC that breaks restore into anything older) and fixed it by pinning the client version in the workflow. **What's not verified: a restore from REAL R2/B2**, because no bucket exists yet (manual prerequisite, §10) — the nightly GH Actions workflow is live but will no-op until `BACKUP_S3_*` secrets are set.
7. **Rate limiting live; isolated DB-hop p95 measured and recorded** — ✅ verified, with an honest caveat. Rate-limiting and caching middleware are live in production right now (confirmed: `/feed` returns `X-Cache`/`X-Total-Time-Ms`/`X-DB-Time-Ms` headers on every response) — but Upstash isn't configured yet (manual prerequisite, §10), so by design (§11.2's fail-open rule) nothing is actually being throttled or cached yet; every request today is a clean cache miss. **The isolated DB-hop p95 measurement is done** (§3 below) — this was possible precisely because caching is currently a no-op, giving an uncached, unambiguous DB-hop reading.
8. **Full test suite green and stable; HARD RULES hold** — ✅ verified. 130/130 backend tests pass; ran 4 times back-to-back post-fix (Part 2.8) with no connection errors, consistently ~50-75s (previously 80-140s with an occasional pooler-exhaustion error). Gating goes through `can()` exclusively (grepped — no scattered `if plan ==`); plans/prices are seeded data, not code; no AI/pgvector/embeddings anywhere; the crawler still only runs on GitHub Actions, the notification worker likewise (never the Render web dyno).

---

## 3. The Lever-2 measurement (PHASE-2-HANDOFF.md §4)

Full writeup: [PART-2.3-LEVER-2-MEASUREMENT.md](PART-2.3-LEVER-2-MEASUREMENT.md). Measured against live production, n=30/endpoint, same methodology as the Phase-1 report.

| Endpoint | X-Total-Time-Ms p95 | X-DB-Time-Ms p95 |
|---|---:|---:|
| `/feed` | 292.7ms | 201.5ms |
| `/search` | 207.7ms | 140.6ms |
| `/opportunity/{slug}` | 192.9ms | 126.8ms |

**The isolated DB-hop p95 is 127–202ms** — a real, consistent cross-region cost (~65-70% of total server-side time), but **total server-side time is itself already under the 300ms target in every endpoint**, even with the DB hop included and before Upstash caching is even live to help further. This leans toward Lever-2 (Singapore consolidation) not being urgent right now, per the handoff's own decision rule — but that call is the architect's, not engineering's.

---

## 4. Manual prerequisites still pending (PHASE-2-HANDOFF.md §10 — flagged as each part reached them, not discovered now)

None of these block the code from working correctly once created — every integration point fails open/closed safely without them (Doc 08-consistent):

1. **Upstash Redis** — rate limiting/caching currently no-op (fail open). Needed to actually enforce limits and get cache-hit benefit.
2. **Cloudflare R2 or Backblaze B2** — nightly backup workflow is live but has nothing to write to yet.
3. **Razorpay account + test-mode keys** — checkout/webhook code is ready; `scripts/setup_razorpay_plans.py` provisions the Razorpay-side Plan objects once keys exist.
4. **Resend account + verified sending domain (SPF/DKIM/DMARC)** — notification worker is live (runs on schedule, no-ops cleanly) but sends nothing until this exists.

---

## 5. Deviations from canon / judgment calls (flagged for the architect, not silently made)

1. **Razorpay `total_count`** (billing-cycle count before a subscription "naturally" ends) is set to 120 for monthly / 10 for annual, approximating "recurring until cancelled" — Razorpay Subscriptions have no literal forever option and the canon doesn't specify a value. Worth architect review once real billing is closer.
2. **Cache-version-bump invalidation deferred, TTL-only for now** (§11.1's own explicit allowance) — no Upstash credentials exist to wire into the crawler's GH Actions environment yet, so there was nothing to wire regardless. 45s TTL fully bounds staleness against the 2-hour crawl cadence.
3. **Digest content is rule-based, not personalized** — a user's dream-company matches if they have any, else a generic recent-opportunities sample. No AI/embeddings, consistent with the Phase-3 boundary, but worth the architect knowing this is deliberately unsophisticated for now.
4. **Company resolution for the aggregator is exact-normalized-name match, not fuzzy** — deliberately, for the same reason `pipeline/dedup.py` defers fuzzy *title* matching to Phase 3 (an unvalidated second fuzzy-matching surface risks the exact false-merge failure mode that dedup.py's own threshold history already paid to learn about). A false split (two Company rows for spelling variants) is the accepted failure mode, consistent with Doc 01 R5.
5. **`postgresql-client-16` pinned in the backup workflow**, not auto-detected — a safe default (works against PG 15/16/17 restore targets) chosen because Debian/Ubuntu's default `postgresql-client` package resolves to 17.x, whose `pg_dump` emits a GUC unknown to older servers (a real bug this session's own drill caught). Worth confirming against the actual Supabase Postgres version.

None of these contradict canon outright — flagging them so the architect can decide whether any should be promoted into the docs themselves.

---

## 6. What's next

Once the four manual prerequisites above exist: run `scripts/setup_razorpay_plans.py` (Razorpay), set the `RESEND_*`/`UPSTASH_*`/`BACKUP_S3_*` secrets (Render env + GH Actions), and re-verify the four partially-blocked acceptance items end-to-end for real. At that point Phase 2's acceptance gate is fully, not partially, satisfied — the architect should re-review before Phase 3 (AI) is issued.
