# PHASE 1 HANDOFF — Foundation & Ingestion Core

*From: Chief Architect (Opus) · To: Lead Engineer (Claude Sonnet) · Status: ACTIVE*
*Prerequisite: you have read ALL of `docs/` (README + 01–08). The canon is law; this handoff sits on top of it.*

---

## 1. Context

Aspirova auto-discovers student opportunities and serves them as one deduplicated, deadline-aware feed (see [Doc 01](../01-product-strategy.md)). Phase 1 builds the **data backbone**: the pipeline that crawls a real ATS, normalizes and **deduplicates** listings into canonical opportunities, and stores them in Postgres — running on free scheduled compute, off the Render web dyno.

**Phase 1 does NOT include:** payments, plans, AI/enrichment, embeddings, notifications, search UI polish, or the public frontend beyond what Part 1.7 specifies. Those are later phases ([00-BUILD-PLAN](00-BUILD-PLAN.md)). Resist pulling them forward.

---

## 2. Scope

**In scope:**
- Monorepo scaffold (backend + frontend + CI/crawl workflows).
- Postgres schema (Phase-1 subset) via migrations.
- `SourceAdapter` interface + **`GreenhouseAdapter`** (ATS-first, Doc 04).
- Ingestion pipeline: fetch → `raw_listings` → normalize → canonicalize/**dedup** → `opportunities` (+ provenance).
- **Change detection** (content-hash gate) before downstream work.
- Crawl runner + **GitHub Actions cron** (Tier-1 subset).
- Minimal read API + minimal Next.js feed/search/SSR pages/bookmarks/auth (Part 1.6–1.7).

**Out of scope (do not build):** Lever/Ashby/aggregator adapters, Playwright, AI/`ai_client`, embeddings/`pgvector`, subscriptions/Razorpay, notifications, referral/B2B hooks. (Schema may include columns the canon defines, but no behavior for them yet.)

---

## 3. Canonical references (read these sections before coding)

- Architecture & seams: [Doc 02](../02-system-architecture.md) §3, §4, §HANDOFF
- Schema (authoritative): [Doc 03](../03-data-architecture.md) §3, §6 (indexes), §7 (dedup data)
- Crawler design & rules: [Doc 04](../04-crawler-system.md) §3 (adapters), §6 (change detection), §9 (dedup), §10 (legal)
- Governance / HARD RULES: [Doc 08](../08-engineering-governance.md) §1, §2, §3

---

## 4. Tech stack (binding for Phase 1)

| Layer | Choice | Notes |
|---|---|---|
| Language (backend/crawlers) | **Python 3.12+** | one runtime for api + crawlers + pipeline |
| API framework | **FastAPI** | read endpoints only in Phase 1 |
| ORM + migrations | **SQLAlchemy 2.x + Alembic** | migrations are the schema contract (Doc 08) |
| Models/validation | **Pydantic v2** | for adapter `NormalizedListing` + API schemas |
| HTTP client | **httpx** | ATS JSON fetching; no browser |
| DB | **Supabase Postgres** (dev project) | enable `pg_trgm`; `vector` extension may be enabled but unused in Phase 1 |
| Dep manager | **uv** (preferred) or Poetry | pick one, commit the lockfile |
| Frontend | **Next.js (App Router) + TypeScript** | Vercel-targeted; SSR for opportunity pages |
| Crawl scheduler | **GitHub Actions cron** | NEVER the Render dyno |
| Lint/format | ruff + black (py), eslint + prettier (ts) | wire into CI |

**Hosting (Phase 1):** Render runs only the FastAPI read API. Supabase hosts Postgres + Auth. GitHub Actions runs the crawler. Frontend can run locally/Vercel preview.

---

## 5. Repository structure (create this)

```
aspirova/
  backend/
    core/
      config.py            # env-based settings (no secrets in code)
      db.py                # SQLAlchemy session/engine
      models.py            # ORM models (Doc 03 subset)
      schemas.py           # Pydantic: NormalizedListing, API DTOs
      adapters.py          # SourceAdapter Protocol + RawListing/NormalizedListing
    crawlers/
      greenhouse.py        # GreenhouseAdapter
      runner.py            # claims due sources, runs adapters, writes crawl_runs
      registry.py          # adapter_key -> adapter class
    pipeline/
      normalize.py         # field normalization
      dedup.py             # blocking + similarity + canonical merge
      ingest.py            # orchestrates fetch->raw->normalize->dedup
    api/
      main.py              # FastAPI app
      feed.py  search.py  opportunity.py  bookmarks.py  auth.py
    migrations/            # Alembic
    tests/
    pyproject.toml
  frontend/                # Next.js app (App Router)
  .github/workflows/
    crawl-tier1.yml        # cron crawler
    ci.yml                 # lint + tests
  docs/                    # the canon (already present)
```

---

## 6. Interface contracts (architect-specified — implement to these exactly)

### 6.1 Adapter contract (`core/adapters.py`)
```python
class RawListing(BaseModel):
    source_slug: str
    external_id: str | None
    source_url: str
    content_hash: str          # hash of the normalized raw payload
    raw_payload: dict

class NormalizedListing(BaseModel):
    source_slug: str
    external_id: str | None
    source_url: str
    title: str
    company_name: str
    company_domain: str | None = None
    location: str | None = None
    is_remote: bool | None = None
    category: str | None = None       # 'internship'|'job'|... (keyword-classified)
    description_raw: str
    apply_url: str
    posted_at: datetime | None = None
    deadline: datetime | None = None
    deadline_confidence: str = "unknown"   # 'explicit'|'inferred'|'unknown'

class SourceAdapter(Protocol):
    source_slug: str
    requires_browser: bool             # MUST be False for GreenhouseAdapter
    def fetch(self) -> Iterable[RawListing]: ...
    def parse(self, raw: RawListing) -> NormalizedListing: ...
    def health(self) -> Literal["ok", "degraded", "broken"]: ...
```

### 6.2 Greenhouse data source (real, public — no auth, no browser)
- Endpoint: `GET https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs?content=true`
- Returns `{ "jobs": [ { id, title, updated_at, absolute_url, location: {name}, content (HTML), ... } ] }`
- `external_id = job.id`; `source_url = apply_url = job.absolute_url`; `title`, `location.name`, decode `content` (HTML→text) into `description_raw`; `posted_at`/freshness from `updated_at`.
- **Change detection:** hash the jobs payload (or per-job `updated_at` set) into `source_state` (Doc 03 §5.2); if unchanged since last run, **skip** parse+dedup for that board.
- **Company board tokens are DATA**, seeded in `companies.ats_board_id` (Doc 03/04 §11). Do **not** hardcode tokens in code. Seed 5–20 **verified** real Greenhouse boards (validate each returns 200 + jobs before seeding). Log/skip any token that 404s.

### 6.3 Category classification (Phase-1, rules-based — no AI)
Classify `category` by title keywords: `internship`/`intern`/`co-op`/`trainee`/`apprentice`/`campus`/`new grad` → `internship`; else `job`. Keep it in `normalize.py`; it's a placeholder for richer Phase-5 tagging.

### 6.4 Dedup contract (Doc 04 §9, Doc 03 §7)
- **Blocking:** candidates share `(company_id or normalized domain, title_normalized)`.
- **Similarity (Phase 1, no embeddings):** trigram similarity on `title_normalized` + exact-ish company match + location agreement. Threshold tunable via config.
- **Decision:** above threshold → attach `opportunity_sources` row to existing canonical opp, refresh `last_seen_at`, keep richest `description_raw`, **do not duplicate**. Below → create new `opportunities` row.
- **Idempotent:** re-running the same crawl creates **zero** new canonical opps and **zero** duplicate `opportunity_sources` rows (enforce via `(source_id, external_id)` uniqueness on `raw_listings` and `UNIQUE(opportunity_id, source_id, source_url)` on `opportunity_sources`).

---

## 7. Suggested part-by-part decomposition

Build in this order; each part is independently testable and committable. Refine if you find a better seam — note it in the Phase Report.

| Part | Deliverable | "Done" check |
|---|---|---|
| **1.1 Scaffold** | Monorepo, FastAPI skeleton (`GET /health` → 200), Next.js skeleton, Supabase dev project, env config, Alembic init, CI lint job | `/health` returns 200; `alembic upgrade head` runs clean on dev DB; CI passes |
| **1.2 Schema** | Migrations for Phase-1 tables: `sources, companies, raw_listings, opportunities, opportunity_sources, tags, opportunity_tags, users, bookmarks, crawl_runs, source_state`; enable `pg_trgm`; `search_tsv` generated col + GIN; indexes from Doc 03 §6 (Phase-1 subset) | Schema matches Doc 03; indexes present (`\d+`); migration is reversible |
| **1.3 Adapter** | `SourceAdapter` contract + `GreenhouseAdapter` (`requires_browser=False`) + `source_state` change detection | Given a real board token, `fetch()`→`raw_listings`; 2nd run with unchanged board is skipped; bad token logs+skips |
| **1.4 Pipeline** | `normalize.py` + `dedup.py` + `ingest.py` wiring raw→canonical with provenance | Same job from 2 seeded sources → 1 `opportunities` row + 2 `opportunity_sources` rows; full re-run = 0 dupes |
| **1.5 Runner + cron** | `runner.py` (claims due sources via `crawl_jobs`/tier, runs adapters, writes `crawl_runs`); `.github/workflows/crawl-tier1.yml` on cron | GH Actions run populates DB on schedule; `crawl_runs` logged; one failing adapter doesn't abort the batch |
| **1.6 Read API** | `GET /feed` (filters: category, remote, deadline sort, pagination), `GET /search?q=` (tsvector + pg_trgm fallback), `GET /opportunity/{slug}`, Supabase auth, `POST/DELETE /bookmarks` | Endpoints return correct indexed results; p95 < 300ms on seeded data; **no AI/heavy work on the hot path** |
| **1.7 Frontend** | Next.js: feed page, search + filters, **SSR `/opportunity/{slug}`** (SEO meta + canonical outbound `apply_url`), deadline/"closing soon" view, bookmark toggle, basic auth UI | View-source on an opportunity page shows server-rendered content + meta tags; stranger can search→open→sign up→bookmark |

---

## 8. Acceptance criteria (Phase-1 gate — all must hold)

1. **Real, deduplicated opportunities** from ≥1 Greenhouse board are present in `opportunities`, each with ≥1 `opportunity_sources` provenance row.
2. **Dedup works:** an opportunity appearing via two seeded sources is a single canonical row; the full pipeline is **idempotent** on re-run (no duplicates).
3. **Change detection works:** an unchanged board on a second crawl performs no parse/dedup (verifiable in logs / `crawl_runs`).
4. **Crawling runs on GitHub Actions on a schedule** and writes `crawl_runs`; **nothing crawls on the Render dyno.**
5. **Read path is fast and AI-free:** feed/search/opportunity endpoints hit the intended indexes; p95 < 300ms on seeded data.
6. **A stranger can:** search the feed, open an SSR (server-rendered, SEO-tagged) opportunity page with a working outbound "Apply at source" link, sign up, and bookmark.
7. **Cost:** running footprint is ~$7–10/mo (Render + domain; everything else free tier).

---

## 9. Cost & performance budget

- **Infra:** Render $7 + domain only. No paid Supabase/Upstash/AI/email in Phase 1.
- **Crawl:** ATS JSON only — **no Playwright** (`requires_browser=False`). Respect `robots`/politeness even though Greenhouse boards are public (Doc 04 §10); send an honest User-Agent + contact.
- **Perf:** feed/search p95 < 300ms on seeded data; crawl of the seeded boards completes well within a GH Actions run.

---

## 10. Test plan (required to pass)

- **Unit:** `GreenhouseAdapter.parse()` against a **captured real payload fixture**; `normalize.py` (title/company/category); `dedup.py` (merge vs new-record decisions, idempotency).
- **Integration:** one full `ingest` path (fetch→canonical) against a fixture board; `GET /feed` + `GET /opportunity/{slug}` return expected shapes; `can`-style gating helper stub returns Phase-appropriate defaults (full gating is Phase 3).
- **Idempotency test:** run `ingest` twice on the same fixture → assert canonical + provenance counts unchanged.
- **No-browser test:** assert `GreenhouseAdapter.requires_browser is False` and that no Playwright import exists in `api/` or `crawlers/greenhouse.py`.

---

## 11. Review gates (Doc 08 §3 — these auto-reject if violated)

- [ ] No crawler/Playwright code path runs on the Render web dyno.
- [ ] No Playwright at all in Phase 1 (`requires_browser=False`).
- [ ] Outbound `apply_url`/`source_url` stored + displayed; **no mirroring** of content as our own; robots respected.
- [ ] One canonical opp per real opportunity; provenance preserved; writes idempotent.
- [ ] Migrations are the schema contract; every index justified by a Phase-1 query.
- [ ] No secrets in code (Anthropic/Supabase/etc. via env only; dev vs prod Supabase separate).
- [ ] Adapter logic lives behind the `SourceAdapter` seam; adding a source = new adapter + `sources`/`companies` rows, core untouched.

---

## 12. What to hand back to Opus (Phase 1 Report)

Use the **Phase Report** template in [00-BUILD-PLAN](00-BUILD-PLAN.md). Specifically include:
- Evidence for each acceptance criterion in §8 (commands, row counts, a screenshot of an SSR opportunity page + its view-source meta, `crawl_runs` excerpt, p95 numbers).
- Any **amendment requests** (e.g., a Doc 03 field you found needs changing) — do not edit the canon yourself.
- Confirmation of the §11 HARD RULES self-check.
- Notes that should shape the Phase 2 handoff (what you learned about the adapter/dedup seams).

**Then stop.** Do not begin Phase 2. The user will ping Opus to review and issue the Phase 2 handoff.

---

## Definition of done (Phase 1)
Real deduplicated opportunities flow daily from a live ATS into Postgres via GitHub Actions; a stranger can search them and open a fast, SEO-indexable, server-rendered opportunity page that links out to the real application; the pipeline is idempotent and change-detection-gated; nothing heavy runs on the Render dyno; the whole thing costs ~$7–10/mo — and every §11 HARD RULE holds.
