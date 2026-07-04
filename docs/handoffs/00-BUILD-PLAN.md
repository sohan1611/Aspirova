# Aspirova — Master Build Plan & Handoff Protocol

*Author: Chief Architect (Opus). This file governs HOW the project gets built and in WHAT order. The implementation agent (Claude Sonnet now, possibly OpenAI Codex later) executes against the per-phase handoff documents in this folder.*

---

## The cadence (how Opus and Sonnet work together)

```
   OPUS                          SONNET                         OPUS
   ────                          ──────                         ────
1. Writes detailed   ──────►  2. Breaks the phase into     ──────►  4. Reviews against the
   PHASE-N handoff             small PARTS and builds              phase gate + HARD RULES,
   (this folder)               them part-by-part, each            then writes PHASE-(N+1)
                               independently testable             handoff
                                      │                                   │
                                      ▼                                   │
                            3. Completes the whole phase,                 │
                               hands back a Phase Report ◄────────────────┘
                               → user pings Opus for review
```

**Rules of the cadence:**
- **Opus writes one phase handoff at a time.** Sonnet does not get the next phase until the current one passes review. This keeps scope tight and lets the architecture self-correct between phases.
- **Sonnet further decomposes each phase into parts** (the handoff suggests a decomposition; Sonnet may refine it). Each part must be independently buildable, testable, and committable.
- **Sonnet never silently deviates from the canon** (`docs/`). If a doc is wrong/unclear/blocking, Sonnet raises an **amendment request** in its Phase Report; Opus amends the doc + adds a Decision-log row. Canon wins until amended.
- **Every phase ends with a Phase Report** (template in §"Phase Report" below) that the user forwards to Opus to trigger review + the next handoff.
- **The merge gate is Doc 08 §3 HARD RULES.** A part that violates a HARD RULE is not "done."

---

## Project status: this is a build-first PROJECT that WILL scale

- Current intent: **build the system** (not yet run commercially). Profit is a reference model (Doc 06), not the immediate goal.
- **But scale-readiness is a first-class requirement.** Do not take shortcuts that block scaling (e.g., hardcoding plan logic, mirroring content, per-user AI, crawling on the web dyno). The canon already encodes the scalable path — follow it. "It's just a project" is **never** a reason to violate a HARD RULE.

---

## The 7 build phases

These are finer execution slices of the 5 strategic phases in [Doc 07](../07-implementation-roadmap.md). Each build phase has a one-line objective and the gate that ends it. Sonnet breaks each into parts.

| Build Phase | Objective | Maps to Doc 07 | Gate (hand back to Opus when…) | Status |
|---|---|---|---|---|
| **1. Foundation & Ingestion Core** | Repo, schema, `SourceAdapter` + `GreenhouseAdapter`, raw→canonical→dedup, GH Actions crawl, change detection | Strategic Phase 1 (MVP) | Real deduplicated opps flow daily from ≥1 ATS into Postgres; runs off Render | **✅ DONE + REVIEWED — [report](PHASE-1-REPORT.md)** |
| **2. Read API, Feed, Search & SSR Pages** | FastAPI read endpoints, `tsvector` search, Next.js feed + SSR `/opportunity/{slug}`, deadline view, bookmarks, basic auth | Strategic Phase 1 (MVP) | A stranger can search, open an SSR opportunity page, sign up, and bookmark | **✅ DONE + REVIEWED** (built alongside Phase 1; live on Vercel + Render) |
| **3. Accounts, Plans, Payments & Gating** | Razorpay (monthly+annual), 5 seeded plan rows, `plans.features` gating + `can()`, subscriptions, dream companies | Strategic Phase 2 | Payments work end-to-end (incl. annual default); Free/Pro Lite/Pro live; gating data-driven | **▶ HANDED OFF — see [PHASE-2-HANDOFF.md](PHASE-2-HANDOFF.md)** |
| **4. Notifications & Reliability** | Notification worker, daily digest (Resend), Pro instant dream-company alerts, frequency caps, more ATS + first aggregator, `crawl_runs` observability, backups | Strategic Phase 2 | Pro user gets a real alert + digest; ≥3 ATS + 1 aggregator; backups restore-tested | **▶ HANDED OFF** (bundled into the Phase 2 handoff with build-phase 3) |
| **5. AI Intelligence Layer** | `ai_client`, enrichment once-per-canonical, embeddings, Resume Match (cosine), Copilot (Pro-gated), Hidden Opps, Weekly Report, Reopen Prediction, spend alarm | Strategic Phase 3 | Match returns sensible results with zero per-match LLM; Copilot gated/capped; AI spend tracked + within band | Pending |
| **6. Growth & B2B** | Referral/viral loops, ambassador program, SEO engine, B2B campus-license MVP, sponsored listings, SES migration, caching hardening | Strategic Phase 4 | `k` measurable + improving; ≥1 campus license or clear profit path; costs tracking the model | Pending |
| **7. Mobile & Expansion** | PWA→native, push notifications, multi-campus B2B dashboards, API/partnerships, expansion | Strategic Phase 5 | Strong retention + profitable engine before investing in native/expansion | Pending |

---

## How Sonnet works inside a phase (binding)

1. **Read all of `docs/` first** — this is the only onboarding (Doc 08 §5). The canon is law.
2. **Decompose the phase into parts** (the handoff proposes a breakdown; refine if needed). Order parts so each is testable on its own and builds on the last.
3. **For each part:** implement → test → self-check against Doc 08 §3 HARD RULES → commit on a branch (never directly on the default branch). Keep parts small.
4. **Route everything through the mandated seams** (`SourceAdapter`, `ai_client`, `can(user, feature)`) — most HARD RULES are satisfied automatically by doing so.
5. **Update `docs/` only via amendment request** — do not edit the canon unilaterally.
6. **When all parts pass the phase gate, write the Phase Report** and stop. Do not start the next phase.

---

## Phase Report (Sonnet fills this at the end of each phase → user forwards to Opus)

```
# PHASE <N> REPORT — <phase name>

## What was built
<parts completed, with a 1-line outcome each>

## Gate evidence
<concrete proof the phase gate is met: commands run, sample data, screenshots, test output, perf numbers>

## Deviations from canon (if any)
<what differed from docs/, and why — each as an amendment request for Opus>

## HARD RULES self-check
<confirm each applicable Doc 08 §3 rule is satisfied; note anything uncertain>

## Cost/perf check
<actual vs the budget in the handoff>

## Open questions / risks for the architect
<anything Opus should decide before the next phase>

## Suggested next-phase notes
<things learned this phase that should shape the next handoff>
```

---

## Index of phase handoffs (Opus writes these one at a time)
- **Phase 1:** [PHASE-1-HANDOFF.md](PHASE-1-HANDOFF.md) — *written, active*
- Phase 2–7: written by Opus after each prior phase passes review.

> Engineers: this protocol and the per-phase handoffs sit **on top of** the canon in `docs/`. Where a handoff is silent, the canon governs. Where the canon is silent, raise it to the architect.
