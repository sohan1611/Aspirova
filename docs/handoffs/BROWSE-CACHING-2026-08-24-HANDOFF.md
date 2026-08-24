# Browse-Page Render Cost (2026-08-24) — Architecture Handoff

*Architect: Claude Opus. Engineer: whoever is dispatched (Codex or Sonnet).
Dispatch ONE part at a time; each part is independently shippable and independently
verifiable.*

> **Naming note.** This is deliberately NOT called "Phase 6". `PHASE-5-HANDOFF.md`
> (2026-07-11, Cream Layer + Competitions) already owns the numbered sequence, and
> recent work has used topical/dated handoffs (`SOURCES-EXPANSION-HANDOFF.md`,
> `AUDIT-2026-08-18-FIXES-HANDOFF.md`). This follows that convention.

---

## Status — Parts A and B BUILT and verified (2026-08-24)

`/jobs`, `/internships`, `/remote` are now ISR; the revalidation push covers list paths.
`/competitions` and the homepage remain `ƒ` and are **out of scope** — see the corrected
scope table in §3.

Build output, against the production API:

| Route | Before | After |
|---|---|---|
| `/jobs`, `/internships`, `/remote` | `ƒ` | `○` — **Revalidate 6h** |
| `/jobs/page/[n]`, `/internships/page/[n]`, `/remote/page/[n]` | — | `●` (SSG) |

Corroborated in `.next/prerender-manifest.json`: all three `[n]` routes appear under
`dynamicRoutes` (the field that stayed **empty** when this was misconfigured in 2026-08-03),
and the three base routes carry `initialRevalidateSeconds: 21600`.

**A third gotcha found while building, beyond the two in §3.** `getFeed` fetched with
`next: { revalidate: 300 }`, and a fetch's revalidate **caps its route's ISR window** — the
trap already documented on `getOpportunity` in `lib/api.ts`. The pages would have declared
6 h and silently regenerated every 5 minutes anyway. `getFeed` now takes a
`revalidateSeconds` argument that the landing pages pass. The build's Revalidate column is
the proof: these routes read `6h` while `/pricing`, still on a 300 s fetch, reads `5m`.

SEO verified on the prerendered HTML (the Binding row in §2): `/jobs` is 245 KB of real
markup with real `/opportunity/...` links, path-based `/jobs/page/2` pagination, zero
leftover `?page=` links, and `rel="next"`. Pagination correctness re-verified against live
data: **zero overlap** between page 1 and page 2, with page 1 matching the prerendered HTML.

**Not exercised in a browser:** the `page <= 1` redirect and the out-of-range `notFound()`.
Both are copied verbatim from the working `companies/[slug]/page/[n]` route, but neither was
hit against a running server — the local launcher could not start one with the production
API reachable. Worth a click-through after deploy.

---

## 0. Why this phase exists (the problem, evidence-backed)

**The Vercel Fluid Active CPU budget (4 h/mo, free tier) is exhausted — `aspirova`
measured at 99.2%.** The cause is not the crawler and not the backend. It is that the
five highest-traffic browse pages cannot be cached, so **every single visit pays a full
server render**.

Measured 2026-08-24 by reading every `page.tsx` in `frontend/app`:

| Page | Mode | Cacheable? |
|---|---|---|
| `app/(feed)/page.tsx` (homepage) | reads `searchParams`, no `revalidate` | **No** |
| `app/jobs/page.tsx` | `export const dynamic = "force-dynamic"` | **No** |
| `app/internships/page.tsx` | `export const dynamic = "force-dynamic"` | **No** |
| `app/competitions/page.tsx` | `export const dynamic = "force-dynamic"` | **No** |
| `app/remote/page.tsx` | `export const dynamic = "force-dynamic"` | **No** |

**The contrast that proves the fix works.** Detail pages (`opportunity/[slug]`,
`companies/[slug]`, `programme/[slug]`) use `revalidate = 604800` **plus** the crawler's
push webhook (`backend/pipeline/revalidate.py` → `frontend/app/api/revalidate/route.ts`).
They cost effectively nothing. The push infrastructure already exists and is already wired
into `crawl-tier1.yml` — it simply only ever calls `revalidatePath('/opportunity/{slug}')`
and never touches a list page.

