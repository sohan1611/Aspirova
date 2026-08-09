# 02 — System Architecture

*Author: Chief Architect. Every decision below includes its rationale and the rejected alternative. Engineers must not deviate without an amendment.*

---

## 1. Architectural principles (the constitution)

1. **Crawl once, store centrally, serve many.** No work is ever repeated per-user that can be done once and shared. This applies to crawling, normalization, enrichment, and AI output.
2. **Separate the *write path* (ingestion) from the *read path* (serving).** Crawlers and enrichment are batch, asynchronous, and can be slow/heavy. User-facing reads must be fast and cheap. They share a database but never share a request lifecycle.
3. **Keep the always-on footprint tiny; push heavy work to free scheduled compute.** The Render web server must stay light (API + serving). All crawling/enrichment runs on GitHub Actions cron (free). This is the core cost lever.
4. **One database does as many jobs as it safely can.** Postgres is relational store + full-text search + vector store + job queue until scale *proves* we need to split. Adding infrastructure is a cost and a liability; earn it.
5. **Everything is an adapter.** Each source is a pluggable adapter behind one interface. Adding a source = adding an adapter, never touching the core.
6. **Config over code for business rules.** Plans, feature gates, crawl tiers, notification rules live in config/data, not scattered conditionals.
7. **Fail soft, observe everything.** A broken source adapter degrades that source only; the platform stays up. Every crawl run, enrichment, and notification is logged and alertable.

---

## 2. The big picture (text architecture diagram)

```
                         ┌────────────────────────────────────────────────┐
                         │                  WRITE PATH                     │
                         │            (batch, async, free compute)         │
                         │                                                 │
  ┌───────────┐  cron    │   ┌─────────────┐    ┌──────────────────┐       │
  │  GitHub   │─────────►│   │  Crawlers   │    │   Normalizer     │       │
  │  Actions  │  (Tier   │   │ (adapters)  │───►│  (clean/extract) │       │
  │  (cron +  │  1/2/3)  │   └─────┬───────┘    └────────┬─────────┘       │
  │  matrix)  │          │         │ raw_listings        │ normalized      │
  └───────────┘          │         ▼                     ▼                 │
                         │   ┌─────────────┐    ┌──────────────────┐       │
                         │   │ Dedup       │◄───┤  Canonicalizer   │       │
                         │   │ Engine      │    │ (merge → canon)  │       │
                         │   └─────┬───────┘    └──────────────────┘       │
                         │         │ canonical opportunity                 │
                         │         ▼                                       │
                         │   ┌─────────────┐  enrich once  ┌────────────┐  │
                         │   │ AI Enrich   │──────────────►│  Embed +   │  │
                         │   │ (summary,   │               │  tag store │  │
                         │   │  tags)      │               │ (pgvector) │  │
                         │   └─────────────┘               └────────────┘  │
                         └───────────────────────┬────────────────────────┘
                                                 │ writes
                                                 ▼
                    ┌───────────────────────────────────────────────────┐
                    │            POSTGRES  (Supabase managed)            │
                    │  relational • tsvector FTS • pg_trgm • pgvector    │
                    │  • job queue (SKIP LOCKED) • events (partitioned)  │
                    └───────────────────────────────────────────────────┘
                                                 ▲ reads
                                                 │
                         ┌───────────────────────┴────────────────────────┐
                         │                  READ PATH                      │
                         │             (fast, cheap, always-on)            │
                         │                                                 │
   ┌──────────┐          │   ┌──────────────┐        ┌──────────────────┐  │
   │ Browser/ │  HTTPS   │   │  FastAPI     │        │ Notification     │  │
   │ Next.js  │◄────────►│   │  (Render)    │◄──────►│ Worker (cron)    │──┼──► Resend/SES
   │ (Vercel) │   REST   │   │  - search    │        │ - digest         │  │
   └──────────┘          │   │  - feed      │        │ - instant alerts │  │
        ▲                │   │  - copilot   │        └──────────────────┘  │
        │ SSR/SEO        │   │  - match     │                              │
        │ pages          │   └──────┬───────┘   ┌──────────────┐           │
        │                │          └──────────►│ Upstash Redis│ cache +   │
        │                │                      │ (free tier)  │ ratelimit │
        └────────────────┘                      └──────────────┘           │
                         └─────────────────────────────────────────────────┘

   External AI: Anthropic API (Haiku-class for enrichment/copilot; embeddings provider)
   Payments: Razorpay (webhooks → FastAPI)   Auth: Supabase Auth or Clerk free tier
```

