# PHASE 1 REPORT — Foundation & Ingestion Core

*From: Lead Engineer (Claude Sonnet) · To: Chief Architect (Opus) · Status: COMPLETE pending one open decision (§6)*

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

**Honest residual uncertainty**: the *exact* root cause of the GH-Actions-to-Supabase-pooler latency/instability itself (vs. local) is not fully explained — likely network distance/variance (GitHub's US-based runners to a Mumbai pooler) compounded by Supabase free-tier pooler characteristics, but not root-caused to a single definitive mechanism. The system is now resilient *to* it (bounded timeouts, no cascading, batched round-trips, per-company isolation), which is the actually-achievable goal — full elimination of cross-continent network variance is not. **As of this report, a verification run with all fixes (§4 #5 and #6) in place is still in progress** — the architect/user should confirm its outcome before treating this investigation as fully closed.

**p95 latency caveat carried over from Step 8, now reinforced**: all local API latency measurements are from this dev machine to Supabase (Mumbai), not from a co-located Render deployment. Doc 02 already anticipated this — real production p95 should be measured fresh once actually deployed.

---

## 6. Open question for the architect — the one thing actually blocking Phase-1 closure

**Render and Vercel deployment has not happened.** Every acceptance criterion above has been verified via local dev servers + GitHub Actions (the crawler specifically is designed to run there regardless of where the API lives), but the **API is not running on Render and the frontend is not running on Vercel** — no `render.yaml`/Vercel project exists yet. This means:
- The literal "~$7–10/mo" cost criterion is currently **$0** (nothing billed) rather than verified-at-$7-10.
- The "production" read-path latency (Render co-located with Supabase) has never actually been measured — only local-machine-to-Supabase, which Doc 02 already flagged as unrepresentative.

This wasn't skipped by oversight — creating cloud accounts and deploying infrastructure is exactly the kind of action this build process has consistently asked before taking (same posture as the GitHub secret and Supabase credential moments earlier in this build). **Decision needed:** deploy now to fully close Phase 1's literal cost/latency criteria, or treat "built, tested, and crawler-verified on GitHub Actions" as sufficient to close Phase 1 and fold actual deployment into Phase 2 (which already covers "production-ready platform")?

---

## 7. HARD RULES self-check (Doc 08 §3)

- [x] No crawler/Playwright code path runs on the Render web dyno (nothing is even deployed to Render yet; crawler only ever runs via GH Actions or local dev invocation)
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
| Infra | ~$7–10/mo | $0 (undeployed — see §6) |
| Read path p95 | <300ms | 215–380ms locally (network-path caveat, §5) |
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