**Two supporting observations from production logs (2026-08-23 16:00 → 2026-08-24 16:00):**

1. The API sees `GET /feed?kind=roles&page=1&limit=30` roughly every 5–7 minutes. That is
   the **data** cache (`lib/api.ts:175`, `next: { revalidate: 300 }`) doing its job — the
   page re-renders per visit, but the upstream fetch is deduped for 300 s. So Render is
   already protected; **Vercel is the side paying per visit.**
2. `force-dynamic` carries **no explanatory comment** on any of the four files. There is no
   canon row requiring it. It reads as a blanket safety default, not a reasoned decision.

---

## 1. Goals / non-goals

**Goals**
- Make the five browse pages cacheable **without losing server-rendered HTML**.
- Keep the crawler's existing push webhook as the freshness mechanism, extended to lists.
- Cut browse-page renders from *per visit* to *per revalidation window + per crawl push*.

**Non-goals (explicitly out of scope — do not do these)**
- **Do NOT move filtering or rendering client-side.** See §2 — this would contradict a
  Binding canon row.
- **Do NOT touch the feed SQL.** See §5 — measured, and deprioritized on evidence.
- No AI, no new data sources, no schema changes.

---

## 2. The Binding constraint this design must honor

`docs/README.md`, decision log, **2026-07-07 — Binding**:

> Phase 4 Part 1 (SEO content engine) complete … long-tail **SSR** landing pages
> (`/internships`, `/remote`, `/jobs`, `/companies/[slug]`) … `JobPosting` JSON-LD +
> dynamic `sitemap.xml`/`robots.txt`

These pages exist **to be crawled by search engines**. Any design that ships an empty shell
and fetches results in the browser breaks that row and requires an architect amendment.

**This design does not touch it.** ISR still renders on the server and still emits complete
HTML including JSON-LD. The only thing that changes is *how often* that render happens —
once per revalidation window instead of once per visitor. SEO output is byte-identical.

---

## 3. Part A — Route-segment pagination + ISR on the browse pages

### The blocker, stated precisely

A Next.js page that `await`s `searchParams` **can never be statically rendered**, because
search params are per-request. Adding `export const revalidate` to a page that reads
`searchParams` does nothing. This is why `force-dynamic` was reachable as a "fix" in the
first place — with `?page=N` in the query string, there was no cacheable shape available.

**Corrected during implementation (2026-08-24).** The claim "`searchParams` carries only
`page`" holds for **three** of the five pages, not all five:

| Page | `searchParams` | Verdict |
|---|---|---|
| `/jobs`, `/internships`, `/remote` | only `page` | **fixed** — route segment + ISR |
| `/competitions` | `sort`, `scope`, `country`, `remote`, `page` | filters are intrinsic |
| `(feed)` homepage | 12+ (`q`, `category`, `kind`, `source`, `location`, `company`, …) | it is a search UI |

The three clean pages are exactly the long-tail SEO landing pages the 2026-07-07 Binding row
protects, so they are also the ones where caching matters most for crawl budget. The other
two are genuinely filter-driven surfaces; making them cacheable is a separate UX question
(what the canonical unfiltered view is, and whether filtering becomes client-side), **not**
something to force through under this phase. They remain `ƒ` and are out of scope here.

### The pattern — already proven in this repo

`app/companies/[slug]/page/[n]/page.tsx` already solves exactly this problem:
pagination lives in the **route segment**, and the page carries `revalidate = 604800` with
`generateStaticParams`. Mirror it.

```
/jobs               → page 1, ISR                 (canonical, unchanged URL)
/jobs/page/[n]      → page n, ISR, prerendered    (new route segment)
```

Apply the same shape to `/internships`, `/remote`, `/competitions`, and the homepage.

### Required implementation notes

1. **`generateStaticParams` is mandatory, even when it returns `[]`.**
   On Next 16, `export const revalidate` on a dynamic segment is **silently ignored**
   unless `generateStaticParams` is also exported. This has already bitten this project
   once. Returning `[]` is legal and means "prerender nothing up front, ISR on demand" —
   but the export must be present.
