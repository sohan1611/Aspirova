# 07 — Implementation Roadmap

*Author: Chief Architect. Built for a SOLO student founder + one coding agent (Sonnet now, possibly Codex later). The sequencing rule: **derisk early, defer cost, prove the loop before adding intelligence.** Timelines assume part-time student bandwidth.*

---

## Sequencing philosophy

1. **Prove the core loop first** (discover → dedup → serve a real, useful free feed). If that isn't valuable, nothing downstream matters.
2. **Monetize only after the free product is genuinely good** — a paywall on a weak product just advertises the weakness.
3. **Add AI only once there's content + users to justify it** (and the cost discipline of Doc 05 is in place).
4. **Scale infrastructure only on measured triggers** (Doc 02 §5), never in anticipation.
5. **Mobile last** — a responsive PWA covers 90% of mobile value at ~0% of native-app cost until scale justifies it.

> Each phase ends with a **Gate** — the concrete condition that says "you're ready to advance." Do not start the next phase until the gate is met. This is how a solo founder avoids half-finishing five things.

---

## Phase 1 — MVP (the core loop)

**Objective:** a genuinely useful *free* product that aggregates real, deduplicated opportunities from ATS sources, served on fast, SEO-indexable pages. No payments, no heavy AI.

**Deliverables:**
- `SourceAdapter` interface + pipeline skeleton: `fetch → raw_listings → normalize → canonicalize/dedup` (Doc 04).
- **`GreenhouseAdapter`** (ATS-first, parameterized by board token) — proves the model; then 5–20 seeded companies.
- Postgres core schema (Doc 03): `sources, companies, raw_listings, opportunities, opportunity_sources, tags, users, bookmarks`.
- **Dedup engine v1** (blocking + trigram + simple rules; embeddings optional here).
- Feed + **`tsvector` keyword search** + filters (category, remote, deadline).
- **SSR, SEO-indexable `/opportunity/{slug}` pages** (the growth surface, Doc 01).
- Deadline view / "closing soon" + bookmarks.
- Basic auth (Supabase Auth).
- GitHub Actions cron running the crawl (Tier-1 subset).

**Risks:** scope creep (resist AI/payments now); dedup quality (start simple, iterate); first adapter teaches the abstraction — expect to refactor `SourceAdapter` once.

**Timeline:** ~4–7 weeks part-time.

**Expected cost:** **~$7–10/mo** (Render $7 + domain; everything else free tier).

**Gate to Phase 2:** real deduplicated opportunities flowing daily from ≥1 ATS; a stranger can search the feed, open an SSR opportunity page, and bookmark — and finds it useful. ≥1 source crawling reliably on schedule.

---

## Phase 2 — Production-ready platform (monetize)

**Objective:** turn the useful free product into a business: payments, plans, alerts, reliability.

**Deliverables:**
- **Razorpay** integration (monthly + annual cycles); seed the 5 canonical plan rows — Pro Lite ₹39/mo · ₹399/yr, Pro ₹49/mo · ₹499/yr (Doc 06 §1) — with **annual as the default highlighted option** showing the ~15% saving; `plans` + `subscriptions` (Doc 03).
- **Config-driven plan gating** via `plans.features` + a single `can(user, feature)` helper (Docs 02/08). Free / Pro Lite / Pro live.
- **Dream-company alerts** + **daily digest email** (Resend) + **notification worker** (GH Actions cron) with batching + frequency caps.
- **Change detection** (`source_state` hashing) wired *before* any future enrichment (cost guard, Doc 04 §6).
- **`LeverAdapter` + `AshbyAdapter`** + first **best-effort aggregator adapter** (robots-respecting, link-out-not-mirror, `legal_status` kill-switch).
- Tier-2/Tier-3 crawl schedules; **Hidden Opportunities** sourcing (long-tail Tier-3) begins.
- Observability: `crawl_runs`, adapter-failure alerts; **backups** (Supabase + independent nightly `pg_dump` → R2/B2, restore-tested).

