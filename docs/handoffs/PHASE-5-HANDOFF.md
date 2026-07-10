# Phase 5 Handoff — Opportunity Expansion: the Cream Layer + Competitions

**Architect:** Claude Opus (Chief Architect). **Engineer:** Codex (gpt-5.6-sol @ ultra).
**Status:** HANDOFF — draft for founder review before execution. Written 2026-07-11.
**Governing canon:** Doc 03 (data), Doc 04 (crawler), Doc 08 (governance HARD RULES = merge gate).

---

## 0. Why this phase exists (the problem, evidence-backed)

Two founder asks, one root cause and one greenfield:

**Ask A — "Why no famous companies / no Top 10/50/100/500? Where is MAANG?"**
Measured against the live production DB (2026-07-11):
- **203 companies total; only 5 carry a Forbes `global_rank` at all** (min rank **132**). So the feed's **Top 10 / 50 / 100 filters return 0 companies**, Top 500 returns 3. The `top` filter keys on `Company.global_rank` (Doc: `api/filters.py`), which is populated *only* by `scripts/match_forbes.py` matching a **crawled** company to the bundled Forbes Global 2000 list.
- **MAANG count in DB = 0** (Google, Amazon, Microsoft, Apple, Meta/Facebook, Netflix, Nvidia — and Flipkart — all zero).
- **Root cause:** the crawler's entire company universe is a **~21-company hardcoded seed** (`scripts/seed_companies.py`) across Greenhouse (12), Lever (3), Ashby (3), SmartRecruiters (3), plus the RemoteOK aggregator (dynamic, supplies the bulk of the ~4,026 active opps as small/unknown companies). **MAANG do not use those four ATSes** — they run proprietary career systems — so they are never crawled. And most seeded companies are private startups (Stripe, Figma, Notion) that are **not in Forbes Global 2000**, so even they don't get a rank → the Top-N filter is empty by construction.
- Internships are only **67 of 4,026** active opps — the aggregator is overwhelmingly full-time jobs.