2. **Return `[]` from `generateStaticParams`, prerendering nothing.** *(Revised during
   implementation — this supersedes the earlier "~10 pages" recommendation.)* The existing
   `companies/[slug]/page/[n]` route already made this call deliberately: `[]` still
   registers the route for on-demand ISR, costs no build minutes, and avoids building a
   static mirror of the corpus for the bot in §5. Prerendering a page range buys nothing
   that on-demand ISR does not already give on first request.
3. **Delete `export const dynamic = "force-dynamic"`** from all four landing pages — but
   **only as part of the route-segment change above, never on its own.** Removing it alone
   was tested and disproved on 2026-08-03: the route stays `ƒ` because `await searchParams`
   already forces per-request rendering. It is a no-op that looks like a cost fix. The
   `searchParams` removal is what does the work; deleting `force-dynamic` merely stops
   overriding the result.
4. **Keep `alternates.canonical`** pointing at the unfiltered path. Add `rel="prev"/"next"`
   for the paginated segments — this is a genuine SEO *improvement*: real crawlable paths
   instead of query strings.
5. **Pick a revalidate window matched to the data.** The crawler runs `0 1 * * *` — **once
   per day**. Anything under an hour is waste. Recommend `revalidate = 21600` (6 h) as a
   safety net, with the push in Part B providing actual freshness.

**Acceptance:** `next build` output shows these routes as `●` (SSG/ISR) rather than `ƒ`
(Dynamic).

---

## 4. Part B — Extend the revalidation push to list pages

`frontend/app/api/revalidate/route.ts` currently accepts `{slugs: [...]}` and calls
`revalidatePath('/opportunity/{slug}')` for each. It never revalidates a list page, which is
*why* the browse pages need a short polling window at all.

**Change:** accept an optional second field (e.g. `{"paths": ["/jobs", "/internships", ...]}`)
validated against a **server-side allowlist of known list paths**. Do not interpolate
caller-supplied strings into `revalidatePath` — the existing `SLUG_PATTERN` guard exists for
exactly this reason, and the same care applies here.

**Backend:** `backend/pipeline/revalidate.py` already batches, authenticates with a bearer
token, and **fails open** (a revalidation failure must never fail a crawl). Extend it to send
the list paths once per crawl. Preserve the fail-open property exactly.

**Net effect:** browse pages become fresh within seconds of a crawl finishing, while
rendering ~4×/day instead of once per visitor.

---

## 5. What was already measured and REJECTED — do not redo this

Recorded so nobody burns a cycle re-deriving it.

**The `/feed` query is slow, and that is fine.** A live `EXPLAIN (ANALYZE, BUFFERS)` of the
real production query (2026-08-24) showed **348 ms** execution. The cost is structural:
`source_rank` is a `row_number() OVER (PARTITION BY primary_source …)` that the outer
`ORDER BY` depends on, so Postgres sorts **all 24,885 matching rows** to return 20, spilling
5.8 MB to disk via external merge. No index can serve a computed window rank.

Three findings against acting on it:

1. **Raising `work_mem` makes it SLOWER.** Measured: baseline 329 ms (spills to disk) vs
   `work_mem=32MB` 365 ms (no spill) vs `64MB` 352 ms. The external merge hits OS page
   cache; an in-memory sort of 25 k wide rows is not cheaper. **Do not "fix" the disk spill.**
2. **Removing `count(*) OVER ()` saves ~34 ms (~10%)**, median over n=20, tight variance.
   Real, but it costs the `total` field that drives pagination, and see (3) for who benefits.
3. **Deep-page traffic is a bot, not users.** In the logs the deep pages increment
   sequentially — `category=job page=312→313`, `remote=true page=319→320`,
   `kind=roles page=334→335` — about one page per hour each. Real users hit `page=1`, which
   is cache-served at 0 ms DB time. **Optimizing deep pagination would mainly speed up a
   scraper.**

Consequence for Part A: prerender a bounded page range. Prerendering all ~330 pages would
build the scraper a free static mirror of the corpus.

---

## 6. Build order

Each part = one work-order → implement → verify against production → branch + PR.

- **A.1** `/jobs` only — route segment + ISR + `generateStaticParams`. Smallest possible
  proof. Verify the build output flips `ƒ` → `●` before touching the other pages.
