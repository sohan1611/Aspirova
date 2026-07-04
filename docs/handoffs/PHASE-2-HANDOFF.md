# PHASE 2 HANDOFF — Production-Ready Platform

*From: Chief Architect (Opus) · To: Lead Engineer (Sonnet / Codex) · Status: ACTIVE*
*Prerequisite: read ALL of `docs/` and the Phase-1 handoff/report. Phase 2 = build-plan phases 3 (Accounts, Plans, Payments & Gating) + 4 (Notifications & Reliability), i.e. strategic Phase 2 in [Doc 07](../07-implementation-roadmap.md).*

---

## 0. Phase-1 review verdict (issued with this handoff)

**Phase 1 PASSES review.** It was verified live, not on trust — the crawler completes reliably on GitHub Actions (12m45s, all 12 companies), the deployed stack (Render + Vercel + Supabase) serves real deduplicated data, and the full sign-up→bookmark flow works against production. Architecture conforms to the canon: Render runs only the API (`render.yaml`), the crawler runs only on GitHub Actions, dedup yields one canonical opp per opportunity with provenance and idempotent writes, outbound-link-not-mirror is honored end-to-end, and the `SourceAdapter` seam is clean. The slug-collision bug found post-close was root-caused and fixed with regression tests. **No blocking defects.**

**Five carry-forward items** become Phase-2 work (detailed below): (1) crawler latency headroom, (2) production p95 over target + variable, (3) no rate limiting on a now-public API, (4) no backups of now-real data, (5) test-suite connection flakiness. Two were found *during this review* and are new since the Phase-1 report:

- **P95 is over target and highly variable.** Two independent measurements: 361-388ms (earlier) and, under load, feed p95 750ms / search p95 **2378ms** (this review). The root cause is not cleanly isolated between the cross-region DB hop, Render Starter CPU throttling, and the free Supabase pooler. **Do not migrate Supabase on this evidence alone** (see §4, the Lever-2 ruling).
- **Test-suite connection flakiness.** `tests/test_runner_isolation.py` uses commit-based fixtures against the shared remote dev DB and the suite creates an engine per fixture; under connection pressure a full-suite run can ERROR (not fail) deep in. Passes in isolation; CI was green. This is test infrastructure, not product logic — but it must be hardened before Phase 2 multiplies DB-touching tests (Part 2.8).

---

## 1. Scope

**IN scope (Phase 2):**
- **Payments, plans, gating:** Razorpay (monthly + annual, annual-default checkout), seed the 5 canonical plan rows, `subscriptions`, config-driven gating via `plans.features` + a single `can(user, feature)` helper, `dream_companies` with per-plan limits.
- **Notifications:** notification worker (GitHub Actions cron), daily digest email (Resend), Pro instant dream-company alerts, frequency caps + suppression, deliverability (SPF/DKIM/DMARC).
- **Reliability & scaling:** crawler **set-based bulk-operation refactor (Lever 1)**; **Lever + Ashby adapters + first best-effort aggregator**; **backups** (Supabase + independent nightly `pg_dump`, restore-tested); **rate limiting** (Upstash) on the public API; latency **instrumentation** + read-path **caching**; adapter-failure alerting.

**OUT of scope — explicitly deferred to Phase 3 (do NOT build any of this now):**
- **All AI:** enrichment (summaries/tags), embeddings/`pgvector`, Resume Match, Career Copilot, Reopen Prediction, Weekly *AI* Report generation. The `ai_client` seam is not needed yet.
- The **"Hidden Opportunities" ranking** is Phase 3; in Phase 2, `is_hidden` is only a **rules-based flag** (source tier + cross-source scarcity), gated by plan — no AI.
- Referrals/viral loops, campus B2B, mobile — Phases 4-5. (Keep the `referrals` schema stub from Doc 03, unused.)

---

## 2. Hard sequencing constraints (violating these will hurt)

