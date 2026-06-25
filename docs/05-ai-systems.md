# 05 — AI Systems

*Author: Chief AI Strategist. The governing law of this document: **generate once, store, reuse. Never run AI per-user when a shared, precomputed result will do.***

---

## 1. The cost model that governs every AI decision

There are exactly three cost shapes for AI in this product. Push every feature toward the cheapest shape it can occupy:

| Shape | Cost driver | Examples | Verdict |
|-------|-------------|----------|---------|
| **A — Per canonical opportunity, once** | # of *new unique* opps/day | summary, tags, embedding | ✅ Preferred. Fixed-ish, tiny, shared by all users. |
| **B — Per user artifact, on change only** | # of resume uploads/edits | resume embedding | ✅ Acceptable. Cached; recomputed only on change. |
| **C — Per user interaction, live** | # of active Pro users × usage | Career Copilot chat | ⚠️ Dangerous. Gate, rate-limit, cache, cheap model. |

**The entire AI architecture is the discipline of keeping features in A and B, and ring-fencing C.**

Two multipliers make Shape A cheap:
- **Enrich *after* dedup** → pay once per canonical opp, not once per source (3× saving when an opp appears on 3 sites).
- **Enrich only past change detection** → never re-pay for unchanged content.

So AI cost ≈ *(new unique opportunities per day) × (per-opp enrichment cost)* — **independent of user count.** That is the whole game.

---

## 2. The five AI features, redesigned for cost

