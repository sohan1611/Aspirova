# Sources Expansion — Architecture Handoff

*Architect: Claude Opus. Engineer: Codex. Status: ISSUED. Governs Doc 04 (Crawler System) under Doc 08's hard rules. Goal: grow coverage (more live opportunities for students) by (A) seeding more companies onto the existing adapters — the cheap, huge lever — and (B) adding new adapter types. No AI involved.*

## 0. The distinction the founder should hold
The homepage shows **9 sources · 1,430 companies · 13,503 live opportunities**. These are three different dials:
- **Sources (9)** = adapter *types* (greenhouse, lever, ashby, smartrecruiters, keka, amazon, + aggregators unstop/devpost/remoteok). Raising this = **new code** (Lever B).
- **Companies (1,430)** = boards crawled by those adapters. Raising this = **pure data**, zero new code, and it is where **most new opportunities actually come from** (Lever A). One `GreenhouseAdapter` already covers *every* Greenhouse company by board token (Doc 04 §3/§11) — the moat.

**Recommendation:** do **Lever A first** (fastest path to more opportunities), then **Lever B** (new platforms unlock companies the current 6 ATS adapters can't reach). "More sources" as literally asked = Lever B; "more opportunities" = mostly Lever A. Both are below.

## 1. How the system works (grounding — do not rebuild)
- **One contract** (`core/adapters.py`): a `SourceAdapter` implements `source_slug`, `requires_browser`, `fetch() -> Iterable[RawListing]`, `parse(raw) -> NormalizedListing`, `health() -> "ok"|"degraded"|"broken"`. `GreenhouseAdapter` (`crawlers/greenhouse.py`) is the reference: hit the board's JSON API, map fields, done.
- **Registration** (`crawlers/runner.py`): a per-company ATS adapter is one entry in `ATS_ADAPTERS` (`adapter_key -> class`); an aggregator is one entry in `AGGREGATOR_ADAPTERS`. The ingest/dedup/change-detection pipeline **never changes** when a source is added.
- **Data model**: a `sources` row carries `adapter_key` (== `companies.ats_type`), `crawl_tier`, `enabled`, `legal_status` (`"ok"` is the kill switch). A company on an ATS is a `companies` row with `ats_type` + `ats_board_id` (the board token — **DATA, never hardcoded**, Doc 04 §11).
- **Free by construction** (adapters get these for nothing): per-source isolation (one broken board never aborts the batch), change detection (unchanged board → skip parse/dedup — the core cost lever), stalest-first time-boxed scheduling. Don't re-implement these in an adapter.
- **Playwright policy (Doc 04 §5, strict)**: `requires_browser` MUST be `False` unless the source genuinely needs JS. **Always find the underlying JSON/XHR/XML endpoint first.** Every candidate below has one — so all new adapters are plain HTTP.

## 2. Lever A — seed more companies onto the existing adapters (data, zero code, do first)
The 6 ATS adapters already cover thousands of companies each; we're only pointing them at 1,430. To add a company: discover its ATS + board token, verify the token is real, insert a `companies` row (`ats_type`, `ats_board_id`, name/slug/domain), and the next crawl picks it up (stalest-first → new boards crawl first).

Work:
1. **A discovery/seed script** (`backend/scripts/seed_boards_batch.py` or extend `seed_companies.py`): takes a curated list of `{company, ats_type, board_token, domain}` and upserts `companies` rows idempotently (skip if slug/board exists), mirroring the existing `seed_companies.py` style.
2. **The curated list is the real work** — a vetted set of company→board mappings. Target student-relevant employers (Indian startups/unicorns + global tech + the "dream companies" set). Aim to roughly **double companies (→ ~3,000)** in the first batch.
3. **Verified-boards control (BINDING — a past bug):** every candidate board token MUST be proven real before seeding, because some ATS APIs return a **200 with an error/empty object** for a bogus token rather than a 404 (Lever's `api.lever.co` returned an error *object*, `len()==2`, that a naive check counted as 2 "boards"). The seed script must call the adapter's `fetch()` against each token and only keep tokens that yield **real listings or a legitimately empty-but-valid board**, discarding error-object/`broken`-health responses.

**Founder prerequisites (Lever A):** (1) authorize seeding the new `companies` rows to **prod** (per the standing board-authorization step); (2) note the **crawl-time budget** — more boards = longer crawl. The Tier-1 job runs ~29 min under a 38-min cap today; the runner time-boxes and rotates stalest-first, so coverage stays complete across runs, but a large jump means individual boards refresh less often. If needed, split into tiers or raise cadence (watch the GitHub Actions minutes budget — see the crawl-budget memory).

## 3. Lever B — new adapter types (new code; each is a small, self-contained part)
Each new adapter mirrors `GreenhouseAdapter`: plain-HTTP `fetch()` of a JSON/XML endpoint → `parse()` to `NormalizedListing` → `health()`; register in `ATS_ADAPTERS`; add a `sources` row; seed a few verified companies. Candidates, each with a confirmed structured endpoint (engineer must re-verify the exact URL shape at build time):

| Adapter | Endpoint shape (verify) | Notes |
|---|---|---|
| **Workable** | `https://apply.workable.com/api/v1/widget/accounts/{subdomain}?details=true` (or the account jobs JSON) | Very common with startups; clean JSON. |
| **Recruitee** | `https://{company}.recruitee.com/api/offers/` | JSON `offers[]`; simple. |
| **Personio** | `https://{company}.jobs.personio.de/xml` | XML feed (strong in EU/India); parse with stdlib xml. |
| **Freshteam** | schema.org `JobPosting` JSON-LD on `/jobs` pages | Memory caveat: robots is `Allow:/jobs` + `Disallow:/`; **1+N requests/board**; and re-check the unverified claim that Freshworks sunset Freshteam for new customers before investing. |
| **BambooHR** | `https://{subdomain}.bamboohr.com/careers/list` (JSON) | Confirm the public careers JSON. |

Recommended first two: **Workable** and **Recruitee** (cleanest JSON, widest startup coverage). Defer Freshteam (caveats) and anything anti-scraping (Wellfound/AngelList, LinkedIn, Indeed — do NOT add; ToS/legal + they need browsers).

Per-adapter checklist:
1. `crawlers/<name>.py` implementing the contract; plain `httpx` (reuse `crawlers/common.py`: `USER_AGENT`, `content_hash`, `extract_text`; `pipeline.normalize.classify_category` for category). `deadline=None`, `deadline_confidence="unknown"` (ATS jobs are rolling — correct).
2. Health: `404`/structural → `broken`; transient/`5xx`/timeout → `degraded`; success → `ok` (Doc 04 §7). Never raise out of `fetch()`.
3. Register in `ATS_ADAPTERS` (runner.py) + insert the `sources` row (`adapter_key`, `crawl_tier`, `enabled=true`, `legal_status="ok"`).
4. **Fixture-based tests** (mirror the existing adapter tests, e.g. `tests/test_unstop_adapter.py`): parse a saved sample payload → assert the NormalizedListing mapping; assert a bogus/empty response degrades to `broken`/`degraded` without raising and yields **zero phantom listings** (the verified-boards control at the unit level). **No live network in tests.**
5. Seed 3–10 verified companies for the new adapter (Lever-A process) so it produces real data.

## 4. Legal / ethics (Doc 04 §10 — binding)
Only public JSON/feed endpoints the company itself exposes for its careers page; respect `robots.txt`; keep `legal_status` as the one-flip kill switch. No login-gated or anti-scraping sources. No browser adapters in this effort.

## 5. Deadlines (ties into the separate due-date task)
ATS job adapters correctly emit `deadline=None`/`unknown` — job posts are rolling, they have no application deadline, so **do not fabricate one**. Deadlines only matter for competitions (unstop/devpost), which is a *separate* accuracy task (next). Keep new ATS adapters `unknown`.

## 6. Build order & merge gate
- **Part 1 (Lever A):** `seed_boards_batch.py` + verified-boards control + a first curated batch (~+1,500 companies). Architect reviews the list; founder authorizes the prod seed.
- **Part 2:** Workable adapter (+ tests + sources row + seed).
- **Part 3:** Recruitee adapter (+ tests + sources row + seed).
- **Part 4 (optional):** Personio / BambooHR / Freshteam as demand warrants.
- Each part: implement → architect verifies against the **CI ephemeral DB** (ruff + black + pytest; tests are now prod-free) → commit solely as `sohan1611`. Doc 08 §3 hard rules are the gate. Update Doc 04 / the Decision log if a binding assumption changes.

**Definition of done:** the homepage "sources" count rises with each new adapter; companies (and thus opportunities) rise materially from Lever A; every board token was verified before seeding; the crawl still completes within its time-box; no browser adapters; tests are fixture-based and prod-free.
