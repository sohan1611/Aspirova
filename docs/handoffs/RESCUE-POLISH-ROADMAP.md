# Rescue & Polish Roadmap — smooth, trustworthy customer experience

**Architect:** Claude Opus. **Engineer:** Codex (gpt-5.6-sol @ ultra). Written 2026-07-11.
Driven by founder-reported issues on the live site. Fix **one item per branch**, Claude verifies + merges each. Trust + smoothness are the bar.

---

## RP-0 — Old/expired competition dates showing ✅ DONE (2026-07-11)
Feb/Mar-2026 (long-closed) competitions were showing as if live. Fixed by the 14-day lifecycle (merge 6970aac) + pruning **1,180** stale competitions. Now: open → "Registers by"; closed ≤14d → "Registrations closed"; closed >14d → deleted daily. 0 stale remain.

## RP-1 — Date format → DD/MM/YYYY (frontend, quick)
Detail page shows "Deadline: 3/1/2026" (US M/D/Y) — founder wants **DD/MM/YYYY** (Indian). Fix EVERY user-facing date (opportunity detail deadline, card "Closes/Registers by …", any `toLocaleDateString`) to a DD/MM/YYYY (or "1 Mar 2026") format via one shared `formatDate` helper using `en-GB`/`en-IN`. No US-format dates anywhere.

