# Advanced filters — Research, Competitions & Hackathons, Programmes

**Date:** 2026-09-01
**Author:** Claude Opus (architect)
**Status:** Data audit complete. Build order specified. Not yet implemented.

---

## 0. Why this document leads with a data audit

The request specifies ~30 filter groups across three pages. Before any UI work, every group was
checked against the real data distribution, because this project already has a law about exactly
this failure:

> **Law 07 — Verify a filter against the real data distribution before building it.**
> A control returning plausible but meaningless numbers is worse than no control.

That law was paid for by Case 4 ("the filter that returned plausible nonsense"). Shipping a
"Funding: Fully Funded" pill that matches zero rows would repeat it at ten times the scale.

**Result: roughly two thirds of the requested filters are backed by data today. One third is not.**
Build the backed set now; the rest needs ingestion work first and is specified separately.

---

## 1. Competitions & Hackathons — mostly buildable

Checked against the 843 active `hackathon` + `competition` rows. The useful signal is in
`opportunities.meta` (JSONB), not in columns.

| Requested filter | Backing | Verdict |
|---|---|---|
| **Type** (Hackathon / Coding / Case / Ideathon / Quiz / …) | `meta.subtype` — 6 clean values: `online_coding_challenge` 232, `general_competition` 220, `case_competition` 52, `innovation_challenge` 44, `hiring_challenge` 16, `events` 2. Plus `meta.type` (competitions/hackathons/quizzes) | **BUILD** — map subtype→label; do not invent CTF/Business Challenge, nothing backs them |
| **Registration Free / Paid** | `meta.is_paid` — clean boolean, 649 rows | **BUILD** |
| **Prize pool range** | `meta.prizes` — structured `[{cash, rank, currency}]`, 328 rows | **BUILD**, but see currency note below |
| **Deadline windows** (today / 3 / 7 / 30 days) | `opportunities.deadline` — 759/843 | **BUILD** |
| **Organizer** (searchable) | `company_id` 843/843 + `meta.organizer` 370 | **BUILD** — derive from companies, never hard-code |
| **Organizer type** (IIT / NIT / IIIT / Govt / Companies) | Derivable from company name. **Reuse `_REPUTED_ORGANISER_REGEX` in `pipeline/notifications.py`** — already word-boundary anchored and already handles the KIIT/IITM lookalike traps | **BUILD** — extract the regex to a shared module, do not fork it |
| **Mode** (Online / Offline / Hybrid) | `meta.mode` — 64 distinct, and **dirty**: `online` 342, `offline` 307, `Online` 94 (case variant), plus leaked venue names (`Jaipur`, `University of Sydney`, `KIT main building`, `Pitkin, CO, USA`) | **BUILD WITH NORMALISATION** — case-fold, map anything not online/offline/hybrid to unknown, and exclude unknown from the facet rather than showing a 61-option dropdown |
| **Domain** (AI/ML, Web, FinTech, …) | `meta.skills` — **582 distinct**, top values are soft skills (`Problem Solving` 284, `Teamwork and Collaboration` 107) not domains | **NEEDS A MAPPING** — do not surface raw skills. Curate a domain→skills map, the way `role-skills-map.json` already works |
| **Location India / Abroad + City** | `country` is **NULL on 479 of 843 (57%)** | **PARTIAL** — an India/Abroad toggle silently hides the majority. Ship only with an explicit "unspecified" bucket, or defer. **City: not stored at all — do not build.** |
| **Team** (Individual / Team + size range) | Not present in any column or meta key | **DO NOT BUILD** — no data |
| **Eligibility** (Students / Professionals / Open) | `meta.eligibility` 272, `meta.eligible_experienced_only` 272 | **BUILD** at low fidelity (student vs experienced), not the four requested buckets |

**Prize-pool caveat:** `currency` is a font-awesome token (`fa-rupee`), not ISO 4217. A range filter
that mixes INR and USD cash values without normalising is Law 07 again in miniature. Either filter
within a single currency or normalise before comparing.

