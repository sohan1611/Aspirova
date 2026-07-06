# Aspirova — Architecture & Strategy Canon

**Tagline:** Every opportunity. One place.
**What it is:** An AI-powered Career Intelligence Platform that *discovers* student opportunities automatically from public sources. It is **not** a job board — companies never post here.

> **Authority model.** This `docs/` folder is the source of truth. The Chief Architect (Claude Opus) owns it. The implementation agent (currently Claude Sonnet; possibly OpenAI Codex later) MUST conform to these documents. If reality forces a deviation, the engineer raises it; the architect amends the doc. Code never silently diverges from the canon.

---

## How to read this

| # | Document | Owner question it answers |
|---|----------|---------------------------|
| 01 | [Product Strategy](01-product-strategy.md) | Why will this win, and who pays? |
| 02 | [System Architecture](02-system-architecture.md) | What are the moving parts and why? |
| 03 | [Data Architecture](03-data-architecture.md) | How is data modeled, indexed, grown? |
| 04 | [Crawler System](04-crawler-system.md) | How do we discover opportunities cheaply & legally? |
| 05 | [AI Systems](05-ai-systems.md) | How do AI features work without bankrupting us? |
| 06 | [Pricing & Cost Analysis](06-pricing-and-cost-analysis.md) | Do the unit economics actually work? |
| 07 | [Implementation Roadmap](07-implementation-roadmap.md) | What gets built, in what order? |
| 08 | [Engineering Governance](08-engineering-governance.md) | What rules must every coding agent follow? |

Each document ends with a **HANDOFF TO ENGINEERING** block — the only part the coding agent is required to act on directly.

---

## The five things you must internalize before reading further

These are the architect's brutally honest top-of-mind conclusions. The rest of the canon defends them.

1. **Stop thinking "scrape the aggregators." Think "go to the source."**
   Internshala, Unstop, Wellfound, and LinkedIn all forbid scraping in their ToS and actively block bots. Building the company on scraping *other aggregators* is legally fragile and technically a treadmill. The durable moat is crawling **company ATS endpoints directly** — Greenhouse, Lever, Ashby, and Workday expose structured, semi-public JSON board endpoints per company. That is where 60–70% of real, fresh, deduplicated opportunity data should come from, at near-zero cost and near-zero legal risk. Aggregators become a *secondary, best-effort* tier, not the foundation. **This single decision reshapes the entire crawler architecture (Doc 04).**

2. **Pricing: Pro Lite ₹39 / Pro ₹49, with annual plans ₹399 / ₹499 (~15% off).**
   The ₹10 (~25%) monthly gap means a rational student takes Pro for the AI features — sound decoy psychology, with Pro Lite as the anchor. **Annual plans are the default offer** (₹399 Pro Lite saves ₹69; ₹499 Pro saves ₹89 vs 12× monthly — both ~15%, "2 months effectively free"): they cut transaction count ~12×, slash involuntary churn, and front-load cash. The higher prices lift blended ARPPU to ₹47.5/mo and move break-even down to **~1,000 users**. Doc 06 models this.

3. **"Crawl once, store centrally, serve many" is correct — and it must extend to AI.**
   The expensive trap is *per-user* AI. The architecture enriches each **canonical** opportunity exactly once (summary, tags, embedding) *after* deduplication, then every user reads the shared result for free. Resume Match is **embedding cosine similarity (no LLM call per match)**, not an LLM grading each resume against each job. Only the Career Copilot is intrinsically per-user — so it is gated to Pro, rate-limited, model-cheap, and cached. Doc 05 enforces this.

4. **Postgres is your search engine, your vector store, and your queue. Add nothing else yet.**
   `tsvector` (full-text) + `pg_trgm` (fuzzy) + `pgvector` (semantic/resume match) + `SELECT … FOR UPDATE SKIP LOCKED` (job queue) means one managed Postgres (Supabase free tier) does the work people reach for Elasticsearch, Pinecone, and RabbitMQ to do. At Aspirova's scale, those would be cost and operational liabilities, not assets. Doc 02/03 defend this.

