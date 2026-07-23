# Smart Profile — Onboarding Taxonomy · Personalized Feed · Resume Skills + ATS

*Architect: Claude Opus. Engineer: Codex. Status: ISSUED (Phase A first, per founder). Deterministic-first — NO new AI spend; respects "AI out of scope until Phase 3" (this feature adds zero LLM calls) and the AI-budget rule. Builds on the existing `/for-you` ranking and the Pro-gated embedding resume-match, which stay as-is.*

## 0. Founder decisions (locked)
1. **Resume parsing = deterministic**, browser-side. Extract PDF text with a client library; match against the taxonomy skills; compute an ATS score from a transparent rubric. No LLM. The existing Pro embedding **semantic match** is untouched and remains the paid tier.
2. **Build order: A → B → C.** Ship the taxonomy + smart feed first (immediate, no AI), then resume skills + ATS, then wire skills into ranking.

## 1. What already exists (extend, do not rebuild)
- **Flat interests** (`frontend/lib/interests.ts` + `OnboardingDialog.tsx`): a 10-key single-level picker in localStorage (`aspirova.interests`). **Phase A replaces this** with the 3-level taxonomy while keeping the same localStorage-for-anonymous + event-store pattern.
- **`/for-you`** (`backend/api/for_you.py`): query-time ranking via Postgres FTS (`websearch_to_tsquery` + `ts_rank`) over a per-field keyword map. **No AI, no per-user state.** Phase A feeds richer terms into this same seam.
- **Account persistence** (`backend/api/account.py`, `AccountMe`/`AccountUpdate` in `schemas.py`): `GET/PATCH /account/me`. `users` already carries a JSONB `notification_prefs`. Phase A adds a JSONB profile the same way.
- **Resume** (`backend/api/resume.py`, `pipeline/resume_match.py`, `frontend/components/ResumeMatchPage.tsx`): Pro-gated, takes already-extracted `resume_text`, embeds once per version, cosine-matches. Phase B adds the **PDF→text→skills+ATS** front half; the embedding match stays Pro.
- **Taxonomy canon:** `frontend/lib/taxonomy.json` (authored) — `streams[] → divisions[] → interests[]`, stable `key`s + user-facing `label`s. This is the single source of truth for all three phases.

