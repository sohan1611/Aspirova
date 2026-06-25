# 04 — Crawler System

*Author: Chief Architect. This is the heart of Aspirova's moat — and its biggest risk. Read §1 before anything else.*

---

## 1. The foundational reframe (do not skip)

The brief lists Internshala, Unstop, Wellfound, etc. as primary sources. **As Chief Architect I am formally rejecting "scrape the aggregators" as the foundation,** for two reasons:

- **Legal/ToS:** these platforms forbid scraping and actively block bots. Building the company *on* them is fragile and exposes Aspirova to cease-and-desist risk (Doc 01 R1).
- **Technical:** HTML scraping breaks constantly; you'd be on a maintenance treadmill.

**The foundation is ATS-direct ingestion.** A large share of real, fresh internships/jobs live on a handful of Applicant Tracking Systems that expose **structured, semi-public, per-company board endpoints** — Greenhouse, Lever, Ashby, Workable, SmartRecruiters, and (harder) Workday. These return clean JSON, need **no browser**, are **stable**, are **low legal risk** (they're the company's own published board), and are **near-free** to fetch. This is the durable, cheap, defensible core. Aggregators become a **best-effort secondary tier**, respected and droppable.

> **Crawler strategy hierarchy:**
> 1. **ATS JSON endpoints** (Greenhouse/Lever/Ashby/…) — primary, structured, low-risk.
> 2. **Official feeds/APIs** (RSS, university JSON, GitHub APIs, hackathon platform APIs where ToS-permitted).
> 3. **Direct company career pages** without a known ATS — HTML parse, often static.
> 4. **Aggregators** (Internshala/Unstop/Wellfound) — **best-effort, robots-respecting, metadata-only + link-out, instantly droppable on notice.**

---

## 2. Crawl tiers (refined from the brief)

Tier by **volatility × value**, mapped 1:1 to GitHub Actions cron schedules.

| Tier | Frequency | Sources | Why |
|------|-----------|---------|-----|
| **Tier 1** | **1–2h** | Top-company ATS boards (FAANG-adjacent + hot startups), high-velocity aggregator categories | Fast-moving, high-demand; "first to know" promise |
| **Tier 2** | **6h** | Mid-size company ATS boards, startup career pages, university career portals | Moderate velocity |
| **Tier 3** | **24h** | Research labs, hackathon platforms, ambassador programs, GitHub opportunity repos, niche fellowships | Slow-moving, long-tail, the unique moat (Doc 01) |

**Refinements over the brief:**
- ATS endpoints are so cheap that **Tier-1 ATS crawling can be more frequent** than aggregator crawling without cost pain — lean into the cheap channel.
- **Change detection (§6) makes frequency cheap:** if a board's content hash hasn't changed, the run costs almost nothing. So "every 1–2h" is affordable.
- Aggregators in Tier 1/2 run **less aggressively** than ATS (respect rate limits / robots), because they're the risky, expensive channel.

---

## 3. Adapter architecture (everything is an adapter)

```
                 ┌──────────────────────────────────────────┐
                 │            SourceAdapter (interface)        │
                 │  fetch()  -> list[RawListing]               │
                 │  parse(raw) -> NormalizedListing            │
                 │  health()  -> ok | degraded | broken        │
                 └──────────────────────────────────────────┘
                     ▲           ▲           ▲           ▲
        ┌────────────┘   ┌───────┘     ┌─────┘      ┌────┘
  GreenhouseAdapter  LeverAdapter  AshbyAdapter  AggregatorAdapter(HTML/Playwright)
  (JSON, no browser) (JSON)        (JSON)        (best-effort, robots-checked)
  UniversityAdapter  GithubAdapter  HackathonAdapter  ...
```

- **One interface, many adapters.** Adding a source = adding an adapter + a `sources` row. Core pipeline never changes.
- **ATS adapters are parameterized, not per-company.** One `GreenhouseAdapter` handles *every* Greenhouse company by board token (`companies.ats_board_id`). Onboarding a new company = inserting a `companies` row with its ATS type + board id. **This scales to thousands of companies with one adapter.** That is the leverage.
- **Adapters declare their needs:** `requires_browser: bool`. Only HTML-heavy aggregators set it true → only those incur Playwright cost.

