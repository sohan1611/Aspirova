# PHASE 4 HANDOFF — Growth Loops (the zero-CAC engine)

*From: Chief Architect (Opus) · To: the engineer (Codex or Sonnet — founder picks per part). Status: ISSUED, but STARTED EARLY and PARTIALLY — see §0. Implements Doc 07 Phase 4 (referral/viral loops, campus ambassadors, SEO content engine, B2B licenses) under Doc 06's cost model.*

---

## 0. Sequencing ruling (why this starts before its formal gate)

Doc 07's gate to *enter* Phase 4 is "Phase 3 done + Pro conversion measurably moving." That gate is **not yet met** (AI go-live is pending the founder's API keys; payments are deferred to a later evening). **Architect ruling:** to use the pre-go-live window productively, begin **only the parts of Phase 4 that need neither AI keys nor payments** now; hold the conversion/payment-dependent parts until the real gate. This is a deliberate, limited early start recorded in the Decision log — not silent gate-jumping.

**Buildable now (key-free, payment-free):**
- **Part 1 — SEO content engine.** Fully independent. Amplifies the SSR opportunity pages that are the organic growth surface (Doc 01). **DO FIRST.**
- **Part 2 — Referral / invite loop.** Key-free; the "invite reward" is granted as a **complimentary Pro `subscription` row** (the gating seam already reads subscriptions), so it needs NO Razorpay. Buildable now.

**Hold for the gate (need payments / real conversion data):**
- **Part 3 — Campus-ambassador program + leaderboard** (builds on referrals; real value once there's Pro to earn).
- **Part 4 — B2B campus-license MVP** (`org_id`/license schema + a placement-cell admin view; the margin-maker, Doc 06 lever #2).
- **Part 5 — Ethical sponsored listings + cost optimization at scale** (Resend→SES, caching hardening, measurement-triggered upgrades — Doc 02 §5).

---

## 1. Part 1 — SEO content engine (DO NOW; key-free, payment-free)

**Objective:** make every opportunity maximally discoverable in organic search — the near-zero-CAC channel (Doc 01/07). Greenfield: the app currently has **no** sitemap, robots, or structured data.

**Deliverables:**
- **JSON-LD `JobPosting` structured data** on `/opportunity/{slug}` (Schema.org) — title, hiringOrganization, datePosted, validThrough (from deadline when explicit), applicantLocationRequirements/jobLocationType (remote), url → the real apply link. This is what surfaces a listing in Google's job results. Emit only fields we actually have; never fabricate (Doc 01 R5) — e.g. omit `validThrough` when the deadline is inferred/unknown.
- **Dynamic `sitemap.xml`** (Next.js `app/sitemap.ts`) — all active opportunity slugs + the static routes (/, /pricing, /resume, /copilot), with `lastModified` from `last_seen_at`. Needs the backend to expose the slug list: add a lightweight, cacheable `GET /sitemap` (or `/opportunities/slugs`) returning `[{slug, last_seen_at}]` for active opps (read-only, no auth, cache-friendly — reuse the Part-2.1 read-cache seam).
- **`robots.txt`** (`app/robots.ts`) — allow crawling, point at the sitemap; keep `/style` and any dev-only routes disallowed.
- **Canonical URLs + richer metadata** on the detail page (canonical to the Aspirova slug URL; keep the existing OG/title work from Phase 2.5).
- **(Optional, if clean) long-tail landing pages** — e.g. `/internships`, `/remote`, or company pages — server-rendered, indexable, linking into the feed. Only if it doesn't complicate the build; otherwise defer.

**Guardrails:** do NOT regress SSR (the detail/feed pages stay server-rendered — that's the whole point); the sitemap endpoint must be cheap (cached, no N+1); never emit structured data we can't stand behind (labeling/trust, Doc 01 R5); no keys, no payments, no AI.

**Acceptance:** `/opportunity/{slug}` carries valid `JobPosting` JSON-LD (validates against Schema.org); `sitemap.xml` lists all active slugs + static routes; `robots.txt` references it; `next build` stays green with SSR intact; the new backend slug endpoint is cached and covered by a test.

---

## 2. Part 2 — Referral / invite loop (buildable now; comp-Pro reward, no Razorpay)

**Objective:** instrument and drive the viral loop (Doc 06 lever #1). The `users.referred_by` column already exists (Doc 03).

**Shape (to be detailed in its own spec when we start it):** each user gets a unique invite code/link; a new signup via that link sets `referred_by`; a successful referral grants the referrer a **complimentary Pro `subscription` row** (status `active`, a bounded term) — no payment involved, and it flows through `can()` unchanged. Instrument the viral coefficient `k` (invites sent → signups → activations). Shareable opportunity/deadline cards for FOMO distribution.

**Why it needs no payments:** the reward is a comp subscription row, not a purchase; Razorpay stays out of scope until the founder wires real billing.

---

## 3. HANDOFF TO ENGINEERING

1. **Start with Part 1 (SEO).** It is fully key/payment-free and compounds over time (indexing lag), so earlier is better.
2. **Protect the SSR growth surface** — every SEO change must keep the opportunity pages server-rendered; measure the build output (`ƒ` for detail/feed).
3. **Never emit structured data we can't back** — omit fields we don't reliably have; trust is the product (Doc 01 R5).
4. **Do not touch payments or AI keys** in Parts 1–2; those parts are defined precisely to avoid needing them.
5. **Each part: implement → verify → commit on a branch → CI green**, authored `sohan1611`-only, same cadence as Phase 3.