1. **Lever 1 (crawler bulk ops) MUST land before Lever/Ashby/aggregator adapters.** At 12 companies the crawl already takes ~12m45s (near the 25-min ceiling) because `ingest_normalized_listing` does ~5 serial DB round-trips per listing over the high-latency link. Adding 3-5× the sources on top of that pattern *will* blow the timeout. Fix the round-trip pattern first (§Parts 2.4), then add sources (2.5).
2. **Rate limiting is urgent, not deferrable-within-Phase-2.** The API at `aspirova-api.onrender.com` is *already public and unthrottled* over a $7 Render Starter + free Supabase pooler. A scraper or accidental hammering can exhaust connections or the budget. Do Part 2.1 early.
3. **Payments require real money movement — never auto-charge or auto-create live billing.** Razorpay setup and going-live is the user's action; you scaffold, integrate, and test in Razorpay **test mode** first.

---

## 3. Canonical references
- Pricing + the exact plan seed: [Doc 06 §1 + §HANDOFF](../06-pricing-and-cost-analysis.md)
- Plan/feature matrix (what each tier gets): [Doc 01 §Business Model / §10](../01-product-strategy.md)
- Schema for the new tables: [Doc 03 §4 (users/plans/subscriptions/dream_companies/bookmarks/resume_profiles), §4.3 (notifications), §5 (crawl ops), §8 (retention/backup)](../03-data-architecture.md)
- Notification worker, Upstash, Resend/SES, `can()`: [Doc 02 §3.6, §3.8, §3.9, §HANDOFF](../02-system-architecture.md)
- Crawler adapters, legal/robots, change detection: [Doc 04](../04-crawler-system.md)
- Governance / HARD RULES: [Doc 08 §1, §3](../08-engineering-governance.md)
- Topology & Lever-1/Lever-2: [Topology & Deploy ADR](TOPOLOGY-AND-DEPLOY-DECISION.md)

---

## 4. Architect ruling on the Lever-2 (Singapore consolidation) question

**Ruling: do NOT migrate Supabase to Singapore yet. Instrument first, then decide from isolated data — and try the cheaper mitigation before the expensive one.**

The p95 is over target and variable, but the end-to-end measurement (test-machine → Render-Singapore → Supabase-Mumbai) conflates three possible contributors: the cross-region DB hop (which a migration fixes), Render Starter CPU throttling (which a migration does **not** fix), and free-pooler queuing. Migrating Supabase churns every secret across Render/Vercel/GitHub and is real work — do not spend it on an unisolated signal (Doc 02 §5: scale by *measured* trigger).

**Phase-2 does two things instead, both cheap and both folded into work already in scope:**
1. **Instrument (Part 2.3):** middleware returns `X-Total-Time-Ms` and `X-DB-Time-Ms` response headers (time the DB round-trip inside the handler vs the whole request). This isolates the DB hop. *Then* the migration decision is data-driven: if `X-DB-Time-Ms` p95 is itself over budget → Singapore consolidation is justified; if the DB hop is fast and total time is dominated by compute → the answer is a bigger Render instance or caching, not a DB move.
2. **Cache hot reads (Part 2.1):** feed/search results in Upstash (which Phase 2 adds for rate limiting anyway). A cache hit skips the DB hop entirely, which likely helps real-world p95 *more* than a region migration, sooner and cheaper. Measure p95 again after caching before revisiting migration at all.

---

## 5. Suggested part decomposition (Sonnet refines; Opus reviews between parts)

Ordered to front-load exposure/data-protection and respect the hard sequencing. Each part is independently shippable and testable.