- **A.2** `/internships`, `/remote`, `/competitions` — same shape.
- **A.3** Homepage `app/(feed)/page.tsx` — same shape; most care needed, highest traffic.
- **B.1** Revalidate route: allowlisted `paths` support.
- **B.2** Crawler: push list paths once per crawl, fail-open preserved.

---

## 7. Verification — this is the merge gate (Doc 08 §3; 2026-08-17 Binding)

**Green tests are NOT evidence.** Every part must be exercised against real production data
or a real rendered DOM.

0. **Do NOT verify on a Vercel preview deployment.** Preview deploys sit behind deployment
   protection and return `no-store` regardless of configuration, so they cannot test
   caching and will produce a false negative. This was established 2026-08-03.
1. **`next build` output** — the changed routes must show `●` not `ƒ`. Paste the table.
   Corroborate against `.next/prerender-manifest.json`: the route must appear under
   `dynamicRoutes`. An empty `dynamicRoutes` means ISR was silently not registered,
   regardless of what `revalidate` says in the source.
1b. **On production, confirm `X-Vercel-Cache: HIT` and `Cache-Control: public`** for the
   changed routes. A `MISS` with `private, no-cache, no-store` means the route is still
   rendering per request and the change did not land.
2. **`curl` the deployed page and grep the HTML** for the JSON-LD block and real listing
   titles. This is the proof SEO did not regress. An empty shell fails the gate.
3. **Vercel CPU** — record Fluid Active CPU before, and again ≥24 h after. The number must
   fall. This is the whole point of the phase; if it does not move, the phase failed.
4. **Freshness** — after a crawl, confirm a newly ingested opportunity appears on `/jobs`
   without waiting out the 6 h window (proves Part B).
5. **Pagination correctness** — `/jobs/page/2` must not overlap `/jobs`. Note that the feed
   query's `id` tie-breaker exists precisely because ties across paginated queries produced
   overlapping rows in production before. Re-verify it live.

---

## 8. Founder decisions needed

1. **Revalidate window.** Recommend 6 h + crawl push. Confirm, or state a freshness
   requirement that needs tighter.
2. **Prerender depth.** Recommend the first ~10 pages per landing page. Deeper prerendering
   mainly serves the scraper (§5).
3. **The scraper itself.** Something is walking the corpus one page per hour. Out of scope
   here — but flagging it: it is the only consumer of deep pagination, and it is consuming
   real Render and Supabase budget. Decide separately whether to rate-limit it.

---

## 9. Decision-log entries to append to docs/README.md (on approval)

| Date | Entry | Status |
|---|---|---|
| 2026-08-24 | **Browse pages were uncacheable, and that — not the crawler or the feed SQL — was the Vercel CPU exhaustion (99.2% of the 4 h/mo free tier).** Five pages (homepage, `/jobs`, `/internships`, `/competitions`, `/remote`) were `force-dynamic` or `searchParams`-dynamic, so every visit paid a full server render; `force-dynamic` carried no comment and no canon row, i.e. it was a blanket default, not a decision. **Ruling:** pagination moves from `?page=N` into a route segment (`/jobs/page/[n]`), mirroring the already-proven `companies/[slug]/page/[n]` pattern, so the pages become ISR. **This preserves the 2026-07-07 Binding SSR/SEO row byte-for-byte** — rendering stays on the server and JSON-LD is unchanged; only render *frequency* changes. `generateStaticParams` must be exported alongside `revalidate` (even returning `[]`) or Next 16 silently ignores ISR. | **Binding** |
| 2026-08-24 | **The `/feed` query's 348 ms is structural and was deliberately NOT optimized.** `source_rank` (`row_number() OVER (PARTITION BY primary_source …)`) forces a sort of all 24,885 matching rows to return 20. Measured and rejected: raising `work_mem` made it **slower** (365 ms vs 329 ms) despite removing the 5.8 MB disk spill; removing `count(*) OVER ()` saves ~34 ms (n=20) but costs the `total` field. **Deciding evidence:** deep-page traffic is a bot walking the corpus sequentially (~1 page/hour: `page=312→313`, `319→320`, `334→335`), while real users hit `page=1` at 0 ms cache-served. Optimizing deep pagination would mainly speed up a scraper. Consequence: prerender only a bounded page range. | **Binding** |
