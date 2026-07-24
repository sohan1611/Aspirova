# Per-Opportunity Skills — Architecture Handoff

*Architect: Claude Opus. Engineer: Codex. Status: ISSUED. Deterministic — NO AI, NO Phase-3 spend (founder chose deterministic 2026-07-24). Every opportunity gets a derived skill set; the feed matches the user's skills against it; skills show ONLY in the detail view.*

## 1. Goal (founder request)
Each job/internship carries the **skills it requires**, derived from its title + description plus role knowledge (e.g. Palantir "Forward Deployed Engineer" → Python, SQL, Data Analysis, Customer Success). The user's saved skills then **match against what a role actually needs** (not just company/position keywords), so a student sees the roles their skills fit. **Skills are shown only when a card is opened (detail view) — never on the feed card** (not by the due date, not under the title).

## 2. Why this is the right seam (grounding)
- **Deterministic extraction already exists** on the frontend (`lib/skillsLexicon.json` 212 skills + `lib/resumeSkills.ts` whole-word matching) for resumes. This feature applies the SAME idea to opportunities, on the backend, at ingestion.
- `pipeline/normalize.py::classify_category` is the existing deterministic per-opp tagger ("placeholder for richer tagging") — extraction lives beside it.
- **Display seam is clean:** `OpportunityDetail(OpportunityListItem)` (schemas.py). Put `skills` on **OpportunityDetail only** → the detail endpoint returns them, the feed/card `OpportunityListItem` never does. Requirement satisfied structurally.
- Phase C already routes the user's skills into `/for-you` via FTS on description text — imprecise (raw keyword presence). This feature stores real per-opp skills so matching is exact.

## 3. Data model + extraction (Part 1 — backend, deterministic)
- **Migration:** `opportunities.skills jsonb NOT NULL DEFAULT '[]'` (array of canonical skill-name strings) + a **GIN index** on it (for overlap queries).
- **Backend skills lexicon:** copy `frontend/lib/skillsLexicon.json` → `backend/pipeline/skills_lexicon.json` (data file). Add a comment in both noting they must stay in sync (same pattern as for_you.py's FIELD_KEYWORDS↔interests.ts). Same alias-matching rules (whole-word; safe for c++/c#/.net).
- **Role→skills map:** `backend/pipeline/role_skills.json` (authored by the architect — see companion file `docs/handoffs/role-skills-map.json`; copy it in). Maps lowercase role-title phrases → implied canonical skills (the "research/implied" layer, deterministic).
- **`pipeline/skills.py::extract_opportunity_skills(title, description) -> list[str]`:**
  - lexicon matches over `title + " " + description` (whole-word/phrase, case-insensitive) → explicit skills.
  - role-map matches over `title` (phrase contained) → implied skills.
  - union, dedup case-insensitively, **explicit-first order**, cap at ~12. Pure function.
- **Ingestion:** in `pipeline/ingest.py`, set `skills=extract_opportunity_skills(normalized.title, normalized.description_raw)` when creating an opportunity AND recompute on update when title/description changed (near where `category` is set). Deterministic, cheap, Shape-A (once per opp).
- **Backfill:** `backend/scripts/backfill_opportunity_skills.py` (dry-run default, `--apply`) — recompute skills for all opportunities from stored `title`+`description_raw`, batched + idempotent. ~13.5k active opps; fast (regex only, no network/AI).
- **Tests:** `extract_opportunity_skills` on real-ish samples (a Palantir FDE description → Python/SQL/etc.; a React role → React/JS/CSS); ingestion stores skills.

## 4. API + matching (Part 2 — backend)
- **`OpportunityDetail`**: add `skills: list[str]`; `from_model` returns `o.skills or []`. Do NOT add skills to `OpportunityListItem` (cards must stay clean).
- **Skill matching on the feed:** the user's skills come from the request (the frontend sends the saved skill names). Add matching to `/for-you` (or a sibling): given `skills` param (CSV of the user's skill names), **filter/rank opportunities whose `skills` overlap** the user's, ordered by overlap count desc, then the existing recency tiebreak. Use the GIN index (`opportunities.skills ?| array[:user_skills]` for the filter; compute overlap count for ranking). This never returns skills in the list payload — it only decides WHICH opps surface and in what order. Keep the existing interest/terms behavior working (skills matching is additive/opt-in, e.g. a `match=skills` mode or when `skills` is supplied).
- **Tests:** overlap filter + ranking; empty skills → unchanged behavior; junk input safe.

## 5. Frontend (Part 3)
- **Detail page `app/opportunity/[slug]`:** render a **Skills** section from `OpportunityDetail.skills` (chips), placed in the detail body (e.g. under the header/near apply) — NOT on the card. Hide the section if empty.
- **Feed:** surface skill-based matching using the user's saved skills (`lib/personalizationSkills.ts` store). Either a "Match my skills" toggle in `ForYouControl` or fold into For You: when the user has saved skills, send them to the feed's skills param so results are ranked by skill fit. **`OpportunityCard` must NOT show skills** — no change to the card.

## 6. Hard constraints
- **No AI, no new deps.** Deterministic only. (LLM inference is a possible Phase-3 upgrade layered on top later.)
- Skills on `OpportunityDetail` ONLY — never on `OpportunityListItem`/the card.
- Backfill is a founder-authorized prod write (dry-run first, like the deadline/seed scripts).
- Backend lexicon is a synced copy of the frontend's; keep the canonical one in `frontend/lib/skillsLexicon.json`.
- CI-green gate (ruff+black+pytest on the ephemeral DB; eslint+tsc+build). Commit as `sohan1611`.

## 7. Build order
Part 1 (model + extraction + ingest + backfill + tests) → I verify + backfill → Part 2 (detail skills + feed matching) → Part 3 (detail UI + feed skill-match). Each: implement → I verify (incl. real-sample extraction + a live check) → commit.