---

## 2. Research & Programmes — half buildable

Checked against the 82 active `programmes` rows.

| Requested filter | Backing | Verdict |
|---|---|---|
| **Programme category** | `category` — 9 clean values | **BUILD** (already the existing pills; expose inside Filters too) |
| **Field / domain** | `tags` jsonb — 20-term controlled vocabulary: `research` 56, `science` 30, `international` 26, `cs` 25, `engineering` 15, `government` 14, `policy` 10, `open-source` 9, `ai` 7 … | **BUILD** — small, clean, already curated |
| **Application status** | `programme_editions.status` — expected/announced/open/closed | **BUILD**, but note **78 of 84 editions are `expected`**, so the facet is near-degenerate until the promotion work in `RESEARCH-INGESTION-HANDOFF.md` Part 3 lands |
| **Organizer** (searchable) | `organiser` — 82/82, free text | **BUILD** — derive the list, do not hard-code |
| **Institution type** (IIT / IISc / IISER / NIT / TIFR / CSIR / …) | Derivable from `organiser` via the shared reputed-organiser regex | **BUILD** — same shared module as §1 |
| **Location India / Abroad + Country** | `country` is `IN` on 45 and **NULL on 37**. There are no other country values at all | **PARTIAL** — India/Abroad works if NULL is treated as "not India", but that is an assumption, not data. **Country/City dropdown: do not build**, there is nothing to populate it with |
| **Mode** (On-site / Remote / Hybrid) | **No column, no field, nothing** | **DO NOT BUILD** |
| **Eligibility** (UG / PG / PhD + year) | `eligibility` is **free prose**, 62/82 — e.g. *"B.Sc., M.Sc., or equivalent students may apply according to the current IISER Mohali criteria."* | **DO NOT BUILD** from current data — needs a structured field at ingestion |
| **Funding** (Paid / Unpaid / Fully Funded) | No column | **DO NOT BUILD** |
| **Duration** (<1mo / 1–3 / …) | `typical_window` is free prose, and the registry handoff already records that only **7 of 82** contain a parseable month | **DO NOT BUILD** |

---

## 3. Build order

**Part A — shared foundations** (do first, both pages depend on it)
1. Extract `_REPUTED_ORGANISER_REGEX` from `pipeline/notifications.py` into a shared module.
   It is already correct and lookalike-safe; forking it would guarantee drift.
2. A faceting endpoint per page that returns counts per option, derived from live data. Counts are
   what stop a user selecting a filter that returns nothing.
3. URL-param contract: AND across groups, OR within a group. Multi-select values comma-joined.
   Must not break existing pagination, sorting or the cards.

**Part B — Competitions filters** (largest backed set — highest value)
Type, Registration, Deadline, Organizer, Organizer type, Mode (normalised), Prize range.

**Part C — Research/Programmes filters**
Category, Field (tags), Organizer, Institution type, Application status.

**Part D — UI**
Filters button beside the existing controls; desktop popover/sidebar, mobile bottom sheet; active
chips; result count; Clear all. **Keep the existing category pills** and the cream/brown language,
type scale, cards and spacing exactly as they are.

**Part E — deferred, needs ingestion first**
Mode/eligibility/funding/duration for programmes; team size and city for competitions; a curated
domain→skills map. Each needs a new structured field at ingestion time, not a UI change.

---

## 4. Performance constraints

- Facet counts must not be an N+1 per option. One grouped query per facet group, cached at the
  existing `read_cache_ttl_seconds` (900s) — filters change far slower than that.
- The feed already has ISR caching with per-fetch `revalidateSeconds`. A filter that pushes routes
  to dynamic rendering would undo the browse-caching work and re-open the Vercel CPU incident.
  **Any new route must keep `generateStaticParams` alongside `revalidate`** — Next 16 silently
  ignores ISR without it, which is the eleven-day bug already recorded in this repo.
- Debounce the searchable organizer inputs; do not fire a request per keystroke.