| Part | Deliverable | "Done" check |
|---|---|---|
| **2.1 Rate limiting + read cache** | Upstash Redis; per-IP rate limits on public `/feed`,`/search`,`/opportunity`; per-user limits on auth/bookmark routes; cache feed/search responses with short TTL + invalidation on ingest | A burst of requests is throttled (429); a cached feed serves without a DB query; p95 re-measured and recorded |
| **2.2 Backups** | Enable Supabase backups; independent nightly `pg_dump` → Cloudflare R2 / Backblaze B2 via GH Actions cron; **one documented restore-to-scratch test** | A backup file lands in object storage on schedule; a restore into a throwaway DB is verified once |
| **2.3 Latency instrumentation** | `X-Total-Time-Ms` + `X-DB-Time-Ms` on API responses; a small script to sample production p95 of both | Headers present on live responses; isolated DB-hop p95 recorded in the Phase-2 report for the Lever-2 call |
| **2.4 Lever 1 — crawler bulk ops** | Rewrite the per-listing round-trip pattern in `pipeline/ingest.py`/runner to set-based: one read of existing `raw_listings`+`opportunities` per board → in-memory dedup → bulk insert/update | A 12-company crawl drops well under its current ~12m45s; idempotency + dedup correctness tests still green |
| **2.5 More adapters** | `LeverAdapter` (`api.lever.co/v0/postings/{co}?mode=json`), `AshbyAdapter` (`api.ashbyhq.com/posting-api/job-board/{token}`), first **best-effort aggregator** (robots-respecting, honest UA, link-out-not-mirror, `sources.legal_status` kill-switch). Seed a few verified companies each. **Only after 2.4.** | New sources ingest via the existing `SourceAdapter` seam, core untouched; cross-source dedup collapses the same job from Greenhouse+Lever into one canonical opp with 2 provenance rows |
| **2.6 Plans, payments, gating** | Seed 5 plan rows (paise, §6); `subscriptions`; Razorpay (monthly+annual, **annual default at checkout**, webhooks → subscription state), test-mode first; `plans.features` jsonb + `can(user, feature)` helper; `dream_companies` with per-plan limit enforced via `can()` | Test-mode annual + monthly checkout updates `subscriptions`; a Free user is blocked at 1 dream company, Pro Lite at 5, Pro unlimited — all via `can()`, no scattered `if plan==` |
| **2.7 Notifications** | Notification worker (GH Actions cron); daily digest email (Resend) to opted-in users; Pro instant dream-company alert triggered post-ingest; frequency caps + suppression via `notifications` table; SPF/DKIM/DMARC on the sending domain | A Pro user with a dream company receives a real alert email on a new matching opp; a Free user gets one daily digest, not per-opportunity; caps prevent duplicates |
| **2.8 Test-infra hardening** | Session-scoped shared engine (or a dedicated test schema/DB) so full-suite runs don't exhaust the pooler; make `test_runner_isolation.py` cleanup robust to interruption (unique per-test slugs or rollback pattern) | Full `pytest` run is green and stable across repeated runs under load; no residue left on interruption |

---

## 6. Interface contracts (build to these)

### Plan seed (paise; Doc 06 §1) — data, never hardcoded logic
```
free              | price_paise=0     | billing=NULL
pro_lite_monthly  | 3900              | monthly
pro_lite_annual   | 39900             | annual    # ₹399/yr, saves ₹69 (~15%)
pro_monthly       | 4900              | monthly
pro_annual        | 49900             | annual    # ₹499/yr, saves ₹89 (~15%)
```
Annual is the default-highlighted checkout option, showing the "~15% off / 2 months free" saving.

### `plans.features` (jsonb) — build the full gating matrix now; AI flags exist but stay false until Phase 3
Per Doc 01's tiering. Example shape (values are the source of truth for `can()`):
```
free:      { dream_companies_limit: 1,   instant_alerts: false, weekly_report: false,
             hidden_opps: "limited", unlimited_bookmarks: false, daily_digest: true,
             copilot: false, resume_match: false, prediction: false }
pro_lite:  { dream_companies_limit: 5,   instant_alerts: true,  weekly_report: true,
             hidden_opps: true, unlimited_bookmarks: true, daily_digest: true,
             copilot: false, resume_match: false, prediction: false }
pro:       { dream_companies_limit: null(=unlimited), instant_alerts: true, weekly_report: true,
             hidden_opps: true, unlimited_bookmarks: true, daily_digest: true,
             copilot: true, resume_match: true, prediction: true }
```
The Phase-3 AI flags (`copilot`/`resume_match`/`prediction`) are present-but-false so the gate is built once; the features behind them are NOT built in Phase 2.

### `can(user, feature)` — the single gating seam (Doc 02/08 HARD RULE)
Reads the user's active subscription's `plans.features`; returns the feature value (bool for toggles, int/None for limits). Every gate in the codebase goes through this — no scattered plan checks. Free/unauthenticated users resolve to the `free` feature set.

### Latency headers (Part 2.3)
`X-Total-Time-Ms` (whole request) and `X-DB-Time-Ms` (summed DB round-trip time in the handler), on every API response.

---

