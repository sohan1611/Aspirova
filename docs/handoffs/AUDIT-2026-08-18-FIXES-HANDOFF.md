# Audit Fixes (2026-08-18) — Architecture Handoff

*Architect: Claude Opus. Engineer: Claude Sonnet. Codex quota is exhausted, so Sonnet
implements directly. Dispatch ONE phase at a time; each phase is independently shippable,
independently verifiable, and ends on its own branch + PR.*

---

## 0. Ground rules that apply to EVERY phase

These are Binding (doc 08 §3 + the 2026-08-18 canon rows). Violating one fails the phase.

1. **Strict verification is the merge gate. Green tests are NOT evidence.** Every phase must
   be exercised against **real production data or a real rendered DOM**, and the real output
   pasted into the phase report.
2. **The honesty rule.** Nothing may be presented as live/apply-now unless it genuinely is.
   No date-based inference of openness. No code path may invent an "open" status.
3. **Never infer country from platform.** ("Unstop is Indian so assume India" is forbidden.)
4. **Frontend caching:** never add `cache: "no-store"` or `force-dynamic` to public pages.
   Use `next: { revalidate }`. Next 16 needs `generateStaticParams` (even `[]`) alongside
   `revalidate` or ISR is silently ignored.
5. **Supabase egress discipline.** Do NOT run the full pytest suite against production. Run
   targeted tests with `--basetemp=../.pytest-tmp` (REQUIRED on this machine). Do not leave
   a local backend running.
6. **Do not run local scripts against prod while a crawl is running** (pooler-slot contention
   caused a 24-minute hang in July).
7. **Git:** branch per phase. Commit as `sohan1611 <sohanmandal1611@gmail.com>`.
   **NEVER** add a `Co-Authored-By` trailer or any final line shaped like a git trailer. Only
   `sohan1611` may appear as a contributor. Never commit `.venv/`, `node_modules/`, or any
   `.env*`.
8. **Green before PR:** backend `uv run ruff check .`, `uv run black --check .`, pytest;
   frontend `pnpm lint` and `pnpm tsc --noEmit`.
9. If you believe a spec item is wrong, **stop and say so** rather than implementing something
   else. An earlier work order in this project was cancelled mid-flight because it was about
   to relabel a real failure as healthy. Being right matters more than being done.

---

## Phase 1 — Ship the rate-limit fix that is already built

**Status: the code is written, committed, pushed and green. It is NOT merged. No new code.**

Branch `fix/source-rate-limit-resilience` (2 commits: `0aeaa75`, `497b5ca`) contains:

- a shared bounded HTTP retry helper (honours `Retry-After`, exponential backoff + jitter,
  injectable sleep) used by the new aggregators
- 3.0s request pacing for himalayas
- `terminal_reason` diagnostics for hackerearth / jobicy
- `AGGREGATOR_MIN_RESERVE_SECONDS` 600 to 900

**Why it matters:** himalayas has **never** recorded a successful crawl. While this sits
unmerged it stays that way, and the staleness alarm keeps crying wolf — an alarm people learn
to ignore is exactly how devpost sat 11 days stale.

**Do:**

1. Open a PR from `fix/source-rate-limit-resilience` into `master`. Wait for CI.
2. Merge.
3. Trigger a crawl (`gh workflow run crawl-tier1.yml`).

**Verify (strict):** from the finished run's logs, paste the `COVERAGE:` lines for himalayas
and hackerearth, plus the staleness report.

- **Expect:** `COVERAGE: himalayas` shows a **complete bounded window**, NOT `http_429`.
- **Expect:** the staleness alarm flags **unstop only**. Unstop truncating on budget is
  correct and must keep reporting `partial` — do not "fix" it.
- A run whose only failing step is *"Report crawl source staleness"* is the alarm working as
  designed, not a crash.

**Done when:** himalayas records its first `success` and the alarm is down to unstop alone.

---

## Phase 2 — A stale opportunity must never present itself as live

**This is the founder's "no more casualties" issue. Highest value in this document.**

### The measured defect

`GET /opportunity/{slug}` (`backend/api/opportunity.py:92-97`) looks up **by slug with no
filters at all** — no status check, no staleness check, no closed check.

Verified live, in the rendered DOM:

```
/opportunity/palantir-forward-deployed-software-engineer-bd2b82a9
  posted_at: 2009-12-05   ->  HTTP 200
  page shows: "Apply on Palantir ->"   no date, no warning of any kind
```

