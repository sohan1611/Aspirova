# PHASE 1 REPORT — Foundation & Ingestion Core

*From: Lead Engineer (Claude Sonnet) · To: Chief Architect (Opus) · Status: COMPLETE — backend (Render) + frontend (Vercel) both live, CORS fixed, full production auth+bookmark flow verified (§6)*

---

## 1. What was built

All 11 steps of [PHASE-1-HANDOFF.md](PHASE-1-HANDOFF.md), plus the connection-robustness work that surfaced from running on real infrastructure:

| Part | Outcome |
|---|---|
| 1.1 Scaffold | Monorepo (`backend/`, `frontend/`, `.github/workflows/`), git repo, uv-managed Python project, Next.js project |
| 1.2 Schema | 12-table Phase-1 schema via Alembic migration; `pg_trgm` + `citext` enabled; `search_tsv` trigger (title+company+summary+description, weighted) |
| 1.3 Adapter | `SourceAdapter` Protocol + `GreenhouseAdapter`, parameterized by board token; 12 real companies seeded |
| 1.4 Pipeline | `normalize.py` + `dedup.py` + `ingest.py` — raw→canonical with full provenance, idempotent |
| 1.5 Runner + cron | `crawlers/runner.py` + `.github/workflows/crawl-tier1.yml` (2h schedule) |
| 1.6 Read API | `GET /feed`, `GET /search`, `GET /opportunity/{slug}`, `POST/DELETE/GET /bookmarks` (FastAPI) |
| 1.7 Frontend | Next.js feed/search, SSR opportunity detail pages, auth UI, bookmark toggle |
| (new) CI | `.github/workflows/ci.yml` — backend ruff+black+pytest, frontend eslint+tsc+build |

**6 commits since the original Phase-1 schema work**, all authored solely as `sohan1611` per the standing git-attribution rule — no co-author trailers, no Dependabot.

---

## 2. Gate evidence (PHASE-1-HANDOFF.md §8, verified just now, not assumed)

