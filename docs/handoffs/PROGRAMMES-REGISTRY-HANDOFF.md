# Programmes Registry — Architecture Handoff

**Author:** Architect (Opus) · **Date:** 2026-07-31 · **Status:** Issued, not yet built

## 1. Why this exists

The founder's master list (2026-07-31) contains ~200 entities that Aspirova **structurally cannot
represent today**: IIT SURGE / IISc / TIFR VSRP research programmes, Indian Academy & INSA fellowships,
ISRO / DRDO / MeitY / NITI Aayog government internships, GSoC / Outreachy / LFX open-source mentorships,
Mitacs / CERN / DAAD international programmes, and recurring competitions (SIH, GRiD, CodeVita, ICPC).

They are **not job listings**. They are **recurring annual programmes**: one stable organisation, a new
edition each year, a fixed application window, hard eligibility rules, and long dormant periods.

Today every row in `opportunities` is a crawled listing with a live apply URL and an implicit "you can
apply now". Forcing programmes into that shape would either (a) show closed programmes as open — the exact
dishonesty the founder called out — or (b) hide them for 11 months a year, which destroys their value.

**This is the product's real differentiator.** No one aggregates IIT SURGE + ISRO + GSoC + Mitacs in one
place, and the founder's own §44 priority list is *almost entirely programmes, not job boards*.

## 2. Binding constraints

1. **Cost first.** The founder is actively fighting Render/Vercel/Upstash/Actions bills on a site with no
   real users. This design must add **no new infrastructure**, **no new vendor**, and **negligible**
   crawl/egress cost. That constraint drives every decision below.
