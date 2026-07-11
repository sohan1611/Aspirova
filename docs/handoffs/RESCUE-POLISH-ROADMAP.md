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