---

## 3. Component-by-component

### 3.1 Frontend — Next.js on Vercel
- **Decision:** Next.js (App Router), hosted on **Vercel free (Hobby) tier**.
- **Why:** (1) Server-side rendering gives every opportunity page an SEO-indexable URL — a core growth surface (Doc 01). (2) Vercel's free tier is generous and purpose-built for Next.js — *zero* infra cost for the frontend. (3) Edge caching of public pages = fast + cheap.
- **Rejected:** SPA (React/Vite) — loses SSR/SEO, the whole organic-growth engine. Hosting frontend on Render — wastes the paid dyno on static serving Vercel does free.
- **Note:** Public opportunity pages are statically generated / ISR-cached; authenticated dashboard is client-rendered against the API.

**Amendment (2026-08-09) — "zero infra cost" was wrong at this page count.** The claim above
held when the catalogue was small. At ~20,400 indexed opportunities it is false, and the free
tier was exceeded on three meters at once: ISR Writes 434K/200K, Fluid Active CPU 6h15m/4h,
Fast Origin Transfer 9.82GB/10GB.

- **The governing relationship is `renders/day ≈ cacheable paths ÷ revalidate window`.** Every
  ISR regeneration is a *full server render*, so one regeneration bills three meters at once:
  Fluid CPU (the render), an ISR Write (storing it), and Fast Origin Transfer (shipping it to
  the edge). They are not three problems; they are one event counted three ways.
- **ISR does not reduce render count — it only moves renders into the background.** Registering
  routes for ISR changed *where* work happened and left the meters untouched. Only widening the
  window (fewer regenerations per path) and cutting the path count actually moved them.
- **The health metric is the ISR reads:writes ratio.** A cache that works is read far more than
  it is written. At the point of failure this project was inverted at roughly **3:1 writes to
  reads** (434K vs 145K) — numerical proof the cache was being discarded before it could pay for
  itself. Watch that ratio, not the absolute numbers.
- **Deploy frequency is itself a cost driver.** Every production deployment invalidates the
  entire ISR cache, so each deploy costs approximately one full regeneration wave across every
  path a crawler subsequently visits. Three deploys inside 56 minutes produced the worst day on
  record (43m CPU, 130K writes) — while shipping cost *fixes*. **Batch frontend releases; do not
  ship them one at a time.** Corollary: a day containing a deploy cannot be used to measure the
  effect of a caching change.
- **Crawl surface is the root variable.** The sitemap is the dial that sets it
  (`SITEMAP_OPPORTUNITY_LIMIT`), but trimming it only changes what a crawler *discovers* —
  already-indexed URLs keep being crawled for weeks, so it is a slow lever, not an emergency one.
- **The durable fix is on-demand revalidation, not a longer timer.** Pages are invalidated when
  content actually changes (`content_hash` differing in `ingest_one`), never on a routine
  `last_seen_at` touch. Time-based revalidation remains only as a backstop. This decouples
  freshness from cost: without it, freshness can only be bought with renders.

### 3.2 Backend API — FastAPI on Render
- **Decision:** **FastAPI (Python)** on the existing **Render $7 instance**.
- **Why:** The intelligence of this product — crawling, parsing, dedup, embeddings, AI orchestration — is materially cleaner and better-supported in Python. A single Python codebase spans API + crawlers + AI, so the coding agent context-switches less. REST/JSON boundary to the Next.js frontend is clean and language-agnostic.
- **Rejected & the honest tradeoff:** A single-language TypeScript monorepo (Next.js full-stack + TS crawlers) would remove the two-language overhead — a real benefit for a solo founder. **It is a legitimate alternative.** We choose Python because the data/AI/crawl core is the heart of the product and Python's ecosystem (parsing, embeddings, scientific libs, Playwright-Python) reduces *that* risk more than the two-language tax adds. **This is a binding decision; if the founder strongly prefers all-TypeScript, raise it before Phase 1 — switching later is expensive.**
- **Render stays light:** the web dyno only serves API + SSR data. It must **never** run Playwright or heavy crawl/enrich loops (those are GH Actions). 0.5 CPU / 512MB is fine for a JSON API at this scale; it is *not* fine for headless Chromium.

