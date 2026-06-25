# 08 — Engineering Governance

*Author: Chief Architect (permanent). This document binds whoever implements — Claude Sonnet today, possibly OpenAI Codex tomorrow. The coding agent changes; this does not. The `docs/` canon is law; code conforms to it, not the reverse.*

---

## 0. The governance contract

- The **Chief Architect (Opus)** owns architecture, standards, reviews, roadmap, cost, scalability, product direction — **permanently**.
- The **implementation agent** writes code that conforms to this canon. It is **interchangeable**: Codex can replace Sonnet at any time with zero architectural drift, *because* the rules live here, not in any one agent's head.
- **Deviations require an architect-approved amendment** to the relevant doc + a new **Decision log** row in `README.md`. The implementation agent **surfaces conflicts; it does not silently diverge.**
- When code and canon disagree, **canon wins** until the architect amends it.

---

## 1. Architecture Guidelines (the binding MUST / MUST-NOT)

Consolidated from Docs 02/03/04/05. These are non-negotiable without an amendment.

### Execution & topology
- **MUST** separate the **write path** (crawl/normalize/dedup/enrich — batch, async) from the **read path** (API serving — fast, cheap). They share the database, never a request lifecycle.
- **MUST NOT** run crawlers or Playwright on the **Render web dyno**. All crawl/enrich runs on **GitHub Actions cron** only.
- **MUST** keep the always-on footprint minimal; push heavy/bursty work to free scheduled compute.

### Crawling
- **MUST** be **ATS-first** (Greenhouse/Lever/Ashby JSON endpoints, parameterized by board token). Aggregators are **best-effort, robots-respecting, metadata-only + link-out**, instantly droppable via `sources.legal_status`.
- **MUST NOT** use Playwright unless `requires_browser=true`, and **MUST** first attempt the underlying XHR/JSON endpoint. When used: headless, block images/media, shared context, GH Actions only.
- **MUST** respect `robots.txt`, send an honest User-Agent + contact, rate-limit per source, and **link out — never mirror full proprietary content as our own.**
- **MUST** pass **change detection** (content-hash) before any downstream parse/dedup/enrich.

### Data plane
- **MUST** use **Postgres only** for store + search (`tsvector`/`pg_trgm`) + vectors (`pgvector`) + queue (`SELECT … FOR UPDATE SKIP LOCKED`). **MUST NOT** introduce Elasticsearch/Pinecone/Kafka/RabbitMQ/Celery without a measured trigger + amendment.
- **MUST** keep **one canonical `opportunities` row per real opportunity**, with raw/canonical separation and provenance in `opportunity_sources` (Doc 03).
- **MUST** make **migrations the schema contract** (Alembic/SQL migrations). No ad-hoc prod schema changes.
- **MUST** partition `user_events` monthly; **MUST NOT** prematurely partition `opportunities`.

### AI
- **MUST** enrich **once per canonical opp, after dedup + change detection, idempotently** (guard on existing summary + hash).
- **MUST** implement **Resume Match as pgvector cosine**. **MUST NOT** make any per-`(user × opportunity)` LLM call for ranking.
- **MUST** gate **Career Copilot** to Pro, **rate-limit** (Upstash), cache shared answers, use the cheapest viable model + concise outputs.
- **MUST** route all model/embedding calls through a **single `ai_client` abstraction** (provider-swappable, model-version-aware, usage-logged). **MUST NOT** scatter raw SDK calls in feature code.
- **MUST** log AI usage (`ai_usage`), alarm on daily spend, and **degrade gracefully** (templated/keyword fallback) at the cap.

### Product/business rules
- **MUST** drive plan gating from **`plans.features` (jsonb)** via a single `can(user, feature)` helper. **MUST NOT** scatter `if plan == 'pro'` checks.
- **MUST** keep plans/prices as **data**, not code (annual prepay = a row).
- **MUST** label AI guesses (inferred deadlines, "fit" heuristics) as estimates; the **source link is truth** (trust + legal).

### Scaling
- **MUST** scale by **measured trigger** (Doc 02 §5), never by anticipation.

---

## 2. Coding Standards

### Languages & frameworks (canon)
- **Backend:** Python + **FastAPI**. **Crawlers/enrich:** Python (same `core` models). **Frontend:** **Next.js** (App Router) + TypeScript.
- One backend repo with clear modules: `api/`, `crawlers/`, `core/` (shared models + schema), `enrich/`, `notify/`. Crawlers import `core`; they're invoked by GH Actions, never by the API process.

### General
- **Type everything** (Python type hints + `mypy`/`pyright`; strict TS). Public functions have typed signatures.
- **Secrets via environment variables only.** Never commit keys (Anthropic, Razorpay, Resend/SES, Supabase). Separate dev/prod Supabase projects.
- **Errors:** fail soft at the system boundary (a broken adapter degrades that source only), fail loud in logs. No silent `except: pass`. Distinguish transient (retry w/ backoff+jitter) vs structural (mark degraded/broken, alert).
- **Idempotency is mandatory** for every pipeline stage: re-running a crawl/enrich must not duplicate canonical opps or double-charge AI. Enforce via unique keys + existence guards.
- **Logging/observability:** structured logs for every crawl run, enrichment, and notification batch; write to `crawl_runs`/`ai_usage`/`notifications`. Every cost-bearing action is countable.
- **Naming:** descriptive, consistent; match the surrounding code's idiom and comment density. Adapters end in `Adapter`; one adapter per source *type*, parameterized — not per company.
- **No dead code, no speculative abstractions** beyond the `SourceAdapter`/`ai_client` seams the canon mandates.