5. **Be honest about the money: at ₹39/₹49/month and ₹95/$, you break even around ~1,000 users.**
   This is currently a **project, not a live product** — profit isn't the immediate goal, a correct/sustainable build is. But the model is sound: running lean, out-of-pocket stays under ~₹950/mo at every stage (well inside a ₹2,000/mo budget), break-even is ~1,000 users at a sober 3% conversion, and it's clearly profitable by ~1,500. Accelerators stack on top: (a) better Pro conversion, (b) **B2B campus licenses** (one ₹30k/yr deal ≈ 53 Pro subs), (c) annual uptake, (d) ethical sponsored listings + affiliates. Doc 06 quantifies all of it.

---

## Canonical technology decisions (the short version)

The full rationale and rejected alternatives live in the relevant docs. This is the binding summary.

| Layer | Decision | Why (one line) | Doc |
|-------|----------|----------------|-----|
| Frontend | **Next.js on Vercel (free tier)** | Best free hosting + SSR/SEO for opportunity pages | 02 |
| Backend API | **FastAPI (Python) on Render** | AI/crawl/data work is cleaner in Python; clean REST boundary | 02 |
| Database | **Postgres via Supabase** | Relational + FTS + vector + queue in one managed box | 02/03 |
| Search | **Postgres `tsvector` + `pg_trgm`** | Free, sufficient to ~1M opps; no Elasticsearch | 03 |
| Vector / Resume Match | **`pgvector` (HNSW)** | Shared embeddings; match = cosine, no per-user LLM | 03/05 |
| Crawlers | **Python workers on GitHub Actions cron** | Free scheduled compute; keeps Render server light | 04 |
| Primary data source | **ATS JSON endpoints (Greenhouse/Lever/Ashby)** | Structured, low-risk, near-free; the real moat | 04 |
| Browser automation | **Playwright — only for JS-heavy sites, as jobs** | RAM-hungry; never always-on, never the default | 04 |
| Queue / scheduling | **Postgres `SKIP LOCKED` + GH Actions matrix** | No Kafka/RabbitMQ; dead simple | 02/04 |
| Cache / rate limit | **Upstash Redis (free tier)** | Serverless, pay-per-use, rate limiting for AI/API | 02 |
| Email | **Resend (free → Pro), AWS SES at scale** | Cheapest path; SES is ~$0.10 / 1k emails | 02/06 |
| AI enrichment | **Cheapest viable model (Haiku-class), once per canonical opp** | Shared output, never per-user | 05 |
| Payments | **Razorpay; annual prepay preferred** | India-native; annual cuts txn cost + churn | 06 |
| Object storage / backups | **Cloudflare R2 or Backblaze B2** | Cheap/no-egress nightly `pg_dump` | 03 |

---

## Decision log (append-only)