---

## 4. Execution model (where crawlers run)

- **GitHub Actions cron** triggers per tier (`schedule: cron`). A workflow:
  1. Loads due `crawl_jobs` (or computes the due source set for its tier).
  2. **Matrix-fans-out** sources across parallel runners (free parallelism).
  3. Each job: `fetch → change-detect → parse → write raw_listings → enqueue normalize/dedup`.
- **Why GH Actions:** free scheduled compute, version-controlled schedules, isolated runs, easy parallelism. Keeps the Render dyno light (Doc 02).
- **Render dyno never crawls.** Hard rule.
- **Budget guard:** monitor monthly Actions minutes; if approaching the cap, stagger schedules or move the heaviest job to a single cheap always-cheap box. Documented trigger (Doc 02 §5).

---

## 5. Playwright usage policy (strict, because it's the cost risk)

- **Default: NO browser.** ATS/JSON/feed adapters use plain HTTP — fast, tiny RAM, cheap.
- **Playwright only when a site genuinely requires JS rendering** (some aggregators/SPAs). Even then:
  - Run **headless**, **block images/fonts/media** (route interception) to cut RAM/bandwidth.
  - **Reuse a single browser context** per run; never one browser per listing.
  - Run **only in GH Actions**, never on Render.
  - Prefer finding the site's **underlying XHR/JSON API** (DevTools network) and hitting that directly instead of rendering — usually possible, far cheaper. *Always try this before reaching for Playwright.*
- **Concurrency caps** to avoid hammering a source (politeness + ban-avoidance).

---

## 6. Change detection (the core cost lever)

- Per crawlable page/board, store `last_content_hash` in `source_state` (Doc 03 §5.2).
- On each run: fetch → hash → **if unchanged, stop** (no parse, no dedup, no AI enrichment). Only changed content flows downstream.
- For ATS endpoints, also diff the **set of listing IDs** to detect adds/removes cheaply.
- **Why it matters:** enrichment (AI) and dedup are the expensive downstream steps. Change detection ensures we pay for them only on genuinely new/changed content — this is what makes 1–2h Tier-1 frequency affordable (Doc 06).

---

## 7. Retry, failure recovery, resilience

