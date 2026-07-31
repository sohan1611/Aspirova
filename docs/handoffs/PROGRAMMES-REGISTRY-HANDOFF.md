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

## 9. Build order

| Part | Scope | Notes |
|---|---|---|
| **1** | Migration (2 tables) + `programmes.json` registry (~40 highest-value entries) + idempotent seed script | Prove the model on the §44 priority list first |
| **2** | Read API (`/programmes`, `/programme/{slug}`) + cached/rate-limited per the existing middleware tiers | Reuse the long-TTL tier — this data changes annually |
| **3** | `/programmes` directory + detail pages + JSON-LD | The SEO asset |
| **4** | Feed integration for `status='open'` + programme badge | |
| **5** | Personalisation via `field_profile`/tags + deadline reminders | Reuses Smart Profile + notification seams |
| **6** | Weekly verification + needs-review report | |
| **7** | Expand registry to full ~200 coverage | Content work, not engineering |

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