The API is already honest: it returns `is_stale: true`. The frontend consumes that flag in
**exactly one place** — `robots: { index: false }`. **Google is protected from this page; the
student is not.** 638 live rows are older than the 10-month rule.

Reachable **only by direct link** — feed, company pages, `/similar` and the sitemap all filter
correctly (verified this audit). So the blast radius is bookmarks, shared links and old emails.

### Task 2A — render the staleness the API already reports (frontend)

In `frontend/app/opportunity/[slug]/page.tsx`, when `opportunity.is_stale` is true:

- show a **prominent banner above the fold**, before the apply affordance, stating plainly
  that the listing is old and very likely closed, and that Aspirova keeps it for reference.
  Include the posted date in the banner.
- **demote the apply CTA.** It must no longer read as a live "Apply on X ->" primary action.
  Keep the link reachable (the student may still want to look) but visibly secondary and
  labelled to say the listing is likely closed.
- do the same for a listing with `closed_at` set, if it does not already say so.

Keep `robots: noindex` exactly as it is.

**Do NOT 404 the page.** Bookmarks and shared links must keep working — we are fixing
dishonesty, not deleting history.

### Task 2B — show the posted date at all

The page currently renders **no posted date anywhere in visible content** (it exists only
inside embedded JSON-LD). A student cannot judge freshness. Render it for every opportunity
that has one.

### Task 2C — close the NULL-date hole (cheap now, do it while it is free)

`is_stale_opportunity()` (`backend/api/filters.py:66`) returns `False` when `posted_at` is
NULL, so **1,729 live rows bypass the 10-month rule entirely**.

Add a fallback: when `posted_at` is NULL, fall back to `first_seen_at` — if we first saw a
listing more than `STALE_AFTER_DAYS` ago and it still has no date, treat it as stale.

**Measured, so you are not flying blind:** today this flips **ZERO rows** — every one of those
1,729 has `first_seen_at` inside the window (earliest 2026-07-11). This is a time-bomb
defuser, not a live fix. **If your measurement disagrees with mine, STOP and report it**
rather than shipping a change that hides thousands of listings.

Mirror the same fallback in the SQL filter `exclude_stale_opportunities()` so the read path
and the detail metadata cannot drift apart. Keep both derived from one definition if you can.

### Verify (strict)

- Backend: targeted pytest for the filter, including a NULL-`posted_at` row with an old
  `first_seen_at`, and one with a recent `first_seen_at`.
- **Before/after row counts from production** for the stale filter, proving the count moved by
  exactly what you predicted (expected: 0 today).
- **Render the real page** for `palantir-forward-deployed-software-engineer-bd2b82a9` after
  deploy and paste the visible text showing the banner, the date, and the demoted CTA.
- Confirm a normal, fresh opportunity page is **visually unchanged**.

**Done when:** that 2009 page can no longer be mistaken for a live opportunity by a human
reading it, and no fresh listing was affected.

---

## Phase 3 — Stop burning Upstash commands on our own traffic

**The Upstash free tier (500k commands/month) is blown: 676k and climbing.**

### The defect

`backend/api/middleware.py` rate-limits `/feed`, `/for-you`, `/search`, `/opportunity/`,
`/company/`, `/companies`, `/facets`, `/trending`, `/programmes`, `/plans` — with **no
exemption for internal callers**. Every Vercel ISR revalidation of a public page is a
first-party request from our own infrastructure, and each one spends Upstash commands. We are
rate-limiting ourselves and paying for the privilege.

### Do

1. **First, measure and report** where the commands actually go, before changing anything.
   Reason from the Vercel ISR revalidate cadence against the routes above, and state the
   estimated split between real users and our own ISR fetches. Do not guess silently — the
   number decides how much this is worth.
2. Add a **shared-secret exemption** for first-party server-side callers: the Next.js server
   sends a header carrying a secret from an env var; the middleware skips the rate-limit
   check when it matches.
   - The secret goes in the backend env and the Vercel env. **Never commit it.**
   - Add it to `backend/.env.example` and `frontend/.env.local.example` as a placeholder.
   - **Fail closed:** if the env var is unset or empty, the exemption must be **disabled**,
     never open. An absent secret must not become a bypass for the whole internet.
   - The header must only ever be trusted server-side. It must be impossible for a browser
     request to claim the exemption — do not read it in any client component, and do not use
     any path that echoes client-supplied headers.