2. **Never claim a programme is open without verification** (founder's explicit instruction). Default
   state is "expected", not "open".
3. **Reuse existing seams.** Postgres-only data plane (Doc 08). No new adapter type unless a programme
   genuinely publishes a machine-readable feed.

## 3. Core decision: curated registry, NOT crawling

**Do not build 200 website scrapers.** Programme sites are heterogeneous, low-change (once a year), and
often JS-rendered — 200 fragile parsers would cost enormous engineering effort, constant maintenance, and
real Actions minutes, to re-discover facts that change annually.

**Instead: a curated JSON registry committed to the repo**, seeded into Postgres — the pattern this
codebase already uses for `frontend/lib/taxonomy.json`, `skillsLexicon.json`, and the colleges dataset.
Content is authored (by the architect/founder), not scraped.

Cost: **~0**. A registry of ~200 programmes is <1 MB, seeded by an idempotent script, cached like every
other read.

## 4. Data model (2 tables)

The split is the heart of the design: **the programme is stable; the edition is what changes.**

```
programmes                      -- the stable entity (authored once)
  id, slug (unique), name
  organiser                     -- "IIT Kanpur", "ISRO", "Google"
  category                      -- see §5
  url                           -- canonical programme page
  description
  eligibility                   -- free text: year of study, discipline, nationality
  typical_window                -- free text: "applications usually open in February"
  country                       -- 'IN' | 'XX' | null (global)
  tags jsonb                    -- ['research','ai','government'] for matching
  is_active bool                -- retire a discontinued programme without deleting history
  created_at, updated_at

programme_editions              -- one row per year (verified separately)
  id, programme_id FK
  year smallint
  status                        -- see §6
  opens_at, closes_at           -- nullable until known
  source_url                    -- the specific edition page/announcement
  verified_at                   -- when a human/job last confirmed this
  notes
  UNIQUE (programme_id, year)
```

Indexes: `programmes(slug)` unique; `programme_editions(status, closes_at)` for the open-now query;
`programmes` GIN on `tags` only if matching proves slow — **do not add speculative indexes** (Doc 08).

## 5. Categories (covers the founder's §15–24 + recurring §25–33)

`research_internship` (IIT/IISc/IISER/TIFR/NIT/IIIT) · `fellowship` (IASc, INSA, NASI, Khorana) ·
`government_internship` (ISRO, DRDO, MeitY, NITI Aayog, RBI, SEBI, CSIR labs) ·
`open_source` (GSoC, Outreachy, LFX, MLH, Season of KDE) ·
`international_research` (Mitacs, CERN, DAAD WISE, RISE, S.N. Bose, A*STAR, KAUST) ·
`corporate_research` (Google Student Researcher, MSR India, Adobe Research, Amazon Science) ·
`recurring_competition` (SIH, GRiD, CodeVita, HackWithInfy, ICPC, Kaggle-style annual events) ·
`scholarship` · `conference`.

This is a `programmes.category` text column with a CHECK constraint — **not** a new enum shared with
`opportunities.category`. Keep the two vocabularies separate; conflating them would leak programme
semantics into the feed's job/internship logic.

## 6. Status model — the honesty mechanism

| status | meaning | shown as |
|---|---|---|
| `expected` | **default.** We know it recurs; this year unconfirmed | "Usually opens in March" — never "apply now" |
| `announced` | edition confirmed, window not yet open | "Opens 15 Mar" |
| `open` | **verified** open now | appears in the live feed |
| `closed` | window passed | "Closed — next edition expected March 2027" |
| `discontinued` | programme ended | hidden from default views |

**Rule: only `open` may surface as an actionable opportunity, and only with a `verified_at` inside a
sensible recency window.** Everything else is directory content. This directly implements the founder's
instruction and means a stale registry degrades to "informative" rather than "wrong".

## 7. Surfacing (where students actually see it)

1. **`/programmes` directory** — browsable, filterable by category/eligibility/country. Valuable
   year-round *because* it shows dormant programmes with their typical windows. This is the SEO asset:
   ~200 long-tail pages ("IIT Kanpur SURGE 2027 eligibility") that no competitor has.
2. **Feed integration** — an edition with `status='open'` appears alongside opportunities, clearly badged
   as a programme, linking to `source_url`.
3. **Personalisation** — match `programmes.tags` against the existing `users.field_profile` /
   `users.skills`. Reuses the Smart Profile seam; no new matching engine.
4. **Deadline reminders** — reuse the existing notification pipeline for `closes_at` proximity. This is
   the highest-value student feature in the whole design: programmes are *missed*, not *unknown*.

## 8. Verification workflow (the only recurring cost)

- **Weekly**, not daily. Programmes change annually; daily checking is pure waste.
- Reuse `pipeline/liveness.py` (already built): HTTP-check each programme `url`; 404/410 flags it for
  review. Conservative rules already apply — only hard-dead URLs flag.
- A "needs review" report: editions whose `closes_at` has passed, or whose `verified_at` is older than
  ~90 days, or whose `status='expected'` while their typical window has arrived.
- **Human-in-the-loop by design.** The job *flags*; a person *confirms*. Never auto-promote to `open`.

Cost: ~200 HTTP requests/week, folded into an existing workflow. **Well under 1 minute of Actions time.**

**Amendment (2026-08-04) — the report's two scheduling triggers, corrected.** As first built, both
were broken in opposite directions and the report could not do the job this section describes.

- **`review_months` is the seasonal trigger; `typical_window` is not.** The trigger originally
  decided a programme was due by parsing month names out of the free-text `typical_window`. Only
  **7 of 82** entries contained a parseable month, because that prose is deliberately hedged —
  §6's honesty rule means it must not assert a month nobody verified. Hedging the prose was right;
  depending on it for scheduling was not. Two individually correct decisions combined into a defect.
  Registry entries therefore carry an optional **`review_months`** (list of 1–12): *internal
  scheduling metadata only*, never rendered, never returned by the API. The asymmetry is the whole
  justification — a wrong `typical_window` misleads a student, whereas a wrong `review_months` only
  means we look a month early, so it can carry a schedule the prose honestly cannot. It is read from
  the registry file at import, following `api/programmes.py`'s loading of `programme_tag_map.json`;
  **no DB column and no migration.** The trigger prefers it and falls back to the prose parsing.
- **Absent `review_months` is a valid authoring choice.** 15 of 82 have none — Indian government
  schemes that notify ad hoc or run rolling intakes, plus a few with no stable month. A guessed
  month fires the report at random and trains the reader to ignore it, which is how a signal dies.
- **A null `verified_at` is NOT stale.** The rule originally flagged it, which in production meant
  **78 of 84 editions every week** — a report saying "78 items need review" says nothing. A null
  value is the *seeded default state*, not decayed verification: it never claimed to be verified.
  Staleness now requires `verified_at IS NOT NULL` and older than the threshold; the seasonal
  trigger is what brings never-verified rows up at the right time.

Measured on production after the fix: stale items **78 → 0**; seasonal coverage per month **0–5 →
4–44**, concentrated in the real application seasons (Dec–Mar, Sep–Dec) with April correctly quiet.

## 9. Build order

| Part | Scope | Status | Notes |
|---|---|---|---|
| **1** | Migration (2 tables) + `programmes.json` registry (~40 highest-value entries) + idempotent seed script | **DONE** | Prove the model on the §44 priority list first |
| **2** | Read API (`/programmes`, `/programme/{slug}`) + cached/rate-limited per the existing middleware tiers | **DONE** | Reuse the long-TTL tier — this data changes annually |
| **3** | `/programmes` directory + detail pages + JSON-LD | **DONE** | The SEO asset |
| **4** | Feed integration for `status='open'` + programme badge | **BLOCKED (correctly)** | Nothing to surface: production has 0 `open` editions and will until a human confirms one |
| **5a** | Personalisation via `field_profile`/tags | **DONE** (2026-08-03) | `programme_tag_map.json` + `?divisions=` ranking + matched band |
| **5b** | Deadline reminders | **BLOCKED on content** | Fires only on `announced`/`open` editions with a real `closes_at`; production has exactly 1 (RISE 2027). Unblocked by **edition verification**, not by registry expansion — see the amendment below |
| **6** | Weekly verification + needs-review report | **DONE** | |
| **7** | Expand registry to full ~200 coverage | **FIRST TRANCHE DONE** (2026-08-04) | 52 → 82; all 9 categories populated for the first time. Still short of ~200, so the part stays open |

**Amendments since issue (2026-08-03):**
- The "current edition" is the **highest-`year` non-`discontinued`** edition, not `year == current_year`.
  Application windows routinely precede their cohort year, and the original rule hid them. The
  selection is date-free — it chooses which row to show and never touches a stored status.
- Per-year facts live in `backend/data/programme_editions.json`, authored with a source URL and
  `verified_at`. The seed **rejects `status: "open"`** from that file outright, so §6's
  "never auto-promote to open" is enforced by code, not convention.
- §7's `/research` page had to be folded into this registry: it was a second, contradictory
  source of truth that inferred openness from the browser clock.

**Amendments from Part 7 (2026-08-04):**
- **§9 was wrong that Part 7 unblocks Parts 4 and 5b.** Expanding the registry adds *programmes*;
  Parts 4 and 5b need *editions* with a verified `status` and `closes_at`. Those are separate
  authoring acts against `programme_editions.json`. Part 7 took the registry 52 → 82 and moved
  neither gate: production still has 0 `open` editions and exactly 1 with a real `closes_at`.
  **The true unblocker is edition verification** — checking official pages for published windows —
  which is the §8 weekly-verification loop doing its job, not a content-volume problem.
- **Registry content is authored by the architect, never delegated to the implementation agent.**
  §3 already required authored content; this makes the process binding. Handing an agent programme
  descriptions, eligibility rules and URLs invites invented facts into the one dataset whose entire
  premise is honesty. The engineering half — validation, seeding, tests — is delegated as normal.
- **Every `url` must be live-checked before commit.** Part 7 verified all 30 additions returned
  HTTP 200 and **dropped 9 candidates rather than guess** (502s, 404s, unreachable hosts). A
  plausible-looking dead URL is worse than an absent programme: §8's liveness job would flag it
  weeks later, after students had already followed it.
- **The tag vocabulary is closed**, enforced by test: every tag must be reachable from
  `programme_tag_map.json`, plus five deliberate registry-only signals (`research`, `international`,
  `government`, `competition`, `open-source`) that describe organiser/location/type rather than
  field of study. This caught a real defect on its first run — `blockchain` was reachable from no
  division, so two programmes could never match a CSE student despite the taxonomy having a
  `blockchain` interest under `cse`.
- **`typical_window` may contain no 4-digit year**, enforced by test. The programme row describes a
  *recurring* window; year-specific facts belong in `programme_editions.json`. A year baked into
  `typical_window` goes stale silently and starts misleading students — the §6 failure mode by a
  different route.
- **`eligibility` may be null; `description` and `typical_window` may not.** The first is a
  detail-page section that degrades gracefully when omitted, and 20 curated entries have no verified
  eligibility text — inventing it would be exactly the fabrication §6 forbids. The other two are
  what the directory card renders, so blank is a visible defect. A present-but-empty value is
  rejected in all three cases.

**Ship Part 1–3 before 4–7.** A browsable, honest directory is independently valuable and proves the
model before it touches the feed.

## 10. Explicitly out of scope

- **Learning resources (§34–42)** — Codeforces, CLRS, NeetCode, MDN. These are *resources*, not
  opportunities. Adding them changes what Aspirova is ("Every opportunity. One place."). A separate
  product decision; do not smuggle them in via this table.
- **Scraping programme websites** — see §3.
- **Auto-marking editions open** — see §6.

## 11. Cost summary

| Resource | Impact |
|---|---|
| New infrastructure | **none** |
| Storage | <1 MB (~200 programmes + editions) |
| Crawl / Actions | ~200 HTTP req/week, <1 min |
| Egress | small rows, cached on the existing long TTL tier |
| AI | **none** — no LLM anywhere in this design |

Net: effectively **$0**, while adding the product's clearest differentiator.