1. **Real deduplicated opportunities with provenance**: 2,348 total opportunities in the live dev DB, **100% with ≥1 `opportunity_sources` row** (verified by direct query).
2. **Dedup + idempotency**: `test_ingest.py` (6 tests) + `test_runner_isolation.py` (1 test) pass, including same-job-two-sources merge, full-rerun-zero-dupes, distinct-roles-do-not-merge, same-title-different-location-does-not-merge (the GitLab false-merge regression).
3. **Change detection**: verified locally in Step 7 (`new_opps=0` on an unchanged board's second crawl) and structurally via 4 fingerprint unit tests (`test_runner.py`).
4. **Crawling on GitHub Actions, writing `crawl_runs`**: confirmed live — `crawl_runs` shows **26 success, 5 failed** (the failures are explained history: missing secret before it was set, then two timeout failures before the connection-robustness fixes landed; all now resolved, see §5). Nothing crawls on the Render dyon — confirmed: no Playwright dependency exists anywhere (`grep` across `pyproject.toml`/`uv.lock` returns nothing), and the crawler is only ever invoked via `crawlers.runner`, never imported by `api/`.
5. **Read path fast and AI-free**: p50 165–200ms across `/feed`, `/search`, `/opportunity/{slug}` (n=80 samples). p95 215–380ms depending on endpoint — see §5 for the honest caveat on this number.
6. **Stranger flow**: live-verified end-to-end —
   - SSR meta tags confirmed via `curl` + grep on real opportunity pages (`<title>`, `<meta name="description">`, `<meta property="og:title">` all render server-side with real crawled data)
   - Outbound `apply_url` confirmed pointing at the real source (e.g. `stripe.com/jobs/...`), never Aspirova
   - Real sign-up → sign-in → bookmark add/list/remove → invalid-token-rejected, all tested against a real (since-deleted) Supabase Auth user, not mocked
7. **Cost**: see §6 — currently **$0** because nothing is deployed yet (all verification has been local + GitHub Actions, both free). Projected cost once deployed matches the ~$7–10/mo target (Render $7 + domain; Supabase/Vercel/GH Actions free tier).

---

## 3. Deviations from canon (amendment requests for the architect)

1. **`crawl_jobs` (SKIP LOCKED queue) intentionally unused.** `run_tier()` iterates sources/companies directly rather than claiming work from the queue table. At 12 companies and one adapter, a sequential pass is fast enough that building parallel-claim infrastructure now would be scaling for anticipated load, not measured load (Doc 02 §5's own binding rule). `crawl_jobs` remains in the schema, unused, until company count actually justifies it.
2. **Dedup similarity threshold raised from the originally-planned 0.5 to 0.6, then re-derived empirically to a much sharper standard** (see §4 bug #1) — title-only trigram similarity needed real-data calibration the doc couldn't have specified in advance.
3. **`statement_timeout` via `options` connection parameter does not work through the Supabase Session Pooler** — confirmed empirically (set via `options="-c statement_timeout=..."` had zero effect; switching to an explicit `SET` after connecting works correctly). Worth noting in Doc 04/08 if any future adapter or script assumes startup-parameter options are honored by the pooler.

None of these contradict canon outright — flagging them so the architect can decide whether any should be promoted into the docs themselves.

---

## 4. Real bugs found and fixed (all via live testing, not theoretical review)

Six, in the order discovered:

1. **Category-classification false positive** (`classify_category`): naive substring match tagged "**Intern**al Audit Lead" and "**Intern**ational Strategic Finance" as internships. Fixed with word-boundary regex; regression-tested against both real titles.
2. **Double-encoded HTML** in Greenhouse's `content` field (literal `&lt;div&gt;` text, not real markup). Fixed with `html.unescape()` before parsing; verified against a real Cloudflare payload.
3. **Dedup false-merge**: GitLab's real board posts "Senior Solutions Architect" as 10 genuinely distinct openings (Germany/US-West/India/UAE/etc.), each with a different apply URL. Title-only trigram similarity collapsed all 10 into one canonical opportunity. Root cause went deeper than the first fix (location agreement) — measuring real false-merge pairs against real true-duplicate pairs showed overlapping score ranges; the threshold was raised to 0.90, which cleanly separates confirmed false merges (max 0.848) from confirmed real duplicates (min 0.930) in the actual data.
4. **Pagination instability**: `/feed`/`/search` sorted only by columns that tie across many rows (same crawl batch's `last_seen_at`, or rank-0 ties). Postgres gives no ordering guarantee among tied rows across separate paginated queries — confirmed live, page 1 and page 2 returned overlapping opportunities. Fixed with `id` as a secondary sort key everywhere pagination exists.
5. **Cascading per-listing failures** (the connection-robustness investigation): a live GitHub Actions run showed two boards with implausible error counts (262/483, 129/217). Root cause: the per-listing exception handler never rolled back, and Postgres aborts the *entire* transaction after any failed statement — one real failure cascaded into hundreds of fake ones. Fixed by committing per listing and rolling back on failure; regression-tested by forcing a real DB-level failure on one listing out of three and confirming the other two survive, then confirmed the test actually catches the bug by reverting the fix and watching it fail with the exact same `SAWarning` seen in production logs.
6. **Per-listing commits were correct but far too slow** (discovered by re-triggering the crawl after fix #5): one 484-listing company alone consumed most of a 25-minute job — round-trip *count*, not server processing time, dominates on this network path, and committing every single listing maximizes round-trips. The run got through only 3 of 12 companies before being cancelled, meaning the other 9 would silently never crawl that cycle. Fixed by batching commits every 25 listings — a failure now rolls back its whole batch (not just itself, not the whole company), an accepted self-healing tradeoff since ingest is idempotent and anything lost reprocesses on the next 2-hour cycle. This also surfaced a quieter accounting bug: `new_opps` was counted optimistically before its batch committed, so a later failure in the same uncommitted batch would silently overcount. Regression-tested both directions: a failure must not cascade past its own batch (3-listing case), and — the test that actually matters at production scale — a later batch's failure must not roll back an earlier *already-committed* batch (27-listing case spanning the 25-listing threshold).

---

## 5. The connection-robustness investigation (full honesty, not a one-line mention)

The first live GitHub Actions crawl hung for the full 15-minute job timeout, twice. Diagnosis, each step verified directly rather than assumed:

- `connect_timeout` alone did not fix it — confirmed by testing against a deliberately unreachable address (failed in exactly the configured time), proving the *mechanism* worked, meaning the hang was happening *after* a successful connection, not during the handshake.
- Added TCP keepalives (detects a connection that goes silently dead post-connect — common behind NAT/stateful firewalls on cloud CI networks) and a server-side `statement_timeout` (caps any single query). The `options` connection-parameter approach to `statement_timeout` silently did nothing (almost certainly filtered by the Supabase pooler); switched to an explicit `SET` after connecting, confirmed working by killing a real `pg_sleep(30)` at exactly 20.1s.
- This combination got a crawl to *complete* (18m36s) but exposed the cascading-failure bug (§4 #5) underneath.
- Fixing #5 (per-listing commits) then exposed #6 (per-listing commits are correct but too slow) — three layered problems that each had to be found by actually running on real infrastructure, not any one of which was visible from local testing or code review alone.
- Also discovered Python block-buffers stdout when piped (always, in CI) — every company's result was appearing in one burst near the end of the run instead of incrementally, making real-but-slow progress look identical to a silent hang during debugging. Fixed with `PYTHONUNBUFFERED=1`.

**Honest residual uncertainty**: the *exact* root cause of the GH-Actions-to-Supabase-pooler latency/instability itself (vs. local) is not fully explained — likely network distance/variance (GitHub's US-based runners to a Mumbai pooler) compounded by Supabase free-tier pooler characteristics, but not root-caused to a single definitive mechanism. The system is now resilient *to* it (bounded timeouts, no cascading, batched round-trips, per-company isolation), which is the actually-achievable goal — full elimination of cross-continent network variance is not.

**VERIFICATION RUN — CONFIRMED (2026-06-30):** run 28420810872, with all fixes (§4 #5 and #6) in place, **completed successfully: 12m45s, all 12 companies `status: success`, ~2,321 listings scanned, 36 new opportunities, 2 errors total** (DB now holds 2,409 opportunities, 100% with provenance). The investigation is closed: the crawler reliably completes on GitHub Actions. One caveat remains open: **12m45s is latency-bound and uncomfortably near the 25-min timeout** — Phase 2's added sources (Lever/Ashby/aggregator, 3–5× the company count) *will* exceed it, so the set-based bulk-operation refactor (Topology ADR "Lever 1") is required before that scaling. The second caveat — 2 `opportunities_slug_key` collisions — **is now fixed and regression-tested** (see §4a below).

**p95 latency caveat carried over from Step 8**: resolved — see §6, real production p95 is now measured.

---

## 4a. Bug found and fixed after this report's original close (2026-06-30, same day, Sonnet)

**`opportunities_slug_key` collision** (the 2 errors noted above): root cause traced precisely - when a previously-ingested listing's content changes (e.g. its location is edited) but the title doesn't, the deterministic slug stays byte-identical to the existing opportunity's, while the old code's exact-location dedup filter correctly refused to self-match the changed listing and tried to `INSERT` a duplicate. Fixed in `pipeline/ingest.py` with an identity fast-path (re-link via the `(source_id, external_id)` link on `raw_listings` instead of re-running dedup) plus a slug-lookup safety net for the rarer case where `raw_listings` has been pruned but the opportunity persists. Verified both regression tests actually catch the bug: reverted the fix, confirmed both failed reproducing the exact production `IntegrityError`, restored the fix, confirmed both pass. Full suite: 54/54 passing. Commit `51ce4e8`.

---

## 6. Render + Vercel deployment — EXECUTED (2026-06-30)

Per the architect's [Topology & Deploy ADR](TOPOLOGY-AND-DEPLOY-DECISION.md): deploy now, minimal and reversible, sole purpose = measure real production read-path p95. Done:

- **Backend live on Render**: `https://aspirova-api.onrender.com`, region Singapore (no Mumbai region exists on Render), Starter plan ($7/mo). Deployed via committed `render.yaml` Blueprint (commit `1bab3f0`). `/health` confirms `env: production`, reading Render's dashboard env vars correctly (not a local `.env`).
- **Functional verification**: `/feed`, `/search`, `/opportunity/{slug}` all return real data from the live Supabase Mumbai DB through Render-Singapore — confirms the cross-region DB connection works correctly in production, not just locally/from GitHub Actions.
- **Frontend live on Vercel**: `https://aspirova.vercel.app`, Hobby (free) tier, deployed via Vercel's Git import (monorepo root directory set to `frontend`). `NEXT_PUBLIC_*` env vars set on the Production+Preview scope before the first build, avoiding a wasted broken deploy. SSR confirmed working against the live backend: real `<title>`/meta description/og:title per opportunity, real opportunity count (2,423) rendered server-side, real apply links pointing at the actual source (e.g. GitLab's Greenhouse board), not Aspirova.
- **CORS fixed**: `CORS_ORIGINS` on Render updated to include `https://aspirova.vercel.app` (was still `http://localhost:3000` immediately after the backend deploy, which would have silently blocked every client-side browser request - e.g. the bookmark button - while server-side SSR fetches kept working fine, since CORS is a browser-only mechanism). Verified via a CORS preflight check: `access-control-allow-origin` was absent before the fix (confirmed the real block, not assumed) and present after.
- **Full production auth + bookmark flow verified live** (not just locally): created a real confirmed Supabase Auth user via the Admin API, signed in for a real session token, and ran the complete cycle against `aspirova-api.onrender.com` - `GET /bookmarks` (empty) → `POST /bookmarks/{slug}` (204) → `GET /bookmarks` (shows it) → `DELETE /bookmarks/{slug}` (204) → `GET /bookmarks` (empty again) → invalid token correctly rejected (401) → test user cleaned up. This closes the Phase-1 "stranger can search→open→sign up→bookmark" acceptance criterion against the actual deployed stack, not a local approximation of it.

### Real production p95 — the number that decides Lever 2

Measured against the live `aspirova-api.onrender.com`, n=30 per endpoint, with a connection-reusing client (a first pass using a fresh `curl` process per request measured p50 ~530-558ms / p95 ~590-748ms — discarded as a methodology artifact: each fresh process pays its own TLS handshake to Render, which isn't what we want to measure; re-run with a persistent `httpx.Client` to isolate that out):

| Endpoint | p50 | p95 | max |
|---|---:|---:|---:|
| `/feed` (no filters) | 357ms | 388ms | 478ms |
| `/feed` (category filter) | 320ms | 370ms | 373ms |
| `/search` (FTS) | 330ms | 380ms | 501ms |
| `/opportunity/{slug}` | 335ms | 361ms | 362ms |

**Verdict: p95 sits at 361-388ms across all four endpoints — modestly over the 300ms target (roughly 20-30% over), and roughly 2x the local-machine-direct-to-Supabase numbers from Step 8 (p50 165-200ms).** Not catastrophic, but a consistent, real signal in the same direction across every endpoint, not an outlier.

**Honest methodology caveat**: this measurement is from the testing machine, through the public internet, to Render-Singapore, to Supabase-Mumbai, and back - it is *not* an isolated measurement of just the Render→Supabase hop (that would require server-side instrumentation, e.g. timing the DB round-trip inside the request handler and returning it separately, which was not built here to keep this deploy minimal per the ADR). The testing machine's own network position adds unknown overhead on top of the Render→Supabase leg specifically. That said, this end-to-end number is arguably *more* representative of real user experience than an isolated DB-hop number would be, since a real user's request also has to travel the public internet to reach Render in the first place.

**This leans toward, but does not conclusively prove,** the case for Lever 2 (Singapore region consolidation: Supabase `ap-southeast-1` + Render Singapore) being worth pursuing - p95 is over target, consistently, but not by a wide margin, and the measurement isn't fully isolated to the hop that consolidation would actually fix. Recommend the architect treat this as suggestive evidence to weigh, not a binding trigger on its own - a cleaner server-side-instrumented measurement would sharpen the call if the decision is close.

---

## 7. HARD RULES self-check (Doc 08 §3)

- [x] No crawler/Playwright code path runs on the Render web dyno (Render runs only `api.main:app`, per `render.yaml`'s start command; crawler only ever runs via GH Actions or local dev invocation - confirmed live, the deployed Render service has never executed crawler code)
- [x] No Playwright at all in Phase 1 — confirmed via dependency grep
- [x] Outbound `apply_url`/`source_url` stored + displayed; no mirroring — confirmed live on real pages
- [x] One canonical opp per real opportunity; provenance preserved; writes idempotent — confirmed via tests + live data (2,348/2,348 with provenance)
- [x] Migrations are the schema contract — single Alembic migration, no manual schema changes
- [x] No secrets in code — verified via `git diff` review before every commit this session; `.env`/`.env.local` correctly gitignored throughout (one near-miss caught and fixed: a real password briefly landed in `.env.example`, fixed before it was ever pushed)
- [x] Adapter logic lives behind the `SourceAdapter` seam — `GreenhouseAdapter` implements the Protocol; runner code never touches Greenhouse specifics directly

---

## 8. Cost/perf check vs. budget

| Budget item | Target | Actual |
|---|---|---|
| Infra | ~$7–10/mo | **$7/mo** (Render Starter; Vercel Hobby + Supabase free + GH Actions free = $0) — on target |
| Read path p95 | <300ms | **361–388ms live production** (§6) — modestly over target, see Lever-2 discussion |
| AI on hot path | none | none — confirmed, no AI code exists yet (Phase 3 concern) |

---

## 9. Test suite summary

**52 backend tests passing** (ruff + black clean): unit (adapter, fingerprint, models structure — no DB/network), integration (ingest/dedup, full API, runner cascading-fix + batching-fix — real dev DB), auth-rejection-path (no real Supabase session needed). Frontend: lint + typecheck + production build clean, manually verified against real backend + real data (no automated frontend test framework — deliberately out of Phase-1 scope, manual/curl verification matches what the handoff's literal acceptance criteria call for).

CI (`ci.yml`) now runs all of this automatically on every push to master and every PR.

---

## 10. Notes for the architect / next phase

- The connection-robustness work (§5) and per-listing isolation fix (§4 #5) are genuinely Phase-2-relevant: Phase 2 adds more sources (Lever, Ashby, an aggregator) and dream-company alerts, both of which will exercise the same DB connection under higher load. The fixes here should hold, but worth re-confirming once Lever/Ashby adapters exist.
- The dedup threshold (0.90) was calibrated against Greenhouse data specifically (title-string conventions vary by ATS). Worth re-validating once Lever/Ashby data exists rather than assuming the same threshold transfers.
- Schema hooks Doc 03/06 call for ahead-of-need (`org_id`/license, `sponsored` flag) are still not in the schema — correctly deferred per Phase 2/4 timing, not an oversight.