## RP-2 — Perceived performance: kill the ~1s "frozen" feel (frontend + cache)
Measured: /feed API 0.3–1.2s (cold higher; Vercel→Render SG→Supabase Mumbai). The feed is a server component, so each category/filter/sort tap is a full navigation with **no loading state** → the page looks frozen for ~1s. Fixes (perceived-perf first, cheap + safe):
1. **`loading.tsx`** for `/(feed)`, `/competitions`, `/companies` → an instant Almanac skeleton (cards shimmer) shows the moment a tap happens.
2. **`useTransition`** in SearchFilters + FeedViewControls + sort/category controls → `startTransition(() => router.push(...))`, show a subtle pending state on the controls; navigation stops blocking the click.
3. **Cache the /feed + /companies GET responses** (Upstash, short TTL ~60–120s, key = full querystring) to cut warm latency for repeated filters. (Upstash is already wired in Phase 2 — reuse it; don't cache authenticated/user-specific responses.)
4. Confirm the competition-exclusion subquery is index-supported (deadline + category partial index) so it doesn't add latency.
Target: taps feel instant (skeleton < 100ms), warm feed < 300ms.

## RP-3 — Separate competitions from the roles feed + surface PPI/PPO contests
Founder: don't mix hackathons/contests/competitions into the internships/jobs view; give them their own home. BUT contests that promise an internship/job on qualifying MAY appear in roles too.
1. **Home feed defaults to roles** (internship+job); competitions live on **/competitions** (and only appear in the main feed when the user explicitly picks Hackathons/Competitions). Wire the home feed to `kind=roles` by default.
2. **PPI/PPO flag:** Unstop items carry `pre_placement_internship` / `pre_placement_opportunity` (seen in prize objects). Detect them in the Unstop adapter → set `meta.offers_ppi`/`offers_ppo`. Such competitions ALSO surface in the internships/jobs feed (via an OR on the flag) and show an "Offers internship/PPO" badge. This is the "contest → job" bridge the founder wants.

## RP-4 — Internship track filter: Company · College · Research · Learning
Founder wants to filter internships by kind. Add an internship **track** dimension (`meta.track`):
- **company** — corporate/ATS + Amazon (default for role adapters).
- **college** — institute-hosted (IIT/NIT/IISc/IISER) internships.
- **research** — research programs/fellowships (subsumes the earlier research-vertical task #47).
- **learning** — training/skill internships (many Unstop "internship" listings).
Classify on ingest (by source + title/organizer heuristics) into `meta.track`; add a "Track" filter group in the Filter popover (Company/College/Research/Learning) backed by a `track` query param. Seed the College/Research tracks from the curated institute/research list (was #47) with **verified apply URLs**.

## RP-5 — Google/MS/Apple "straight to source" cards + flagship programs (was #46)
Search for Google/Microsoft/Apple → branded card (logo) → page with honest "we link to source" message + verified careers redirect + a **Flagship annual programs** list (GSoC, Solution Challenge, STEP, Girl Hackathon; Imagine Cup, Engage, Explore; Swift Student Challenge) with *tentative* timelines + verified official links. (Details + verified dates already curated in task #46.)

---

## Build order (each = one Codex branch, Claude verifies + merges)
1. **RP-1 + RP-2** (frontend polish: DD/MM dates + loading skeletons + useTransition) — quick, high-impact, safe. *(do first)*
2. **RP-2 caching** (Upstash on /feed + /companies) — backend.
3. **RP-3** (roles/competitions split + PPI/PPO bridge) — backend + frontend.
4. **RP-4** (internship tracks + College/Research curated data + filter) — backend + data + frontend.
5. **RP-5** (Google/MS/Apple cards + programs) — frontend-leaning.

## Guardrails
- Every outbound link (careers, apply, programs) fetch-verified before shipping (trust).
- No US date formats. No fake/stale data. No ToS-violating scraping.
- Each item ships only after ruff/black/pytest + eslint/tsc/build + a browser check.
- Stay within Supabase Pro + GitHub Actions (3,000 min) limits.

---

## v2 — Extensive site audit (Opus, 2026-07-11)
Measured on prod (9,706 active opps: 233 internships / 8,950 jobs / 234 hackathon / 289 competition).

**A0 — India internships = 0; all 233 internships have NO deadline; all Amazon/US ATS.** Root cause: Unstop *internships* (10,000, Indian, with deadlines) were never crawled — only its competitions/hackathons. → FIXING (feat/india-internships, br6ow7vqo): add opportunity=internships + extend the 14-day deadline lifecycle to internships. **[P0]**

**A1 — Home "roles" feed leads with PPI/PPO competitions** (recently crawled, sort=recent) so real internships/jobs get buried. → order genuine internships/jobs first; PPI/PPO competitions after. **[P1]**

**A2 — 816 duplicate multi-location role clusters** (e.g. MongoDB "Enterprise Account Executive" ×19 cities, Databricks roles ×13–15) bloat the feed with near-identical cards. → group multi-location roles into one card ("+18 locations") or de-dupe the feed by (title, company) with a location roll-up. **[P1]**

**A3 — Junk/empty listings:** 1 empty title, 1 "Test 1 posting", 9 roles missing location. → drop empty-title/obvious-test rows on ingest; require a location for role listings or show "Location N/A". **[P2]**

**A4 — /companies counts competitions as "open roles"** and lists small competition-organizers (colleges/clubs) as if employers. → the Companies directory should reflect employers with real internship/job counts (exclude competition-only organizers, or label "N events"). **[P2]**

**A5 — ATS/Amazon internships legitimately have no deadline** → show "Posted <n> ago" (not implying an expiry); never show a stale "months ago with no action". **[P2, part of A0 card work]**

Still open from v1: RP-4 (internship tracks Company/College/Research/Learning + institute/research curated data), RP-5 (Google/MS/Apple source-cards + flagship programs).

### Fix order (one Codex branch each, Claude verifies+merges)
1. **A0** India internships + internship lifecycle (in progress). 2. **A1** roles-first ordering. 3. **A2** multi-location de-dupe. 4. **A3** junk filter. 5. **A4** companies-directory = employers. 6. RP-4 tracks. 7. RP-5 MAANG cards.

---

## Phase 6 — The "Never-Miss" Command Center (the reason to pay) — Opus, 2026-07-11
Founder's core doubt: "if it just redirects to Unstop, why pay?" Answer: Aspirova is the personal scout that watches every source + never lets you miss. The moat = breadth × personalization × proactivity × intelligence. Most exists (Phase 3) but is buried and was running on wrong deadlines (now fixed). Make it the hero:

**C1 — Closing-soon deadline alerts (NEW, highest value; the anti-Flipkart).** notification_worker gains `--closing-soon`: for each opted-in user, email the bookmarked (and, for Pro, resume-matched) opportunities whose deadline is within N days (default 3). Dedup via the notifications table; gate by plan/prefs; wire into the daily cron. Unblocked now that deadlines are correct. This is THE "never miss another Flipkart" feature.

**C2 — "My Opportunities" tracker page (NEW).** A dashboard of the user's bookmarks with deadline countdowns ("Closes in 3 days"), urgency-sorted, split Open / Closing-soon / Closed. The personal command center + the home for the alerts. Bookmarks already exist.

**C3 — Personalized "For You" (enhance).** Resume-matched opportunities as a first-class tab/front-door for logged-in users with a resume (Resume Match exists at /resume — surface it as "For You").

**C4 — Sharpen free vs paid.** Free = browse + limited bookmarks. Paid = closing-soon + dream alerts + unlimited tracking + For-You + Copilot. Make the paid value legible on pricing + at the gates.

### Overall remaining order
1. A1 feed ordering (in progress). 2. A2 multi-location de-dupe. 3. **C1 closing-soon alerts** (high value, unblocked). 4. C2 tracker page. 5. A3 junk, A4 companies-directory. 6. C3 For-You. 7. RP-4 tracks, RP-5 MAANG cards. 8. C4 pricing clarity.

**A6 — meta payload bloat:** Unstop meta.skills stores full nested objects (id/pivot/ai_generated per skill) → /feed responses are huge → slower transfer (hurts the perceived-perf goal). → trim meta to essentials (skill NAMES only, drop pivot/prizes internals) in the Unstop adapter + a one-time backfill. **[P1, perf]**