### 3.3 Crawlers — Python workers on GitHub Actions cron
- **Decision:** Crawl/normalize/dedup/enrich pipeline runs as scheduled **GitHub Actions** workflows (cron + job matrix for parallel sources), writing to Supabase.
- **Why:** GitHub Actions gives **free scheduled compute** (generous monthly minutes for the relevant account tier), perfectly suited to "run every 1–6–24h, do work, exit." It keeps the heavy, bursty, RAM-hungry work entirely off the paid Render dyno. Matrix builds parallelize sources for free.
- **Rejected:** Always-on crawler service on Render (would need a bigger, costlier instance and wastes money idling between crawls). Celery+Redis worker fleet (operational overhead unjustified at this scale).
- **Detail in Doc 04.** Failure recovery: each source run is independent; a failed adapter logs + alerts but doesn't fail the batch.

### 3.4 Database — Postgres via Supabase
- **Decision:** Single **Postgres** (Supabase), with `pg_trgm`, `tsvector`, `pgvector` extensions.
- **Why:** One managed database is the store, the search engine, the vector index, and the job queue. Supabase free tier (Postgres + auth + 500MB) gets us to thousands of users at $0; Pro ($25/mo) scales well past that. Managed = no DBA work for a solo founder.
- **Rejected:** Self-hosted Postgres on Render (ops burden, backups, no free tier benefit). Separate Elasticsearch/Pinecone/RabbitMQ (each is cost + ops we have not earned). See Doc 03 for why Postgres FTS/vector is sufficient.

### 3.5 Search — Postgres FTS + trigram
- **Decision:** `tsvector` GIN index for keyword search; `pg_trgm` for fuzzy/typo-tolerant matching; `pgvector` for semantic search.
- **Why:** Free, in-database (no network hop, no sync), and comfortably handles hundreds of thousands to ~1M opportunities with proper indexing. Semantic + keyword can be combined (hybrid search) without leaving Postgres.
- **Earn the upgrade:** Only consider Meilisearch/Typesense/Elasticsearch when query latency at real data volume *measurably* fails SLOs. Documented trigger, not a default.

### 3.6 Notification system — worker + Resend/SES
- **Decision:** A scheduled **notification worker** (GH Actions cron for digests; near-real-time path for Pro instant alerts triggered post-ingest). Sends via **Resend** early (free tier, great DX, deliverability help), **AWS SES** at scale (~$0.10/1k).
- **Why:** Email is the dominant *variable* cost at scale (Doc 06), so the design is batch-first: one daily digest email per free user (not per-opportunity), instant alerts bounded to Pro + dream companies only. Templating + suppression list + SPF/DKIM/DMARC from day one for deliverability.
- **Rejected:** Sending per-opportunity emails (cost + fatigue). Twilio SMS/WhatsApp at launch (expensive in India; revisit as a premium add-on later).

### 3.7 AI systems — external API, shared outputs
- **Decision:** Anthropic API; **cheapest viable model (Haiku-class)** for enrichment + Copilot; an embeddings provider for vectors. All enrichment is **per-canonical-opportunity, once**, stored and reused. Detail in Doc 05.
- **Why:** Per-user AI is the budget killer. Shared enrichment makes AI a fixed-ish cost proportional to *new unique opportunities/day*, not users. Copilot (the one unavoidable per-user cost) is Pro-gated, rate-limited, and cached.

### 3.8 Cache / rate limiting — Upstash Redis
- **Decision:** **Upstash Redis** (serverless, free tier, pay-per-request).
- **Why:** Rate-limit AI/Copilot and API endpoints, cache hot feed/search results and computed match scores. Serverless pricing means $0 when idle — perfect for a cost-sensitive startup. No always-on Redis box to pay for.

### 3.9 Auth & Payments
- **Auth:** Supabase Auth (bundled, free) or Clerk free tier. Decision: **Supabase Auth** to keep one vendor and reduce moving parts.
- **Payments:** **Razorpay** (India-native, UPI + cards + UPI-autopay for subscriptions). Webhooks → FastAPI → update `subscriptions`. Annual-prepay-first (Doc 06).

### 3.10 Scheduler — GitHub Actions cron (+ Render cron as fallback)
- **Decision:** GH Actions `schedule:` triggers per crawl tier; optionally Render Cron Jobs for anything that must live next to the DB.
- **Why:** Free, declarative, version-controlled schedules. Tiered crons map 1:1 to crawl tiers (Doc 04).