### 2.1 AI Career Copilot — *Shape C (the only live per-user feature)*
**What:** a chat assistant answering "what should I apply to / how do I improve my chances / what fits me."
**Cost-safe design:**
- **Pro-gated** (it's the premium hook anyway).
- **Cheapest viable model** (Haiku-class) for the conversational turn; reserve any larger model for rare complex asks.
- **RAG, not raw generation:** assemble tight context = user profile + top-K opportunities via **pgvector** search (cheap retrieval) + their bookmarks. Don't stuff the whole catalog into the prompt.
- **Rate-limit hard** (Upstash): e.g., N messages/day per Pro user. Prevents a single power-user from running up the bill.
- **Cache** common, non-personal answers ("when does Google STEP usually open?", "how to write an internship resume") — these are shared knowledge, served from cache, $0 marginal.
- **Short outputs** by design (system prompt enforces concise answers) — output tokens dominate cost.
**Why gated + capped:** Copilot is the *only* feature whose cost scales with users. Containing it is non-negotiable.

### 2.2 Resume Match Engine — *Shape B + A, ZERO per-match LLM*
**What:** "how well does this opportunity fit me?" ranked matches.
**The critical design decision:** **Resume Match is embedding cosine similarity, NOT an LLM grading each resume against each job.**
- Embed the resume **once** per version (Shape B) → store in `resume_profiles.embedding`.
- Opportunities are already embedded (Shape A).
- **Match = pgvector cosine top-K.** No LLM call. Near-free, millisecond, scales infinitely.
- Optional cheap re-rank / one-line "why it fits" can be generated **once per (opportunity) and lightly personalized client-side**, or batched — but the *ranking itself* never calls an LLM per user per opp.
- **Cache** the match list per `(user, resume_version)`; invalidate on resume change or when new opps arrive (incremental: only score the new opps against the cached resume vector).
**Why this matters:** the naive "LLM scores resume vs each job" design would cost *users × opportunities* LLM calls — financially impossible. Embeddings turn an O(users×opps) LLM bill into an O(opps + resumes) embedding bill plus free vector math. **This single decision is the difference between viable and bankrupt.**

### 2.3 "Internship Prediction Engine" — *REFRAMED, Shape A, mostly no LLM*
**Challenge:** "predict if a student gets in" is low-value, easily wrong, and erodes trust. **Rejected as specified.**
**Reframe → Recurring-Program Reopen Prediction:** many high-value programs recur predictably (Google STEP ~Nov, MLH seasons, fellowship cycles, ambassador intakes). Using historical `posted_at` patterns in our own data + curated known cycles:
- Predict **"X usually opens around <window>"** and **"likely to reopen in N weeks."**
- This is **data/statistics, not heavy ML** — cheap, defensible, genuinely useful, and *uniquely possible because Aspirova has the longitudinal crawl history.*
- Surfaced as "Upcoming likely openings" — a great Pro hook and a reason to keep dream-company alerts.
**Optional later:** a lightweight "fit likelihood" *band* (not a false-precision percentage) derived from match score + historical selectivity signals — clearly labeled as a heuristic, never a promise.

### 2.4 Hidden Opportunities Engine — *Shape A, classification once*
**What:** surface long-tail/low-competition opps (research labs, ambassador programs, niche fellowships) as a premium tier.
**Design:**
- "Hidden" is mostly a **classification + scarcity signal computed once per opp** (`opportunities.is_hidden`): source type (Tier-3 lab/ambassador/GitHub), low cross-source count (appears nowhere else = genuinely hidden), low view counts.
- No per-user AI. It's a flag + a filter, gated by plan (`hidden_opps` feature).
**Why it's strong:** these sources cost us almost nothing (Tier-3, 24h) yet are the *most differentiated* content (Doc 01 moat). Packaging them as "hidden" is high-margin perceived value.

### 2.5 Weekly Career Report — *Shape A templated + Shape B light personalization*
**What:** a weekly digest: new matches, closing-soon deadlines, recommended actions.
**Design:**
- **90% is templated assembly from precomputed data** (match list, deadlines, new hidden opps) — *no LLM needed* to fill a good template.
- Optional **one short LLM-generated intro paragraph**, and even that can be **batched/cached by cohort** (students with similar profiles get similar framing) rather than fully unique per user.
- Generated by the notification worker (GH Actions cron), not on a user request.
**Why:** a great report doesn't require per-user generation — structured data + a strong template *feels* personalized because the *data* is personalized, cheaply.

---

## 3. Embeddings: the backbone

- **One embedding per canonical opportunity** (Shape A), one per resume version (Shape B). Stored in pgvector (Doc 03).
- **Powers three features at once:** semantic search, Resume Match, and Copilot retrieval — one cost, three products. *Maximize reuse.*
- **Model versioning:** store `model` with each vector so a future model upgrade is a controlled re-embed migration, not a silent inconsistency.
- **Chunking:** opportunity descriptions are short; embed the whole normalized description (+ title + tags). Resumes may need light truncation/section-weighting.

---

## 4. Model selection policy

- **Default to the cheapest model that clears the quality bar** for each task. Enrichment/tagging/summary and most Copilot turns → **Haiku-class.** Reserve larger models for genuinely hard, rare asks (and measure whether they're even needed).
- **Right-size outputs:** output tokens cost more than input; enforce concise outputs via prompts and `max_tokens`.
- **Batch** enrichment calls where the API supports it.
- **Always read the live pricing/model reference before committing** model IDs and cost assumptions — pricing and model lineup change. (Use the `claude-api` skill / current Anthropic docs; do not hardcode cost numbers from memory.)
- **Provider portability:** wrap all AI calls behind one internal `ai_client` interface so swapping models/providers is a one-file change, not a refactor (Doc 08).

---

## 5. Cost-control mechanisms (checklist the engineer must implement)

1. **Enrich after dedup, after change detection** — never before. (Pipeline ordering, Doc 04.)
2. **Idempotent enrichment:** an opp already enriched is never re-enriched on re-crawl (guard on `summary IS NOT NULL` + content hash).
3. **Resume Match = vectors only; no per-match LLM.**
4. **Copilot:** Pro-gate + Upstash rate-limit + response cache + concise outputs + Haiku-class.
5. **Cache shared answers** (FAQ-style Copilot, reopen predictions, hidden-opp lists).
6. **Batch** enrichment and report generation in scheduled jobs.
7. **Budget alarms:** track daily AI spend (count calls/tokens in a `ai_usage` log); alert if it exceeds a threshold (catches a runaway loop or a viral spike early).
8. **Graceful degradation:** if the AI budget cap is hit, fall back to non-AI behavior (templated report, keyword search) rather than failing or overspending.

---

## 6. Quality & trust guardrails

- **Never present AI guesses as facts.** Inferred deadlines and any "fit" signals are clearly labeled (`deadline_confidence`, "heuristic"). Trust is the product (Doc 01 R5).
- **Summaries link to source**; the AI summary is a convenience, the source is truth (legal + trust, Doc 04 §10).
- **Copilot grounding:** answer from retrieved opportunities + known data; instruct it to say "I don't have that" rather than hallucinate opportunities. A fabricated internship is a trust-killer.
- **Human-reportable:** "this summary is wrong / link is dead" feeds the `flags` table.

---

## 7. Where the AI budget actually goes (sanity model; hard numbers in Doc 06)

- **Dominant cost:** enrichment of *new unique opps/day*. Bounded by ingestion volume, not users. Change detection + dedup keep it small.
- **Second:** Copilot — bounded by Pro-user count × rate cap. Capped by design.
- **Near-zero:** Resume Match, Hidden flag, Weekly Report (vectors + templates).
- **Conclusion:** with this architecture, **AI is NOT the thing that scales painfully with users** — *email is* (Doc 06). That's a deliberate, healthy outcome.

---

## HANDOFF TO ENGINEERING

1. **Single `ai_client` abstraction** wrapping all model + embedding calls (provider-swappable, model-version-aware, with a usage logger). No raw SDK calls scattered in features.
2. **Enrichment runs in the ingestion pipeline only**, after dedup + change detection, idempotently. One function: `enrich(opportunity)` → sets `summary`, `tags`, `embedding`. Never called from the API request path.
3. **Resume Match: implement as pgvector cosine top-K.** Explicitly forbidden: any per-(user×opportunity) LLM call for ranking. Cache by `(user, resume_version)`; incrementally score only new opps against cached resume vector.
4. **Copilot:** Pro-gated via `plans.features.copilot`; Upstash rate-limit; RAG context from pgvector retrieval; concise `max_tokens`; cache shared/non-personal answers; cheapest viable model.
5. **Reopen Prediction:** statistical, from `posted_at` history + curated cycles. Do **not** build "will this student get in." Label all predictions as estimates.
6. **Hidden flag:** computed once per opp (`is_hidden`) from source tier + cross-source scarcity + low engagement; gated by plan. No per-user AI.
7. **Weekly Report:** templated assembly from precomputed data in the notification worker; at most one short cached/cohort-batched LLM intro.
8. **Cost controls mandatory:** `ai_usage` logging, daily spend alarm, budget-cap graceful degradation, idempotency guards.
9. **Read current model/pricing docs before finalizing model IDs and `max_tokens`;** do not hardcode pricing assumptions.

**Definition of done for the AI layer:** AI cost scales with *new opportunities*, not users; Resume Match makes zero per-match LLM calls; Copilot is gated, rate-limited, and cached; every AI output is labeled and source-linked; a runaway spend is caught by an alarm and capped by graceful degradation.