## 7. Phase-2 acceptance gate (hand back to Opus when ALL hold)
1. Payments work end-to-end in Razorpay **test mode**, monthly **and** annual, updating `subscriptions`; annual is the default checkout.
2. Gating is data-driven: a Free/Pro-Lite/Pro user hits the correct `dream_companies` limit and `instant_alerts`/`hidden_opps` access — all via `can()`.
3. A Pro user receives a **real** dream-company instant alert email + a Free user receives a daily digest (Resend), with frequency caps working.
4. **≥3 ATS adapters (Greenhouse+Lever+Ashby) + 1 aggregator** ingesting via the seam; cross-source dedup verified.
5. **Lever-1 landed**: full crawl comfortably under the timeout with the new source count.
6. **Backups** running to object storage with **one restore actually tested**.
7. **Rate limiting** live on the public API; **isolated DB-hop p95** measured and recorded (the Lever-2 input).
8. Full test suite green and stable; HARD RULES (§8) hold.

---

## 8. Review gates (Doc 08 §3 + Phase-2 additions)
- [ ] Gating goes through `plans.features` + `can()` — zero scattered `if plan == ...`.
- [ ] Plans/prices are **data** (seeded rows in paise), not code.
- [ ] Razorpay keys + Resend/Upstash/R2 creds via env only; **never** in the client bundle or git. `service_role` stays backend-only.
- [ ] New adapters honor the `SourceAdapter` seam; aggregator respects robots.txt + honest UA + **link-out-not-mirror** + `legal_status` kill-switch.
- [ ] No AI code, no `pgvector`, no enrichment snuck in (Phase 3 boundary).
- [ ] Crawler still runs only on GitHub Actions; Render dyno still runs only the API; the notification worker also runs on cron, not the web dyno.
- [ ] Backups exclude nothing precious; a restore was tested, not assumed.

## 9. Cost/perf budget
- New services: Upstash (free tier), Resend (free 3k/mo → later SES), R2/B2 (cheap/free egress). Razorpay per-transaction only. Target stays **≤ ~$10-15/mo** through Phase 2 (Doc 06).
- Email discipline: one daily digest, instant alerts bounded to Pro + dream companies, frequency caps, suppress inactives (email is the linear-scaling cost, Doc 06).

## 10. Manual prerequisites (the user must create these — flag each when you reach it)
Razorpay account (test-mode keys first), Resend account + verified sending domain (DNS records for SPF/DKIM/DMARC), Upstash Redis database, and a Cloudflare R2 or Backblaze B2 bucket. All have free/cheap tiers. Do not assume any exist; prompt the user at the part that needs it, the same cadence as the Supabase/Render/Vercel setups.

---

## 11. Part 2.1 build addendum — binding rulings (2026-07-05)

*Issued by the Chief Architect after reading the current code (`api/main.py`, `core/config.py`, `api/{feed,search,opportunity,auth,bookmarks}.py`, `api/deps.py`, `crawlers/runner.py`). These pin the decisions the §5 table row left open so Part 2.1 is buildable without a review bounce. They are **Binding** (Decision-log row of the same date). Sonnet may refine numbers; the **mechanisms** below are not optional.*

**Readiness verdict:** the seams are clean and nothing structural blocks the part — the work is decisions, not missing infrastructure. Build to these.

### 11.1 Cache invalidation is cross-process — design for it explicitly
Ingest runs **only** on GitHub Actions (`runner.py` docstring; Doc 02 §3.3 hard rule), so the web dyno never learns when data changed. "Invalidate on ingest" therefore cannot be a call inside a request handler.
- **Ruling:** a short TTL is the mandatory correctness backstop; a **cache-version bump** is the best-effort fast-invalidation on top. Cache keys are prefixed with a version integer read from Upstash (e.g. `feed:v{ver}:{normalized_qs}`, `search:v{ver}:{q,page,limit}`, `opp:v{ver}:{slug}`). The crawler does **one** `INCR aspirova:cache:ver` at the end of any run that changed data (`new_opps > 0` or the board fingerprint moved). Old keys become unreachable and expire via TTL. **O(1); never SCAN/DEL** over the keyspace.
- **If** wiring Upstash creds into the crawler (GH Actions secrets) is judged out of 2.1 scope, **ship TTL-only** and defer the version-bump — with a 2-hour crawl cadence, sub-minute staleness is immaterial and TTL fully bounds correctness. Do not block 2.1 on it.
- **Manual prereq (flag it):** the version-bump path needs `UPSTASH_REDIS_REST_URL` + `UPSTASH_REDIS_REST_TOKEN` as GitHub Actions secrets, not just Render env.