### 3.11 Analytics
- **Decision:** First-party event table in Postgres (Doc 03) + a free product-analytics tool (PostHog free / Plausible) for funnels. No expensive analytics stack.
- **Why:** Own your funnel + viral-loop metrics (`k`, conversion, churn) cheaply; the event table doubles as input to the prediction/personalization features.

---

## 4. Request lifecycles (so the engineer builds the right seams)

**Read — user opens feed:**
`Next.js → FastAPI /feed?filters → (Redis cache hit? return) → Postgres query (FTS + filters, indexed) → cache → return`. Target p95 < 300ms. No AI call on the hot path.

**Read — Resume Match:**
`User uploads resume (once) → embed once → store vector → match = pgvector cosine top-K against opportunity embeddings → cache per (resume_version) → return`. **No LLM call per match.** Re-runs only when resume changes or new opps arrive.

**Read — Copilot (Pro only):**
`Rate-limit check (Redis) → context-assemble (user profile + relevant opps via vector search) → cheap LLM call → cache common Q&A → return`. Bounded, gated, observable.

**Write — ingestion:**
`GH Actions cron → adapter fetch → raw_listings insert → normalize → canonicalize+dedup → if new canonical: enrich once (summary/tags/embedding) → index → trigger instant-alert evaluation for matching dream-company subscribers`.

---

## 5. Scalability posture (what changes, and when)

| Trigger (measured, not guessed) | Action |
|--------------------------------|--------|
| Render API CPU/RAM sustained high | Vertical bump Render; move SSR data aggregation to edge caching |
| Postgres FTS p95 misses SLO at real volume | Add Meilisearch/Typesense as a read replica index |
| Email volume cost dominates | Move Resend → SES; tighten digest batching/frequency |
| Crawl minutes exceed GH Actions budget | Self-host a single small crawl box, or stagger schedules |
| pgvector recall/latency degrades | Tune HNSW params; partition embeddings by recency |
| Postgres DB > Supabase tier | Supabase Pro; later, read replicas for read path |

**Principle: scale by *measurement and trigger*, never by anticipation.** Every premature scaling decision is money a student startup can't afford.

---

## 6. What we explicitly are NOT building (anti-scope)

- ❌ Kubernetes / microservices — a modular monolith (FastAPI) + scheduled workers is correct at this scale.
- ❌ Kafka / RabbitMQ — Postgres `SKIP LOCKED` is the queue.
- ❌ Elasticsearch / Pinecone — Postgres FTS + pgvector.
- ❌ Always-on crawler fleet — GH Actions cron.
- ❌ A mobile app in Phase 1 — responsive PWA first (Doc 07).

---

## HANDOFF TO ENGINEERING

**Build order & seams:**
1. **Repo shape:** one Python backend repo (`api/`, `crawlers/`, `core/` shared models, `enrich/`, `notify/`) + one Next.js frontend repo (or a monorepo with both). Shared DB schema lives in `core/`. Crawlers import `core` models but are invoked by GH Actions, never by the API process.
2. **Hard rule:** the Render web process must never spawn Playwright or run a crawl/enrich loop. Those run only in GH Actions. Enforce in code review (Doc 08).
3. **Adapter interface first.** Define `SourceAdapter` (`fetch() -> list[RawListing]`, `parse(raw) -> NormalizedListing`) before writing any specific crawler. Everything plugs into it. (Doc 04.)
4. **Config-driven plan gating.** Implement `plan_features` as data, consumed by a single `can(user, feature)` helper. No scattered plan checks.
5. **Read/write separation in code.** API modules never call crawl/enrich functions synchronously. Enrichment is triggered only inside the ingestion pipeline.
6. **Caching + rate limiting are cross-cutting from day one** (Upstash), not a later optimization — wrap the feed, search, match, and copilot endpoints.
7. **Observability baseline:** structured logs for every crawl run, enrichment, and notification batch; a `crawl_runs` table (Doc 03) as the operational dashboard; alert on adapter failure rate.
8. **Env/secrets:** all keys (Anthropic, Razorpay, Resend/SES, Supabase) via env vars; never in code. Separate dev/prod Supabase projects.

**Definition of done for the architecture layer:** crawlers run on a free schedule and write canonical, enriched opportunities to Postgres; the API serves fast cached reads with config-driven gating; no per-user AI on the hot path; the Render dyno never does heavy work.