## 2. Data model (one migration, Phase A)
Add to `users` (all nullable; null = not set, mirrors `notification_prefs`):
- `field_profile jsonb` — `{ "stream": string|null, "divisions": string[], "interests": string[] }` (values are taxonomy keys).
- `skills jsonb` — `[{ "name": string, "source": "resume"|"manual" }]` (Phase B populates; create the column in Phase A's migration so B needs no migration).
- `exposure jsonb` — `{ "experience": string|null, "notes": string|null }` free-form exposure/experience the user can edit (Phase B surfaces; column created now).

Extend `AccountMe` (read) and `AccountUpdate` (partial write) with `field_profile`, `skills`, `exposure`. Validation: `stream` must be a known stream key or null; `divisions`/`interests` filtered to keys that exist under the chosen stream (drop unknowns server-side — never trust client keys); `skills` capped (e.g. ≤100 items, name ≤80 chars); reuse the existing `model_fields_set` partial-update pattern in `update_account_me`.

## 3. Phase A — 3-level onboarding + personalized feed (NO AI)

### A.1 Taxonomy module + profile store (frontend)
- New `frontend/lib/taxonomy.ts`: import `taxonomy.json`, export typed `STREAMS`, plus helpers: `getStream(key)`, `getDivision(streamKey, divKey)`, `interestsFor(streamKey, divisionKeys[])` (deduped union), and `expandToSearchTerms(profile)` → deduped keyword list = each selected interest's optional `keywords[]` if present, else its `label` (labels are already good tsquery terms; do NOT author 250 keyword lists now).
- New `frontend/lib/fieldProfile.ts`: replaces `interests.ts` as the client store. Same external-store pattern (localStorage `aspirova.field_profile`, a change event, `useSyncExternalStore`, SSR-null snapshot, `useHydrated`). Shape = the `field_profile` object. For **signed-in** users it also hydrates from / writes through to `PATCH /account/me` (server is source of truth; localStorage is the anonymous/offline fallback and the pre-hydration seed). Keep `aspirova.country` untouched — it stays the separate country store.
- Migrate legacy `aspirova.interests` best-effort (map old flat keys onto the nearest new interest keys) or cleanly ignore; do not crash on old values.

### A.2 Onboarding (rebuild `OnboardingDialog.tsx`) — three steps
1. **Stream** (single-select): the 16 streams as cards (reuse the existing card/aria pattern already in the dialog).
2. **Division** (single-select): divisions under the chosen stream. If a stream has one division, auto-advance.
3. **Interests** (multi-select): interests under the chosen division(s) — "choose as many as you like", the existing multi-select chip pattern. Country step stays (as today).
- Back/next navigation; the whole selection commits to `fieldProfile` (and `/account/me` if signed in) on finish, then routes to the personalized feed (`view=foryou`) exactly as today. "Skip for now" still works. First-run trigger logic (localStorage `aspirova.onboarded`) unchanged.
- A settings entry point (the existing `requestOnboarding()` event) reopens it to edit later. Also expose the same editor in Account → Profile (a "Fields & interests" block) so it's editable there.

### A.3 Feed ranking (`/for-you` extension, backend)
- Accept a new `terms` query param (CSV, `max_length` bounded like `fields`): the frontend passes `expandToSearchTerms(profile)`. Backend runs the **existing** `websearch_to_tsquery("english", " OR ".join(terms))` path — same safe parser, same `ts_rank` ordering. Keep the old `fields` param working (back-comat) — if `terms` present use it, else fall back to `fields`.
- No new per-user state on this endpoint; it stays stateless and cacheable. The richer the profile, the sharper the ranking — this is the "don't hunt through 1000s" payoff, achieved with zero AI.
- Frontend `ForYouControl`/feed: send `terms` derived from the stored profile; show which interests are driving the feed with a way to tweak.

### A.4 Acceptance (architect-verified)
- Onboarding walks stream→division→interests, persists to localStorage (anon) and `/account/me` (signed-in), survives reload and cross-device (signed-in).
- `/for-you?terms=...` returns sharper results for a rich profile; old `fields` param still works; invalid/unknown keys are dropped server-side; no 500s on junk input.
- Backend: ruff + black + pytest (new tests for the profile PATCH validation + `terms` ranking). Frontend: eslint + tsc + `next build`. Identity/theme unchanged.

## 4. Phase B — Resume PDF → Skills & Exposure + ATS score (NO AI, deterministic)
*Detailed spec issued as its own work order after A lands; summary so the data model above is B-ready.*
- **Client-side PDF text extraction** (a browser PDF text library, e.g. pdfjs-dist — a justified new frontend dep; the file never leaves the browser → privacy + zero server cost). Guard image-only PDFs (no extractable text) → tell the user to upload a text-based PDF.
- **Skill extraction:** match extracted text against a skills lexicon derived from the taxonomy (interest labels/keywords + a curated skills list) → proposed `skills[]`; user confirms/edits; manual add always available. Persist via `PATCH /account/me` (`skills`, `exposure`).
- **ATS score (0–100) beside the uploaded resume**, with an **(i) button → tips**. Transparent rubric, all computable from the extracted text — weighted checks, each contributing points and, if failed, a specific tip:
  - Contactability: email + phone present; a LinkedIn/GitHub/portfolio link present.
  - Structure: standard sections detected (Experience/Work, Education, Skills, Projects).
  - Parseability: text extracted cleanly (image-only or garbled → low — the #1 real ATS killer); no evidence of multi-column/table garbling.
  - Content quality: quantified achievements (numbers/%/₹/$), strong action verbs, reasonable bullet density.
  - Length: within a healthy word-count band (roughly 400–1000 words for a student resume).
  - Relevance: keyword overlap with the user's chosen field/interests (uses the same taxonomy terms).
  - Hygiene: no first-person pronoun overuse, consistent dates, no oversized blocks.
  - The (i) popover lists each check as pass/fail with its tip; the score is the weighted sum. Label it "ATS readiness — an estimate to improve your resume," never a guarantee (Doc 01/05 labeling rule).
- Gating: **free for everyone** (extraction + skills + ATS). The Pro **embedding semantic match** stays Pro (unchanged).

## 5. Phase C — skills into ranking (NO AI)
- Fold confirmed `skills[]` into `expandToSearchTerms` so the feed also reflects resume-derived skills, not just picked interests. Optionally add a lightweight skill-overlap boost. Still deterministic, still through the `/for-you` FTS seam.

## 6. Hard constraints (all phases)
- **Zero new AI spend.** No LLM anywhere in this feature. (The pre-existing Pro embedding match is out of scope and unchanged.)
- Commit solely as `sohan1611` (no co-author trailer, no Dependabot). Branch per part; CI-green gate (not local-green). Non-implementing architect reviews before each commit.
- New frontend dep is allowed **only** for the PDF text extractor in Phase B, and must be justified + self-contained; no other new deps.
- Every derived output (skills, ATS score, "for you") is labeled as a suggestion/estimate, source-linked where relevant — the source of truth stays the opportunity/the user's own edit.
- Batch commits to protect the CI-minutes budget; one push per phase where possible.

## 7. First work order to Codex = Phase A, Part 1 (data model + taxonomy module)
Backend migration (`field_profile`/`skills`/`exposure` jsonb on `users`) + `AccountMe`/`AccountUpdate` extension + validation + tests, AND the frontend `taxonomy.ts` + `fieldProfile.ts` store (no UI yet). Implement → I verify (migration on a throwaway DB, ruff+black+pytest, eslint+tsc) → commit. Then Part 2 (onboarding UI) and Part 3 (`/for-you` terms + feed wiring).