### 11.2 Fail-open, always
If Upstash is unreachable on the **rate-limit** path, **allow** the request and emit a log line + an alert counter — do not 503. Availability beats protection for a public read API on a $7 dyno; the DB's `statement_timeout` (Doc: `core/db.py`) + pooler cap are the backstop. On the **cache** path, a backend error falls through to the DB — a cache outage must never turn a read into a 500.

### 11.3 Client identity behind Render's proxy
Per-IP limits key on the **first hop of `X-Forwarded-For`**, never `request.client.host` (which is Render's proxy — that would collapse every user into one bucket and throttle the whole world at once). Trust XFF **only** because we know we sit behind Render's proxy; document that trust boundary in the code. Per-user limits key on `user.id` from `get_current_user`; unauthenticated requests fall back to the IP key.

### 11.4 Limits and TTLs are configuration, not code
Env-driven, same ethos as "plans are data." Initial values (Sonnet may tune, but they live in config from day one):

| Surface | Initial limit |
|---|---|
| `/feed`, `/search` (per IP) | 60 req / min |
| `/opportunity/{slug}` (per IP) | 120 req / min |
| bookmark writes `POST`/`DELETE` (per user) | 30 req / min |
| read-cache TTL | 45 s |

Use the **Upstash Python SDK** (`upstash-redis` + `upstash-ratelimit`, REST-based — no persistent TCP from Render) with an atomic fixed/sliding window. Do **not** hand-roll `INCR`/`EXPIRE` (race-prone).

### 11.5 Middleware ordering + response contract
- The cache check MUST run **before** the `get_db` dependency opens a session, so a hit does **zero** DB work — the §5 "serves without a DB query" check depends on this. Implement the read cache as middleware or a dependency ordered ahead of the session, not inside the handler after `get_db` already ran.
- Rate-limit + cache layers sit **inside** CORS, so a `429` or a cached response still carries CORS headers (otherwise the browser masks it).
- `429` responses carry `Retry-After` and a JSON body.
- Design so Part 2.3's `X-Total-Time-Ms` / `X-DB-Time-Ms` middleware layers cleanly on top; a cache hit still reports timing (with `X-DB-Time-Ms ≈ 0`).

### 11.6 Pre-flight before per-user limits
`api/auth.py` and `api/bookmarks.py` still carry stale `BLOCKED ON CREDENTIALS — untested` docstrings, though the Phase-1 review reports the sign-up→bookmark flow verified live. Before layering per-user limits on `get_current_user`, **confirm auth works end-to-end** against the real Supabase creds now in `.env`, and clear the stale docstrings.

### 11.7 Updated "Done" check for Part 2.1 (supersedes the §5 table row)
1. A burst above the window returns `429` with `Retry-After`.
2. A repeated `/feed` (and `/search`) request serves from cache with **zero** DB round-trips — proven via `X-DB-Time-Ms ≈ 0` (Part 2.3) or a query-counter assertion in a test.
3. With Upstash forced unreachable, the API still serves reads (**fail-open**, covered by a test).
4. Per-IP keying is correct behind a simulated `X-Forwarded-For`: two client IPs get two buckets; a single proxy IP does **not** collapse all users into one.
5. p95 is re-measured **after** caching and recorded — the Lever-2 input (§4).

---

## Definition of done for Phase 2
Free/Pro-Lite/Pro are live with data-driven gating and working Razorpay (test-mode) monthly+annual checkout; dream-company alerts and a daily digest actually send; the crawler ingests from ≥3 ATS + 1 aggregator on a bulk-op pipeline that finishes well under the timeout; the now-public API is rate-limited and cached; real data is backed up and a restore is proven; the isolated DB-hop latency number is in hand to settle Lever 2 — and every §8 gate holds. Then write the Phase-2 Report and stop; the user pings Opus for review and the Phase-3 (AI) handoff.
