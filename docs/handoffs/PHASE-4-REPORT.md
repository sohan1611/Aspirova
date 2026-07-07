# PHASE 4 REPORT — Growth Loops (progress: Parts 1–2 + source/coverage work)

*From: Chief Architect (Opus). Status of the **buildable-now, key-free, payment-free** half of Phase 4 (see [PHASE-4-HANDOFF.md](PHASE-4-HANDOFF.md) §0). Everything below is **merged to `master`, CI-green, and live in production**. Built via the Claude→Codex delegation loop (work orders 14–21 in `.agents/collab-log.md`), every commit authored `sohan1611`-only.*

---

## 1. What was built (all live)

**Part 1 — SEO content engine** (Parts 1 / 1b / 1c):
- `JobPosting` JSON-LD on the opportunity detail (fields we actually have; `validThrough` only on explicit deadlines — Doc 01 R5), dynamic `sitemap.xml` + `robots.txt`, canonical URLs, and a cached backend `/sitemap-opportunities` + `/sitemap-companies`.
- Long-tail SSR landing pages: `/internships`, `/remote`, `/jobs`, and `/companies/[slug]` (backed by a new `/company/{slug}` endpoint).
- Dynamic `next/og` share cards (root brand card + opportunity + company), each falling back to the brand card on any error so a backend-less build never breaks; Twitter card → `summary_large_image`.

**Part 2 — Referral / invite loop** (2a backend, 2b frontend, 2c share):
- `users.invite_code` (additive migration `f2a9c7d4e1b0`, applied to prod), `core/referral.py` (unique-code gen, guarded `record_referral` — self-referral + set-once + row-lock, atomic set-referrer-and-reward), `/referral/me` + `/referral/claim`.
- **Reward = a bounded 30-day comp `pro_lite_monthly` subscription** (Ruling A): unlocks the non-AI Pro features, leaves `copilot`/`resume_match`/`prediction` OFF → **zero marginal AI cost** at go-live. No Razorpay.
- **Gating refinement** (Ruling B, architect-approved amendment of the single `can()` seam): comp subs (`razorpay_sub_id IS NULL`) grant features only while `current_period_end` is null or in the future; **Razorpay subs are byte-for-byte unchanged** (first `OR` branch short-circuits) so bounded comp terms expire without a cron and no paying user can be affected.
- Frontend: `/referral` invite page, a silent global first-touch `?ref=` capture (auto-claims once on sign-in), an `Invite` nav link, and a `Share` button on opportunity pages that appends the signed-in user's `?ref=` so shares land on the Part-1c OG card.

**Source expansion — SmartRecruiters (4th ATS adapter):**
- New `SmartRecruitersAdapter` via the `SourceAdapter` seam (the ingestion pipeline is unchanged; `run_tier(1)` auto-discovers it). Seeded Wise / Western Digital / Universal Music Group. **+598 real opportunities ingested** (catalog 3,050 → 3,669).

**Companies directory:**
- `GET /companies` (one GROUP BY over companies with ≥1 active opp, ordered by open-role count; cached + IP-rate-limited) and a browsable SSR `/companies` index (138 companies) with a footer + sitemap entry.

## 2. How it was verified (not assumed)
- **Backend:** ruff + black; new tests per part; full migration up/down on a throwaway `pgvector/pgvector:pg17` container; the full suite against the container and/or production; **zero test-row-leak** checks after per-op commits. The referral migration was applied to prod (founder-authorized) and the full suite ran green vs prod (173).
- **Crawler:** an end-to-end **live container crawl** (real SmartRecruiters HTTP → throwaway DB) proved real opportunities ingest with clean locations, real apply URLs, and stripped HTML **before** any prod seed. Prod activation (seed + `workflow_dispatch` crawl) was founder-authorized; result confirmed in the live feed.
- **Frontend:** eslint + tsc + `pnpm build` with **no backend** (SSR routes stay `ƒ`, no `/pricing`-style prerender break); live browser preview against production data for every user-facing surface (OG PNGs, `/referral` capture, `/companies` directory rendering 138 real companies).

## 3. Real defects & incidents found and fixed during verification
- **OG-image eslint (`react-hooks/error-boundaries`)** — JSX was constructed inside a `try/catch`; restructured so the try computes only data and the `ImageResponse` is built once after it.
- **Referral frontend `react-hooks/set-state-in-effect`** — reworked to mirror `ResumeMatchPage` (no synchronous setState in the effect) and read `window.location.origin` via the repo's `useHydrated()` hook.
- **Thin-description curation** — a live crawl showed Visa's SmartRecruiters postings are syndication shells (one empty description); Visa dropped from the seed (Doc 01 R5). Wise/WD/UMG return full descriptions.
- **Crawl duration** — SmartRecruiters fetches a per-posting detail endpoint every crawl (the board fingerprint is computed after `fetch()`), pushing the first real Tier-1 crawl to **24m44s / 25m**. Stopgap: `crawl-tier1.yml` timeout raised 25 → 40. Proper fix (lazy/only-changed detail fetch) is a tracked follow-up.
- **Red master after the SR seed** — two independent causes, both fixed: (1) SmartRecruiters board tokens are capitalized, so `company_slug = board_token` produced capitalized slugs that broke the company-sitemap sort invariant → `board_token.lower()` (no-op for the existing lowercase adapters) + a founder-authorized 3-row prod slug UPDATE; (2) `test_runner_isolation` derived opportunity slugs from a fixed company name, so two overlapping CI jobs (a double-push) collided on `opportunities_slug_key` → made the seeded company name unique per run. A later `/companies` test asserted a name-tiebreak ordering with Python string comparison over real prod rows → relaxed to the collation-independent count-non-increasing invariant.

## 4. Production state (verified live)
- Catalog: **3,669 active opportunities across 138 companies** (4 ATS/aggregator sources: Greenhouse, Lever, Ashby, SmartRecruiters + the RemoteOK aggregator).
- Endpoints live on Render: `/referral/me`, `/referral/claim`, `/companies`. Pages live on Vercel: `/referral`, `/companies`, the OG image routes, all landing pages.
- All AI remains **key-guarded and dormant at $0 spend** (Phase-3 features unchanged). No payments code activated.
- Master CI green.

## 5. In-flight and deferred
- **Running now (founder-started, parallel sessions):** (a) location display trailing-comma cleanup; (b) the SmartRecruiters lazy/only-changed detail-fetch optimization (which will let the crawl timeout drop back toward 25 min and unblock the large held-out boards, BoschGroup 4667 + DeliveryHero 1110).
- **Deferred to the real Doc-07 gate** (need payments live + real conversion/users): Part 3 (campus ambassadors + leaderboard), Part 4 (B2B campus licenses), Part 5 (sponsored listings + Resend→SES cost optimization). Not started, by architect ruling — building them ahead of users would be gate-jumping.

## 6. What's next
1. **Founder-led, evening:** AI go-live (Anthropic + OpenAI keys → the enrichment / resume-match / copilot / weekly-report features activate; run `enrich_worker --limit N` as a cost dry-run first, then flip on) and Razorpay wiring (test-mode first; the webhook out-of-order/replay fix folds in here).
2. **After the lazy-detail task lands:** resume catalog expansion (more companies on the cheap one-call adapters + the held-out SmartRecruiters boards) with the crawl back within budget.
3. **Then the Doc-07 gate opens** Parts 3–5 once payments + real conversion data exist.
