# Research ingestion — architecture handoff

**Date:** 2026-09-01
**Author:** Claude Opus (architect)
**Status:** Part 1 in implementation, Parts 2–5 specified

---

## 0. What triggered this, and a correction

The founder reported the Research tab as near-empty and suspected the crawl was failing. I replied
that research is curated by design and has no crawl — citing `PROGRAMMES-REGISTRY-HANDOFF.md` §3.

**The founder overruled that, and they are right:**

> Each type in Aspirova should have a crawl at least. In that way not a single quality reachable
> opportunity is missed.

That §3 decision was mine, from an earlier session, not theirs. The evidence supports overruling it:
a hand-curated file stalled at **82 of an intended ~200** entries, has not been edited since
**4 August**, and its only automated job **can exclusively close rows, never add or promote them**.
A pipeline that strictly degrades is not a pipeline.

The narrow part of §3 that survives: *do not build 200 scrapers for 200 individual programme
homepages.* That was never the only alternative to curation, and treating it as one was the error.

---

## 1. Three independent causes of "the research tab is empty"

Diagnosed 2026-09-01. They are separate problems and need separate fixes.

| # | Cause | Evidence | Fix |
|---|---|---|---|
| 1 | `/research` renders **2 of 9** categories | `app/research/page.tsx` queries only `research_internship` + `fellowship` = **16 + 9 = 25 items**. The other 57 are reachable only at `/programmes`. | Part 2 |
| 2 | Registry is **41% built and stale** | 82 rows vs ~200 target; `data/programmes.json` mtime 4 Aug | Part 5 |
| 3 | Editions never advance | **78 of 84** editions sit at `expected`; only **2** are `announced` | Part 3 |

Cause 1 is the largest and cheapest: the tab is showing 30% of content that already exists.

---

## 2. Source viability — probed live, not assumed

Every row below was tested on 2026-09-01. **Do not spec an adapter against an unverified source.**
This codebase has already shipped a Devfolio adapter that was written, reviewed, merged, deployed —
and stored zero rows for weeks.

| Source | Probe | Verdict |
|---|---|---|
| **Unstop `scholarships`** | `declared_total = 2383`, live public API, existing adapter already pages/dedupes/reports coverage | **VIABLE — Part 1, in progress** |
| Unstop `conferences` | `1178`; page-1 sample was Model UN, debates, college seminars (1 of 8 was a real conference) | Skip — fails the quality bar |
| Unstop `workshops` / `quizzes` | `9624` / `6519` | Skip — this is the noise tier |
| Unstop `fellowships` / `mentorships` / `courses` | `declared_total = 0` | Nothing upstream to take |
| **AICTE National Internship Portal** | `robots.txt` = `User-agent: * / Allow: /` (permissive), but sitemap holds **246 URLs, all static** (login, register, dashboards); `recentlyposted.php` returns 152 KB with **0 table rows, 0 AJAX endpoints**, 6 intern-classed nodes | **NOT VIABLE** — listings sit behind login. Do not crawl authenticated surfaces. |
| **Euraxess** (EU research posts) | `/jsonapi` → **404**; `/jobs/search` is HTML-only, 186 KB, markup carries `antibot` guards | Deprioritise — HTML parsing + bot defences = the treadmill §3 warned about |
| **Buddy4Study** | `robots.txt` permissive except `/media-url/*`, `/UID/*`; **sitemap index present** | **SPIKE REQUIRED** — Part 4 |
| NSP (`scholarships.gov.in`) | no `robots.txt` (404) | Treat with caution; absence of robots is not permission |

### The structural finding

**No aggregator exposes Indian institutional research internships.** IIT/IISER/TIFR/national-lab
summer programmes are announced on their own sites, one page each, once a year. That is a real
constraint, and it is why the registry exists.

But it does **not** follow that the registry must stay manual. See Part 3.

---

## 3. Part 3 — make the verifier PROMOTE, not only close (the key idea)

This is the highest-leverage item in this document.

`scripts/verify_programmes.py` + `pipeline/programme_verification.py` already run weekly
(`weekly-report.yml`, 8/8 successful runs) and already:

- fetch per-programme URL liveness (`fetch_url_liveness_status`)
- parse `typical_window` prose and `review_months`
- emit a needs-review report

The workflow's own comment states the limitation:

> programme verification only closes editions whose non-null `closes_at` is already in the past;
> **it never promotes rows to open** and otherwise only prints the needs-review report.

So the registry can only lose entries. **Extend the existing verifier to advance an edition when
evidence supports it** — `expected → announced` when a programme's page, inside its
`review_months`, shows an open application signal.

Why this is the right shape:
- It reuses rails that already exist, run, and are proven reliable.
- It is ~1 capability, not 200 scrapers — it respects what §3 got right.
- It scales with the registry: every entry added in Part 5 becomes self-maintaining.
- It is bounded and safe: promotion is per-programme, rate-limited, and already runs under
  `robots_policy` respect and the `AspirovaBot/0.1` identifying UA.

**Design constraints for the implementer:**
- Promotion must require positive evidence, never inference from silence. "Cannot tell" is
  `expected`, not `announced` — this codebase's Law 06: *'resolving' is a third state.*
- Never auto-promote to `open`. `announced` is the ceiling for an automated signal; `open` should
  remain human- or deadline-confirmed.
- Count and report every promotion in the weekly report, so a wrong rule is visible immediately.
- The needs-review report is currently unread. It flagged `pm-internship-scheme` — **URL dead,
  404** — on 2026-08-31 and nothing happened. Route it somewhere the founder actually sees.

---

## 4. Work items, in priority order

| Part | Work | Cost | Status |
|---|---|---|---|
| **1** | Unstop `scholarships` ingestion + quality gate + new `scholarship` category | zero new infra | **In implementation (Codex)** |
| **2** | Broaden `/research` beyond 2 categories — 25 → up to 82 visible | one-line change | Specified below |
| **3** | Promotion capability in `verify_programmes` | one capability on existing rails | Specified above |
| **4** | Buddy4Study spike — prove or kill in one sitting | timeboxed | Specified below |
| **5** | Registry content 82 → ~200, **India-first** (founder's call, 2026-09-01) | authoring | Ongoing |

### Part 2 spec

`frontend/app/research/page.tsx` filters to `research_internship | fellowship`. Widen to the
research-shaped set: add `international_research`, `corporate_research`, `government_internship`.
Leave `scholarship`, `open_source`, `recurring_competition`, `conference` at `/programmes` —
they are not research.

That moves the tab from 25 to roughly 25 + 13 + 6 + 11 = **55 items** with no crawl and no cost.
Confirm counts against the DB before shipping; do not trust these numbers blindly.

### Part 4 spec — Buddy4Study spike

Timeboxed. Answer three questions and stop:
1. Does the sitemap index expose **individual scholarship pages**, or only articles/static pages?
   (AICTE failed exactly here — permissive robots, useless sitemap.)
2. Is there a JSON endpoint behind the listing pages, or is it server-rendered HTML only?
3. What fraction of a 40-item sample is genuine aid vs lead-gen? Apply the same bar Part 1 used —
   a live sample of Unstop scholarships was only ~25% genuine before a quality gate.

**Kill the spike if (1) fails.** Do not write an adapter to prove a source exists.

---

## 5. Standing rule this establishes

Every opportunity type gets an ingestion path — but **a crawl per type with a quality gate, not an
open pipe**. Unstop's unused types total ~19,700 rows of which the large majority is noise;
ingesting them wholesale would damage the product more than the empty tab does.

The bar: *no quality reachable opportunity is missed* — where **quality** and **reachable** are
both load-bearing.