- **Per-source isolation:** an adapter failure marks that `crawl_run` failed/partial and alerts; it never aborts the batch or other sources.
- **Retries:** exponential backoff with jitter, capped attempts (`crawl_jobs.attempts`). Distinguish transient (5xx/timeout → retry) from structural (404/403/parse-shape-changed → mark adapter `degraded`/`broken`, alert, don't blind-retry).
- **Circuit breaker:** if a source fails N consecutive runs, auto-pause it (`sources.enabled=false`) and alert, rather than burning minutes/risking bans.
- **Idempotency:** re-running a crawl must not create duplicate canonical opps — dedup + `(source_id, external_id)` uniqueness guarantees this.
- **Dead-letter:** unparseable raw payloads are kept (`processed=false`, flagged) for inspection, never silently dropped.

---

## 8. Queue system

- **Postgres `crawl_jobs` with `FOR UPDATE SKIP LOCKED`** (Doc 03 §5.1). Multiple GH Actions runners claim disjoint jobs without contention. No Kafka/RabbitMQ/Celery — unearned complexity at this scale.
- Pipeline stages (`fetch → normalize → dedup → enrich`) are decoupled via job rows / `processed` flags so each stage drains independently and can be re-run.

---

## 9. Deduplication engine (logic; data in Doc 03 §7)

Pipeline when a new/changed raw listing arrives:
1. **Normalize** title, company (strip legal suffixes, lowercase), location.
2. **Block** candidates by `(company_id or normalized domain, title_normalized)` — only compare within a block (cheap).
3. **Score** similarity: trigram(title) + cosine(description embedding) + deadline/location agreement.
4. **Decide:**
   - High score → **merge**: attach `opportunity_sources` row, refresh `last_seen_at`, keep richest description; **do not re-enrich** (already enriched).
   - Low score → **new canonical opp** → enrich once (Doc 05).
5. **Provenance preserved** so a bad merge is reversible.

**Cross-source dedup is the visible payoff** (Doc 01): "found on company page + Internshala + Unstop" → one clean record.

---

## 10. Legal, robots.txt & ethics policy (binding)

This is not optional polish; it's existential risk management (Doc 01 R1).

- **Respect `robots.txt`** for all non-API HTML sources. `sources.robots_policy` records the stance; default `respect`.
- **Identify honestly:** a real User-Agent string with a contact URL. No spoofing, no stealth-evasion to defeat anti-bot systems for aggregators.
- **Politeness:** rate-limit per source; never hammer; back off on 429.
- **Metadata + link-out, not mirroring:** for aggregator-sourced content, store metadata and a short normalized summary, and **always link to the original**. Don't republish full proprietary descriptions verbatim as if they're ours. Position Aspirova as an *index/search* layer (like a search engine) that drives traffic *to* the source.
- **Prefer official/structured channels** (ATS, APIs, RSS) precisely because they carry an implicit "this is published for consumption" signal.
- **Takedown response:** `sources.legal_status` lets us flip a source to `paused` instantly. Maintain a documented process to honor takedown requests within a stated window.
- **Personal data:** crawl *opportunities*, not people. Don't harvest applicant or recruiter personal data.
- ⚠️ **This is engineering policy, not legal advice. Before scaling paid usage or aggressively crawling Indian aggregators, the founder must get a lawyer's read.** Cheaper than litigation.

---

## 11. Source onboarding playbook (how the moat compounds)

To add coverage (the data-moat flywheel):
1. **Find the ATS.** For a target company, detect Greenhouse/Lever/Ashby (URL patterns, page markers). If found → insert `companies` row with `ats_type` + `ats_board_id`. **Done — existing adapter covers it.** Zero new code.
2. **No ATS?** Add to Tier-2/3 with a generic HTML adapter or a small custom parser.
3. **Long-tail (labs, ambassador, GitHub):** Tier-3 adapters; often a single curated list + light parsing. *These are the uniquely valuable, low-competition sources — invest here disproportionately.*
4. **Track health** via `crawl_runs`; broken adapters surface on the ops view.

**Leverage insight:** the ATS-parameterized design means coverage scales by *data entry* (adding company board IDs), not by *engineering*. A coding agent can be tasked to bulk-discover and insert ATS board IDs — that's how Aspirova reaches thousands of companies cheaply.

---

## HANDOFF TO ENGINEERING

**Build in this order:**
1. **`SourceAdapter` interface + the pipeline skeleton** (`fetch → raw_listings → normalize → dedup → enrich`) with Postgres-as-queue. Get one end-to-end flow working before breadth.
2. **`GreenhouseAdapter` first** (cleanest public JSON board endpoint), parameterized by board token — proves the ATS-parameterized model. Then `LeverAdapter`, `AshbyAdapter`.
3. **Change detection** (`source_state` hashing) wired *before* enrichment, so AI cost is gated from day one.
4. **Dedup engine** with blocking + trigram + embedding scoring; preserve provenance in `opportunity_sources`.
5. **GH Actions workflows** per tier (cron + matrix). Render never runs a crawl.
6. **Playwright adapter** only after JSON sources work, and only for sites that truly need it — with image/media blocking and shared context. Always attempt the underlying XHR/JSON API first.
7. **Resilience:** per-source isolation, backoff+jitter retries, circuit breaker, idempotency, dead-letter for unparseable payloads.
8. **Legal guardrails as code:** robots.txt checks, honest UA + contact, per-source rate limits, `legal_status` kill-switch, link-out-not-mirror enforced in the serving layer.
9. **Ops visibility:** populate `crawl_runs`; alert on adapter failure-rate and circuit-breaker trips.

**Hard rules (review will reject violations):**
- No crawler runs on the Render web dyno.
- No Playwright unless `requires_browser=true` and the XHR/JSON route was checked first.
- No enrichment without passing change detection.
- No mirroring of full aggregator content; always store + display the outbound source link.
- No defeating anti-bot measures on aggregators; respect robots.txt and rate limits.

**Definition of done for the crawler layer:** ATS-parameterized adapters ingest thousands of company boards on a free schedule; change detection gates downstream cost; dedup yields one canonical opp per real opportunity with full provenance; aggregators are best-effort and instantly droppable; the whole thing runs off Render.