3. Only exempt the **read** endpoints listed above. Never exempt auth, account, bookmarks,
   notifications, or anything that writes.

### Verify (strict)

- A request carrying the correct secret is not counted; a request without it still is.
- **With the env var unset, the exemption is off and normal rate limiting applies** — test
  this explicitly, it is the dangerous case.
- Paste real before/after Upstash command counts, or a measured request-level proof.

**Done when:** ISR traffic no longer consumes the quota, and public rate limiting is provably
unchanged for real users.

---

## Phase 4 — Feed quality: seniority and dead deadlines

### Task 4A — `/trending` must respect seniority

`backend/api/trending.py` applies `exclude_stale_opportunities()` and
`exclude_closed_competitions()` but **not `experience_filters()`**. Measured live: trending is
currently led by *"Staff Machine Learning Engineer, Ads Conversion Core Modeling"* at
Pinterest. A **Staff** role has no business trending on a student platform.

Apply the same early-career filtering the feed uses. Note the trap that cost three rounds last
time: **`student_rank < 2` means *not senior*, and most jobs are not senior — filtering senior
OUT is not the same as filtering student IN.**

**Verify by reading the actual returned titles**, not counts. Paste the top 20 trending titles
before and after. Earlier rounds passed on counts and still shipped "MÜNCHEN - Campervan
Reinigung" and "Campus Recruiter - Dental Hygiene".

### Task 4B — expire past-deadline listings

6 live rows have a deadline in the past, all from unstop. Find out **why the expiry job did not
catch them** (is it category-scoped? source-scoped?), fix the cause, and report the root cause.
Do not just delete the 6 rows — a one-off cleanup that leaves the mechanism broken will
silently refill.

Respect the existing 14-day closed grace window: recently-closed items are deliberately kept
and sorted last. Do not change that behaviour.

---

## Phase 5 — Locations render with dangling separators

**560 live rows** render as `London,` `Sydney,` `Remote,` `Brasil,` — a trailing comma with
nothing after it. Small, but it is on every card and it looks broken.

A fix already exists, unassessed, on pushed branch `claude/clever-einstein-6b43e2`: it adds
`frontend/lib/cleanLocation.ts` and applies it in `OpportunityCard.tsx`,
`opportunity/[slug]/page.tsx` and `opengraph-image.tsx`.

**Do:** review that branch on its merits. If it is correct, rebase onto current `master` and
open a PR. If not, write the fix fresh and abandon the branch.

Normalise at **render** time, not by rewriting stored data — the crawler owns the raw value and
will simply rewrite it. Handle leading and trailing `,` `·` `|` `/` `-` and doubled commas.

**Verify:** paste before/after rendered strings for at least 5 of the real affected rows
(`London,` and `Brasil,` are the most common).

---

## Explicitly OUT of scope for these phases

- **unstop budget truncation.** 38 days without a clean success is expected: it truncates on
  budget and correctly reports `partial`. It is converging (2173/2186 last measured) and
  ingest is idempotent, so each run advances. **No checkpointing.** Do not touch this.
- **Pagination / page-2 jumbling.** Already fixed — `feed.py` carries a deterministic
  tiebreaker. Re-measured this audit: page1 and page2 overlap = 0, stable across calls.
- **The 638 stale rows in the database.** They are correctly filtered from every browse
  surface. Phase 2 fixes the presentation. Do not mass-delete or mass-expire them.
- **All AI features.** Out of scope until Phase 3 of the roadmap.
- **Workday adapter.** Founder decision pending, not approved.
- **`feat/lever-a-board-batch`** and **`claude/fervent-shamir-1f3523`** — parked and unpushed,
  not part of these phases.

---

## Founder-only actions (Sonnet cannot do these)

- **Supabase → Authentication → Policies → enable leaked password protection.** Dashboard
  only; no API is exposed for it.
- **Decision: pursue Workday?** Per-tenant like Greenhouse/Lever, needs a company list. It is
  the genuine unlock for Adobe / TCS / Infosys-scale Indian employers.
- **Phase 3 needs a new shared secret** created and set in both the Render and Vercel
  environments.

---

## Suggested order

Phase 1 (merge, no new code) → Phase 2 (the casualty) → Phase 3 (cost) → Phase 4 (quality) →
Phase 5 (cosmetic).

Phases 2 and 3 touch different layers and could run in parallel if you prefer, but Phase 1
should land first: it is already built and is holding a real fix out of production.
