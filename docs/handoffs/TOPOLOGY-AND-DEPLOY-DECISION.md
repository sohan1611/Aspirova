# Architect Decision Record — Topology & Deployment Timing

*Author: Chief Architect (Opus) · Date: 2026-06-30 · Status: BINDING*
*Resolves the open question in [PHASE-1-REPORT.md](PHASE-1-REPORT.md) §6.*

> **Correction note (kept deliberately, not erased):** an earlier draft of this ADR recommended *deferring* deployment, on the premise that the crawler "still does not complete." That premise was **wrong** — verification run 28420810872 actually finished in **12m45s, all 12 companies `success`, 0–1 errors each** (the batched-commit fix worked; the earlier "no output" reading was buffered logs mid-run, not a hang). With the crawler confirmed working, the decision below is the corrected one. The reasoning is preserved transparently because how a decision was reached matters as much as the decision.

---

## The question
"Should we deploy the FastAPI backend to Render + Next.js frontend to Vercel now?"

## The decision
**Yes — deploy now, but as a deliberately *minimal, reversible measurement*, not a "Phase 1 is shipped" milestone.** Render **Singapore** + Vercel **Hobby**, `render.yaml` as IaC, Supabase stays in Mumbai for now. The crawler stays on GitHub Actions (canon-compliant). Hardening (rate limiting, custom domain, monitoring, any DB region migration) is explicitly **out of scope** and deferred to Phase 2.

### Why deploy now (with the crawler confirmed working)
- **The write path works.** 12 companies crawled in 12m45s on GitHub Actions with near-zero errors. The "don't put a public face on a broken system" objection no longer applies — the system works.
- **The read path is independent and ready.** It serves the 2,348 opportunities already in the DB regardless of crawler state, and was optimized in Step 8 to **one DB round-trip per request**.
- **Deploying is the *only* way to get the one genuinely-unknown number: production read-path p95.** Everything else has been measured locally; the Render-Singapore→Supabase-Mumbai latency cannot be. This is the deliverable that justifies the deploy.
- **It's cheap, reversible, and has real learning/portfolio value** for a solo builder who has stated the intent to scale this. `render.yaml` makes it reproducible *and* tear-down-able.

### Why "minimal + reversible," not "shipped"
- **Render has no Mumbai region** (verified against Render's live docs — options: Oregon, Ohio, Virginia, Frankfurt, Singapore). Closest to the `aws-1-ap-south-1` Supabase project is **Singapore, ~100–150ms away.** True compute↔DB co-location is *not achievable on Render*; name it honestly. A single-query read path at ~120ms should still land p95 under the 300ms target — but that's a prediction the deploy will confirm or refute.
- Because true co-location is impossible, the deploy is a **measurement**, not a validation of an assumed-fast path. Keep it minimal and tear-down-able so it never becomes a sunk commitment.

---

## Architect ruling on topology (the real long-term issue)
**The Mumbai Supabase region is stranded from all available compute** (GitHub Actions = US, Render = Singapore at best, Vercel = US/EU). At Phase-1 scale (12 companies, 12m45s) this is *tolerable*. It will not stay tolerable: Phase 2 adds Lever/Ashby adapters + an aggregator + more companies — easily 3–5× the source count — and at the current latency-bound rate that **blows the crawl timeout.** Two independent levers, in order:

### Lever 1 — cut the crawler's round-trips (do before Phase 2 scales sources; NOT a deploy blocker)
The crawler's cost is round-trip *count* × link *latency*. `ingest_normalized_listing` does ~5 serial round-trips **per listing**; over the US→Mumbai link that's why 12 companies took ~13 minutes. Replace with **set-based** operations per board:
- One query for all existing `raw_listings` (external_id → content_hash) → diff in memory.
- One query for the company's existing active `opportunities` → dedup blocking/scoring in memory.
- **Bulk** insert/update `raw_listings` / `opportunities` / `opportunity_sources` in a handful of statements, not N×5.
- Effect: a 484-listing board drops from ~2,400 round-trips to single digits — good engineering regardless of region, keeps the crawler **free on GitHub Actions** (Doc 04). **Priority: before Phase 2 adds sources. Not required to deploy the read path or to consider Phase-1 ingestion working.**

### Lever 2 — region consolidation (strategic; gated on measurement)
Clean end-state: **consolidate compute + DB in Singapore** (Supabase `ap-southeast-1` + Render Singapore; optionally the crawler as a Render Cron Job co-located with the DB). Per Doc 02 §5 (*scale by measured trigger, not anticipation*): **the p95 number from this very deployment is the trigger.** If Render-Singapore→Mumbai p95 is comfortably < 300ms, Mumbai is vindicated and Lever 2 may be unnecessary. If not, that number is the concrete justification to migrate. Migration is cheap-ish (data regenerable by re-crawl, schema in migrations, new project + re-seed + secret re-point) but remains a deliberate Phase-2 decision.

---

## Deployment spec (the actual command for Sonnet)

Minimal + reversible. `render.yaml` committed as IaC.

**Backend — Render:**
- Region **Singapore**.
- **Paid Starter (~$7/mo), NOT free** — the free tier spins down after 15min idle with a ~1-min cold start, which makes a live demo worse than none.
- Start command **exactly**: `uv run uvicorn api.main:app --host 0.0.0.0 --port $PORT` — hardcoding `--port 8000` → 502 on every request; omitting `--host 0.0.0.0` → unreachable container. Build: `uv sync --frozen`.
- Env vars: `DATABASE_URL`, `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_KEY`, and `CORS_ORIGINS` including the Vercel domain. **`service_role` key lives only here, never shipped to the browser.**

**Frontend — Vercel Hobby (free):**
- Server-side fetch to the Render URL works normally; mind the **10s function duration** limit.
- **`NEXT_PUBLIC_*` is inlined at BUILD time** — set `NEXT_PUBLIC_API_URL` (Render URL) + `NEXT_PUBLIC_SUPABASE_URL`/`ANON_KEY` in Vercel env **before** building; changing them later requires a redeploy.
- Hobby is non-commercial/single-seat — fine for a project.

**The deliverable that justifies it:** measure real production read-path **p95** (feed/search/opportunity) once live. Record it in the Phase-1 report. That number drives the Lever-2 decision.

**Explicitly DEFER to Phase 2:** rate limiting, custom domain, uptime monitoring, any Supabase region migration. Estimated cost: Render ~$7/mo + Vercel $0.

---

## Decision-log entries (mirrored into README)
- Deploy read path now, **minimal + reversible**, Render Singapore + Vercel Hobby; purpose = real p95 measurement + portfolio artifact — **Binding**.
- Crawler **set-based bulk-operation** refactor (Lever 1) required **before Phase 2 scales source count**; non-blocking for the deploy — **Binding**.
- Region consolidation in Singapore (Lever 2) is the strategic direction, **gated on the measured p95**, not assumed — **Proposed, measure first**.
