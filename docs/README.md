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

> Engineers: do not contradict a **Binding** row without an architect-approved amendment.