**Ask B — "Add competitions / hackathons / contests as first-class opportunities."**
Company-hosted hackathons and coding competitions (Flipkart GRiD, Google Kickstart/Hash Code, Meta Hacker Cup, Unstop challenges) are a primary funnel from student → internship → job. They are time-boxed by a **registration deadline** (the founder's example: a Flipkart contest whose registration closed 2026-07-07 — missed by many). These are genuine opportunities and fit the brand ("Every opportunity. One place.") but are **not modeled today** (`Opportunity.category` only ∈ {internship, job}).

---

## 1. Goals / non-goals

**Goals**
1. Make the **Top-N filter meaningful** and put **recognizable, prestigious companies** (incl. literal MAANG) into the feed.
2. Model and ingest **competitions/hackathons/contests** as first-class opportunities, with registration-deadline alerting so subscribers don't miss them.
3. Do both **within Supabase Pro limits** (8GB disk / 250GB egress) — growth is fine but must be incremental + change-detected, never repeated full scans.

**Non-goals (this phase)**
- No AI cost expansion (embeddings/enrichment for competitions reuse the existing gated pipeline; no new paid AI on the hot path — Doc 02 §3).
- No scraping that violates a platform's ToS/robots without an available public/JSON API (see §6 risk table). Prefer official/public JSON endpoints.
- No change to plan gating/pricing.

---

## 2. Data model changes (Doc 03 contract — Alembic migration is the source of truth)

Keep **one canonical `opportunities` table** for all opportunity kinds (a competition IS an opportunity). Minimal, additive schema:

1. **Broaden `Opportunity.category`** taxonomy (free-text column already; no DB enum). Allowed values become:
   `internship | job | hackathon | competition`
   - `hackathon` = build-something events (Devpost/Devfolio/MLH + company hackathons like Flipkart GRiD's hackathon rounds).
   - `competition` = coding contests / challenges / case comps / CP rounds (Unstop challenges, Kaggle, Codeforces/CodeChef rounds, Meta Hacker Cup).
   - (Reserve `fellowship`, `scholarship` for a later phase — do NOT add now.)
   - **All API validators must broaden** from `^(internship|job)$` to `^(internship|job|hackathon|competition)$` (`api/feed.py`, `api/search.py`, anywhere else the pattern appears).

2. **Add `Opportunity.meta JSONB NULL`** — type-specific attributes that don't deserve first-class columns yet. For competitions: `{ organizer, prize, mode: "online"|"offline"|"hybrid", eligibility, team_size, registration_deadline, event_start, event_end, tags: [...] }`. Roles leave it null. (Notification already uses a JSONB `meta`; mirror the pattern.) One migration: `add_opportunity_meta`.
   - `deadline` (existing) = the **registration deadline** for competitions (drives "closing soon" + the deadline sort). `deadline_confidence` reused.
   - Rationale for JSONB over a side table: competitions are read-mostly, attributes are sparse/evolving, and JSONB keeps the hot feed query single-table (Doc 02 §3 latency rule). Promote a field to a real column only when we need to index/sort on it.

3. **Company cream-tier ranking** — the current `global_rank` (Forbes Global 2000) is a decent proxy for *big public* companies but misses prestigious *private* ones (Stripe, OpenAI, Databricks). Add a curated overlay:
   - New bundled data file `data/prestige_companies.json` — a hand-curated list of ~150–300 high-signal companies (MAANG + top unicorns + top product/CP-relevant firms) each with a `prestige_rank` band (e.g. 1–50 "dream", 51–200 "top"). 
   - Keep `global_rank` as-is (Forbes). Add **`Company.prestige_rank INT NULL`** (migration `add_company_prestige_rank`) populated by a new `scripts/match_prestige.py` (same domain/name matcher as match_forbes).
   - The feed `top` filter changes semantics to **"effective rank = LEAST(prestige_rank, global_rank)"** so both Forbes giants and hot private startups qualify for Top-N. `api/filters.py` updated accordingly (still a single indexed comparison).

No destructive changes; all columns nullable/additive; no reindex of existing rows required.

---

## 3. Part 5.1 — The Cream Layer (companies) 

**5.1a — Expand ATS seeds (fast, low-risk, uses existing adapters).**
- Grow `GREENHOUSE_/LEVER_/ASHBY_/SMARTRECRUITERS_COMPANIES` in `seed_companies.py` with ~40–80 **recognizable** companies that actually use those ATSes (fintech/AI/product names students want). **Every board token MUST be verified live (HTTP 200 + non-empty jobs) before inclusion** — per the existing rule in that file. **Verification is Claude's job** (Codex's sandbox can't spawn network processes): Claude curls each candidate token, hands Codex only the verified `(token, name, domain)` triples. Netflix → Lever (`netflix`) belongs here.
- **Guardrail:** to bound crawl duration/egress, land in batches (the file already documents holding some out). Target ≤ ~80 net new ATS companies this part.

**5.1b — Prestige overlay + ranking fix.**
- Add `data/prestige_companies.json` (curated; Claude supplies the list), `Company.prestige_rank` migration, `scripts/match_prestige.py`, and the `api/filters.py` effective-rank change (§2.3). Re-run `match_forbes` + `match_prestige` after seeding so Top-N lights up.

**5.1c — MAANG proper (custom adapters; higher effort, ToS-aware).**
The literal MAANG/adjacent giants need dedicated adapters against their **public JSON job APIs** (one adapter each, same contract as `crawlers/greenhouse.py`, registered in `crawlers/runner.py`, seeded as `type="ats"`/`"employer"` Sources):
- **Amazon** — `https://www.amazon.jobs/en/search.json` (public, paginated, supports `category`/`normalized_location`).
- **Microsoft** — `https://gcsservices.careers.microsoft.com/search/api/v1/search` (public JSON).
- **Google** — `https://careers.google.com/api/v3/search/` (public JSON).
- **Apple** — `https://jobs.apple.com/api/role/search` (JSON POST).
- (Meta — GraphQL, more fragile; defer to a follow-up.)
- **Each adapter:** internships-first (filter to student/intern + new-grad where the API allows), map to `Opportunity(category=internship|job, company=<the giant>)`, resolve/seed the Company with a real `domain` + a high `prestige_rank`. **Robots/ToS:** these are public search JSON endpoints; respect rate limits, set a descriptive UA, honor `Source.robots_policy` + change-detection (`SourceState`). If any endpoint requires auth or blocks, **stop and flag — do not scrape around it** (Doc 08 legal rule).

**Order:** 5.1a + 5.1b first (immediate visible fix, no fragile adapters), then 5.1c per-giant.

---

## 4. Part 5.2 — Competitions / Hackathons / Contests

**5.2a — Schema + ingest plumbing.** `category` broadening + `meta JSONB` migration (§2.1/2.2); extend `pipeline/ingest.py` + `pipeline/company_resolution.py` to accept the new categories and populate `meta` + `deadline` (registration close). Competition organizers resolve to a `Company` where one exists (Flipkart → company), else `company_id` null (allowed).

**5.2b — Source adapters (public/JSON first).** New `type="competition"` Sources + adapters in `crawlers/`, prioritized for the student audience:
1. **Unstop** (`unstop.com` — formerly Dare2Compete) — **highest priority**; this is where **Flipkart GRiD, company challenges, case comps, hackathons** for Indian students live. Public opportunity search JSON. Directly fixes the founder's Flipkart example.
2. **Devpost** (`devpost.com/api/hackathons` — public JSON) — global hackathons.
3. **MLH** (Major League Hacking season list) — student hackathons.
4. (later) **Kaggle** (ML comps), **Codeforces/CodeChef** (CP contest calendars, official APIs) — for pure competitive-programming/ML contests.
- Each adapter: same runner contract; map to `Opportunity(category=hackathon|competition, deadline=registration_close, meta={organizer,prize,mode,eligibility,team_size,event_start,event_end})`, `apply_url`=registration URL. Change-detected via `SourceState`.

**5.2c — API.** Category validators broadened (§2.1). The existing `/feed` + `/search` already filter by `category`, so competitions are queryable immediately. Add convenience: `/feed?category=hackathon|competition` works; optionally a `type` grouping later. Keep `deadline` sort working (registration closing-soon).

**5.2d — Frontend (Almanac system).**
- Feed **Category filter** gains **Hackathons** + **Competitions** (extends the chips/dropdown from #38/#39 — trivial once the API accepts them).
- **Competition card variant** (reuse `OpportunityCard` shape): show **prize**, **mode** (online/offline), **organizer**, and a prominent **"Registers by <date>"** with an urgent state when < 7 days (this is the anti-"missed Flipkart" signal). `.tnum` on prize/dates.
- A dedicated **/competitions** landing = the feed pre-filtered to hackathon+competition, with its own editorial masthead ("THE ARENA" / "Competitions & hackathons"), plus a nav entry. On-brand with "one place."

**5.2e — Notifications (the anti-miss).** Extend the existing notification worker (Resend) to send a **"registration closing soon"** alert for hackathons/competitions with `deadline` within N days (default 3), deduped via the existing `notifications(user_id,type,sent_at)` index. Gated/prefs like other alerts. This is the feature that ensures "my subscribers don't miss this type of opportunity."

---

## 5. Build order (each part is one Codex work-order + Claude review + merge-gate)

| Part | Scope | Deploys | Risk |
|------|-------|---------|------|
| **5.1a** | Expand ATS seeds (Claude-verified tokens) + broaden category validators | seed+crawl (founder-authorized) | low |
| **5.1b** | `prestige_rank` col + `data/prestige_companies.json` + `match_prestige.py` + effective-rank in `filters.py` + re-rank | migration + script | low |
| **5.2a** | `meta JSONB` migration + category taxonomy + ingest plumbing + tests | migration | low |
| **5.2b-1** | **Unstop adapter** (Flipkart GRiD et al.) + seed Source + tests | crawl | med (ToS) |
| **5.2d** | Frontend: category filter + competition card + /competitions page + nav | Vercel | low |
| **5.2b-2** | Devpost + MLH adapters | crawl | med |
| **5.2e** | Registration-closing-soon notifications | worker | low |
| **5.1c** | MAANG adapters (Amazon → Microsoft → Google → Apple), one at a time | crawl | med (ToS/fragility) |

Rationale for order: 5.1a/b give the **immediate visible cream-layer fix**; 5.2a/2b-1/2d ship a **working competitions MVP featuring Unstop (Flipkart)**; then breadth (Devpost/MLH), alerts, and the harder MAANG adapters.

---

## 6. Supabase-limit guardrails (founder constraint — hard)

- **Change-detection required:** every new adapter MUST use `SourceState` content hashing (Doc 04 §6) so unchanged pages don't re-ingest — this bounds egress.
- **Incremental crawl, batched writes:** reuse the Lever-1 set-based bulk upsert path (Doc 04); no per-row round-trips; no repeated full-catalog scans.
- **Bounded seed growth per part** (≤ ~80 ATS companies in 5.1a; competition adapters paginate with sane caps). Storage is a non-issue at these volumes (8GB); **egress from crawl frequency is the thing to watch** — keep the scheduled crawler cadence unchanged, just more sources per run.
- Reuse `data/*.json` bundled files (Forbes, prestige) — no external ranking API calls.

---

## 7. Founder decisions (RESOLVED 2026-07-11)

1. **Execution order:** ✅ **Cream layer first** (Part 5.1), then competitions (Part 5.2).
2. **MAANG adapters (5.1c):** ✅ **Yes, staged** — one giant at a time, internships-first, public JSON endpoints only; stop + flag if any blocks crawlers.
3. **Competition source priority (5.2):** ✅ **Unstop first** (captures Flipkart-type Indian-student contests) → Devpost → MLH.
4. **Surface (5.2d):** ✅ **Unified feed** (extra Category values) **plus a dedicated /competitions page** — on-brand with "one place."
5. **Prod data ops:** ✅ **Ask before each** seed/crawl/rank/migration run; batched, off-peak, not concurrent with CI.

---

## 8. Decision-log entries to append to docs/README.md (on approval)

- **Binding:** All opportunity kinds share the one `opportunities` table; kind = `category` ∈ {internship, job, hackathon, competition}; type-specific fields live in `opportunities.meta` (JSONB), not new tables, until an index/sort need promotes one to a column.
- **Binding:** Top-N filter ranks by `LEAST(prestige_rank, global_rank)` (curated prestige overlay + Forbes), not Forbes alone.
- **Binding:** New crawl sources MUST use `SourceState` change-detection + set-based bulk upserts (Supabase egress guardrail).
- **Binding:** Custom employer/competition adapters use only public/JSON endpoints; if an endpoint needs auth or blocks crawlers, stop and flag — never scrape around it.