### Testing
- **Unit-test** the dedup engine, normalizers, and each adapter's `parse()` against captured fixtures (real payload snapshots) — these are where silent breakage hides.
- **Integration-test** one full ingest path (fetch → canonical → enrich) and the gating helper (`can`).
- **Cost-sensitive paths** (Resume Match, Copilot, enrichment) get tests asserting **no unexpected LLM calls** (mock `ai_client`, assert call counts).
- Migrations tested against a disposable DB before prod.

---

## 3. Review Checklist (run before every merge)

> The architect (or an automated reviewer) runs this. Anything in **HARD RULES** auto-rejects.

**HARD RULES — auto-reject if violated:**
- [ ] No crawler/Playwright code path runs on the Render web dyno.
- [ ] No Playwright without `requires_browser=true` + a checked XHR/JSON alternative.
- [ ] No enrichment without passing change detection + dedup; enrichment is idempotent.
- [ ] No per-`(user × opportunity)` LLM call (Resume Match is cosine).
- [ ] No raw AI SDK calls outside `ai_client`.
- [ ] No scattered plan checks (gating goes through `plans.features` + `can`).
- [ ] No mirroring of full aggregator content; outbound source link present; robots.txt respected.
- [ ] No secrets in code.

**Architecture compliance:**
- [ ] Read/write path separation preserved.
- [ ] New source = new `SourceAdapter` + `sources` row, core untouched.
- [ ] Postgres-only data plane (no new infra without amendment).

**Cost discipline:**
- [ ] AI work is shared/precomputed where possible; `ai_usage` logged; spend bounded.
- [ ] Email batched (digest), frequency-capped, inactive recipients suppressed.
- [ ] Caching/rate-limiting applied to feed/search/match/copilot.

**Data & migrations:**
- [ ] Schema change ships as a migration; indexes justified by a real query; no unused index added.
- [ ] Canonical-opp invariant + provenance intact; idempotent writes.

**Security & legal:**
- [ ] Secrets via env; authz on every user-data endpoint; no PII harvested from crawls.
- [ ] `legal_status` kill-switch honored; rate limits + honest UA in place.

**Performance:**
- [ ] No AI/heavy work on the hot read path; queries hit the intended index; p95 within budget.

**Tests & observability:**
- [ ] Adapter `parse()` + dedup covered by fixtures; cost-path call-count tests present; structured logs emitted.

---

## 4. Handoff Document template (architect → coding agent, per task)

Copy-paste and fill for each unit of work. Keep it tight; link to canon rather than restating it.

```
# HANDOFF: <task name>   (Doc owner: Chief Architect | Implementer: Sonnet/Codex)

## Context
<1–3 sentences: why this exists, which roadmap phase, which docs govern it>

## Scope
- In:  <exactly what to build>
- Out: <explicitly what NOT to touch>

## Canonical references
<links: e.g. Doc 04 §3 SourceAdapter; Doc 03 §3.4 opportunities; Doc 05 §2.2 Resume Match>

## Interface contracts
<function/class signatures, schemas, endpoints, event shapes the work must conform to>

## Acceptance criteria
- [ ] <observable, testable outcomes>

## Cost / performance budget
<e.g. no per-match LLM; enrich once per canonical; p95 < 300ms; AI calls logged>

## Test plan
<unit/integration/cost-path tests required to pass>

## Review gates
<which HARD RULES apply; any extra checks; who/what signs off>
```

---

## 5. Agent-agnostic notes (so Codex can replace Sonnet cleanly)

- **The canon is the memory.** All durable decisions live in `docs/`, not in agent context. A new agent reads `docs/` and is fully onboarded.
- **The Decision log (`README.md`) is append-only.** Binding rows are not edited away; superseded decisions get a new row referencing the old.
- **Conflicts go up, not around.** If the canon is wrong, unclear, or blocks correct implementation, the agent **raises an amendment request** — it does not invent a workaround that diverges silently.
- **Style continuity:** new code matches existing idiom, structure, and the seams the canon defines (`SourceAdapter`, `ai_client`, `can`). Consistency across agents > any single agent's preference.
- **No agent expands architecture scope.** Adding infra, a new language, or a new data store is an *architect* decision (amendment), regardless of which agent proposes it.

---

## HANDOFF TO ENGINEERING

1. **Adopt this document as the merge gate now.** Wire §3's HARD RULES into review (manual at first; automate what you can — a CI lint for "no `anthropic` SDK import outside `ai_client`", "no Playwright import in `api/`", etc.).
2. **Encode the seams the canon depends on early:** `SourceAdapter`, `ai_client`, `can(user, feature)`. Most HARD RULES are automatically satisfied if code is forced through these seams.
3. **Use the §4 template for every non-trivial task.** A task without a handoff doc is a task that will drift.
4. **Keep `docs/` and the Decision log current.** Any approved deviation = doc amendment + log row, same PR.
5. **On agent handoff (Sonnet → Codex or vice versa):** the incoming agent's first action is to read all of `docs/`; no other onboarding is required or permitted to substitute for it.

**Definition of done for governance:** any compliant PR passes §3 without architect intervention; a brand-new coding agent can onboard purely from `docs/` and produce conforming code; no architectural decision lives only in code or in an agent's transient context.