| Date | Decision | Status |
|------|----------|--------|
| 2026-06-23 | Adopt ATS-first crawling; aggregators demoted to best-effort tier | **Binding** |
| 2026-06-23 | Postgres-only data plane (search + vector + queue) for Phase 1–3 | **Binding** |
| 2026-06-23 | Resume Match = embedding cosine, not per-user LLM | **Binding** |
| 2026-06-23 | Crawlers run on GitHub Actions, not the Render web dyno | **Binding** |
| 2026-06-24 | 5-phase roadmap with enforced phase gates; Phase-1 MVP is ATS-first, no payments/AI (Doc 07) | **Binding** |
| 2026-06-24 | Engineering governance adopted; §3 HARD RULES are the merge gate; canon is law, agents are interchangeable (Doc 08) | **Binding** |
| 2026-06-24 | `ai_client`, `can(user, feature)`, and `SourceAdapter` are mandated seams (most HARD RULES are satisfied by routing through them) | **Binding** |
| 2026-06-25 | **Pricing (SUPERSEDES earlier ₹25/₹30):** Pro Lite ₹39/mo · ₹399/yr; Pro ₹49/mo · ₹499/yr. Annual = ~15% off (Pro Lite saves ₹69, Pro saves ₹89). Annual is the default checkout option (Doc 06) | **Binding** |
| 2026-06-25 | FX assumption corrected to ₹95 = $1 across the canon; blended ARPPU ₹47.5/mo; break-even ~1,000 users at 3% conversion (Doc 06) | **Binding** |
| 2026-06-25 | Aspirova is currently a **project (build), not a live product**; profit is a reference model, not the immediate goal | **Binding** |
| 2026-06-30 | Deploy read path now as a **minimal, reversible measurement** — Render **Singapore** ($7 Starter) + Vercel Hobby, Supabase stays Mumbai; purpose = real production p95 + portfolio artifact, NOT "Phase 1 shipped" ([Topology & Deploy ADR](handoffs/TOPOLOGY-AND-DEPLOY-DECISION.md)) | **Binding** |
| 2026-06-30 | Crawler **set-based bulk-operation** refactor required **before Phase 2 scales source count** (root cause of slow GH-Actions→Mumbai crawls is round-trip count × link latency, not commit frequency); non-blocking for the deploy | **Binding** |
| 2026-06-30 | Render has **no Mumbai region** (Singapore is closest, ~120ms to Mumbai DB); strategic direction is **consolidate compute + DB in Singapore**, but gated on the measured p95, not assumed | **Proposed — measure first** |
| 2026-06-30 | **Phase 1 PASSES architect review** (crawler + deployment + auth flow all verified live; no blocking defects). Build phases 1-2 done; Phase 2 (build phases 3-4) issued via [PHASE-2-HANDOFF.md](handoffs/PHASE-2-HANDOFF.md) | **Binding** |
| 2026-06-30 | **Lever-2 ruling:** do NOT migrate Supabase to Singapore yet. Production p95 is over target + variable but not isolated to the DB hop. Phase 2 adds server-side `X-DB-Time-Ms` instrumentation + Upstash read-caching first; migrate only if the *isolated* DB-hop p95 is over budget | **Binding** |
| 2026-06-30 | **Lever-1 (crawler set-based bulk ops) is a hard precondition** inside Phase 2 — must land before Lever/Ashby/aggregator adapters, else the ~12m45s crawl blows the 25-min timeout at 3-5× the source count | **Binding** |
| 2026-06-30 | Rate limiting on the public API is **urgent Phase-2 work**, not deferrable — the API is already public and unthrottled over a $7 Render + free pooler | **Binding** |
| 2026-07-05 | **Part 2.1 rulings** (see [PHASE-2-HANDOFF §11](handoffs/PHASE-2-HANDOFF.md)): rate limiter **fails open**; per-IP keys on `X-Forwarded-For` (not the Render proxy IP); cache invalidation = short TTL backstop **+** crawler-driven version-bump (never SCAN/DEL), TTL-only acceptable if crawler→Upstash is deferred; limits/TTLs are **config, not code**; cache check runs before `get_db`; rate-limit/cache middleware sit inside CORS | **Binding** |
| 2026-07-05 | **Phase 2 (build phases 3-4) engineering complete**, merged to `master`, deployed live, CI green. 4 of 8 parts' acceptance criteria partially blocked on manual prerequisites (Upstash/R2-B2/Razorpay/Resend accounts — none created yet); every integration fails open/closed safely without them. Full account: [PHASE-2-REPORT.md](handoffs/PHASE-2-REPORT.md) | **Binding** |
| 2026-07-05 | **Lever-2 isolated DB-hop measurement** (live production, n=30/endpoint): X-DB-Time-Ms p95 127–202ms; X-Total-Time-Ms p95 192–293ms — already under the 300ms target *including* the DB hop, before Upstash caching is even live. Leans toward Lever-2 not being urgent, but the migrate/no-migrate call is the architect's per the standing role model. Full data: [PART-2.3-LEVER-2-MEASUREMENT.md](handoffs/PART-2.3-LEVER-2-MEASUREMENT.md) | **Measured — architect to rule** |
| 2026-07-05 | **Phase 2 closeout, Resend + Upstash manual prerequisites verified live**: Resend sending domain (`aspirova.org`) fully verified, real digest email delivered via the actual pipeline code; Upstash rate limiting fires exactly at the configured 60/min threshold (60×200 then 429s in a live burst test) and read-cache hits confirmed (`X-DB-Time-Ms` 0.00ms). Cached p95 re-measured at 7.9–8.1ms across all three endpoints (down from 192–293ms uncached) — reaffirms the Lever-2 no-migrate reading with an even wider margin. R2/B2 and Razorpay remain open (Razorpay explicitly deferred to last by user decision). Full detail: [PHASE-2-CLOSEOUT.md](handoffs/PHASE-2-CLOSEOUT.md) | **Verified** |
| 2026-07-06 | **Cloudflare R2 manual prerequisite verified live, real backup/restore bugs found and fixed (two of them)**: (1) `postgresql-client-16` in `backup.yml` was a wrong assumption — production Supabase actually runs **Postgres 17.6**, and `pg_dump` cannot dump from a server newer than itself; fixed by pinning `postgresql-client-17`. (2) even after that fix, the real GitHub Actions run still resolved `pg_dump` to 16.14 — `ubuntu-latest`'s runner image ships a pg_dump 16 binary already on `PATH` that shadows the correctly-installed v17 package (which installs to `/usr/lib/postgresql/17/bin/`, not `/usr/bin/`); fixed by prepending the versioned bin dir to `$GITHUB_PATH`. Both fixes verified end-to-end against real production with explicit user authorization at each step: real local Docker restore drill (all 17 tables, exact row-count match) plus a real `workflow_dispatch` run of the actual "Nightly Backup" GitHub Actions workflow succeeding unattended. **All three non-payments manual prerequisites (Resend, Upstash, R2) are now closed** — only Razorpay remains, deferred to last by standing user decision. Full detail: [PART-2.2-RESTORE-DRILL.md](handoffs/PART-2.2-RESTORE-DRILL.md) addenda | **Verified** |
| 2026-07-06 | **Roadmap re-sequenced: Premium UI (new Phase 2.5) → AI (Phase 3) → Razorpay wiring.** Razorpay deferred by founder decision; architect concurs and reorders per Doc 07's own law ("don't monetize/enhance a weak product"). Payments stay **fail-closed and honest** (pricing = waitlist, never a checkout that errors) until wired after AI, when the paywall will gate real Pro value on a premium-feeling product. Does not void any Binding row — inserts a phase and moves the *completion* of Phase 2's payment gate later. The webhook out-of-order/replay fix (flagged in the Phase-2 review) folds in with the eventual Razorpay wiring | **Binding** |
| 2026-07-06 | **Phase 2.5 (Premium UI & Experience) issued** to engineering: design-system-first (Tailwind v4 `@theme` tokens → owned primitives on Radix → redesigned feed/detail/auth/shell + honest pricing-waitlist page), 8 parts. **Direction = Professional/Trust, blue-led** (founder's call), **system-adaptive theme + manual toggle**; architect caveat pinned — execute it *premium* (typographic rhythm, spacing system, micro-interactions) to avoid the generic-corporate trap. SSR/SEO growth surface stays server-rendered; no AI, no functional payments. Full brief: [PHASE-2.5-HANDOFF.md](handoffs/PHASE-2.5-HANDOFF.md) | **Binding** |
| 2026-07-06 | **Phase 2.5 engineering complete**, all 8 parts merged to `master`, full backend suite green (133/133), production build clean. All 5 gate conditions met: design system consumed everywhere, feed/detail/auth/shell/pricing redesigned in both themes, SSR/SEO intact (`/` and `/opportunity/[slug]` still dynamic), **Lighthouse accessibility 100 on both feed and detail** (target ≥95), pricing page is a real waitlist with zero functional-checkout risk. Six real defects found and fixed via live verification (not code review alone): an unapplied font, a token-naming collision, a route-scoped loading-UI leak, a doubled page title, a self-contradicting dialog title, and **two real WCAG AA contrast failures** (muted-foreground on muted at 4.34:1, white-on-destructive at 3.76:1 — both were unmodified shadcn-preset defaults, now fixed and re-verified at 6.9-7.6:1 and 4.83:1). Full report: [PHASE-2.5-REPORT.md](handoffs/PHASE-2.5-REPORT.md). **Phase 3 (AI) can now be issued** per the gate | **Binding** |

> Engineers: do not contradict a **Binding** row without an architect-approved amendment.