**Risks:** involuntary churn at micro-price (mitigate with annual prepay); aggregator legal/ToS (keep best-effort + link-out, get a lawyer's read before pushing paid hard — Doc 01 R1/Doc 04 §10); email deliverability (SPF/DKIM/DMARC from day one).

**Timeline:** ~5–8 weeks part-time.

**Expected cost:** **~$8–15/mo** (still mostly free tiers; email/payment small).

**Gate to Phase 3:** payments work end-to-end (incl. annual); a Pro user receives a real dream-company alert + daily digest; ≥3 ATS adapters + 1 aggregator running with backups and a tested restore.

---

## Phase 3 — AI features (the Pro hook)

**Objective:** ship the personalization that drives Pro conversion (Doc 06 lever #1), under strict cost discipline (Doc 05).

**Deliverables:**
- **Enrichment pipeline:** summary + tags + **embedding** generated **once per canonical opp, after dedup + change detection**, idempotent (`ai_client` abstraction).
- **Resume Match:** embed resume once per version; match = **pgvector cosine top-K — NO per-match LLM**; cached per `(user, resume_version)`.
- **Career Copilot:** Pro-gated, **Upstash rate-limited**, RAG over retrieved opps, cheapest model, concise outputs, shared-answer cache.
- **Hidden Opportunities** flag (classification once per opp; plan-gated).
- **Weekly Career Report** (templated assembly from precomputed data; ≤1 short cached/cohort LLM intro).
- **Reopen Prediction** (statistical from `posted_at` history + curated cycles — **not** "will this student get in").
- `ai_usage` logging + **daily spend alarm + graceful degradation**.

**Risks:** AI cost blowout if discipline slips (the alarm + idempotency + change-detection gating are the guardrails); hallucinated opportunities in Copilot (ground in retrieved data, label everything — Doc 05 §6); Match quality (tune embeddings, gather feedback).

**Timeline:** ~6–9 weeks part-time.

**Expected cost:** **~$20–40/mo** at the user scale you'll be at (AI is fixed-ish, Doc 06).

**Gate to Phase 4:** Resume Match returns sensible ranked results with zero per-match LLM calls; Copilot is gated, capped, and cached; AI spend is tracked and within the modeled flat band; conversion to Pro is measurably moving.

---

## Phase 4 — Scaling (growth + the real business)

**Objective:** grow users near-zero-CAC and unlock the profit layer (Doc 06 levers #2, #4).

**Deliverables:**
- **Referral/viral loops live** (schema already exists, Doc 03): invite-for-Pro, FOMO/deadline shares, shareable reports; instrument `k`.
- **Campus-ambassador program** + leaderboard (the zero-CAC engine, Doc 01 §8).
- **SEO content engine** — every opportunity page optimized; long-tail "X internship 2026 last date" capture.
- **B2B campus-license MVP** (the margin maker, Doc 06 lever #2) — schema `org_id`/license hooks, a basic admin view for a placement cell.
- **Ethical sponsored-listing** mechanism (clearly labeled).
- **Cost optimization at scale:** Resend → **SES**, caching hardening, Supabase Pro, measurement-triggered upgrades (Doc 02 §5).
- Reliability hardening: circuit breakers, dead-letter review, SLOs.

**Risks:** viral loops that don't move `k` (kill them fast); B2B sales is a new muscle for a solo founder (start with the founder's own campus); cost creep as email/AI grow (the §6 reductions in Doc 06 must be active).

**Timeline:** ~8–12 weeks part-time, ongoing.

**Expected cost:** **~$40–120/mo** depending on user scale (Doc 06 tables).

**Gate to Phase 5:** `k` measurably > 0 and improving; ≥1 paying campus license OR clear B2C-profitability path at current conversion; infra costs tracking the model, not exceeding it.

---

## Phase 5 — Mobile app & expansion

**Objective:** meet students where they are (mobile-first) and broaden the category.

**Deliverables:**
- **PWA → native** (React Native / Expo to reuse skills) with **push notifications** (cheaper + higher-engagement than email for instant alerts).
- Segment/geographic expansion (more colleges, more program types, possibly beyond India).
- **Deeper B2B** (multi-campus dashboards, analytics for placement cells).
- Possible **public API / partnerships** (the opportunity graph as a product).

**Risks:** native app maintenance overhead for a solo founder (only do this once retention + scale justify it — don't build the app to chase vanity); expansion diluting focus before the wedge is won.

**Timeline:** ~10–16 weeks part-time, ongoing.

**Expected cost:** scales with users per Doc 06; push notifications *reduce* per-message cost vs email.

**Gate:** strong retention + a clear, profitable engine before investing in native + expansion. Don't expand a leaky bucket.

---

## Cross-phase guardrails (apply in every phase)

- **No crawler ever runs on the Render dyno** (Doc 02/04).
- **No per-user AI on the hot path; no per-match LLM** (Doc 05).
- **Config-driven gating only** (`plans.features`).
- **Scale on measured triggers, not anticipation.**
- **Each phase ships behind its gate** — a solo founder's scarcest resource is focus; the gates protect it.

---

## HANDOFF TO ENGINEERING

1. **Treat phases as hard sequencing.** Do not start Phase N+1 until Phase N's gate is met. If tempted to pull a later feature forward (e.g., Copilot in Phase 1), escalate to the architect — usually the answer is no.
2. **Phase 1 is ATS-first.** The very first adapter is `GreenhouseAdapter`. Get one opportunity end-to-end (crawl → canonical → SSR page → bookmark) before breadth.
3. **Build cost guards before the cost exists:** change detection (Phase 2) and `ai_client` + `ai_usage` + spend alarm land *with* the first AI feature (Phase 3), never after.
4. **Schema-ahead for later phases:** referral, `org_id`/license, and `sponsored` fields exist in the schema by Phase 2–4 entry so growth/B2B aren't painful retrofits (Doc 03/06).
5. **Every phase ends with the gate's metric instrumented** — you can't pass a gate you can't measure.

**Definition of done for the roadmap:** a solo founder + coding agent can execute Phase 1 to a useful free product on ~$7–10/mo, gate into monetization, then layer AI and growth without ever violating the cost or architecture canon — each phase shippable, measured, and reversible.
