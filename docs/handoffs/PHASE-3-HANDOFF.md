# PHASE 3 HANDOFF — AI Features (the Pro hook)

*From: Chief Architect (Opus) · To: the engineer (Codex or Sonnet — founder's pick per part). Status: ISSUED. Phase 2.5 gate is met (CI green). This phase implements Doc 05 (AI Systems) under Doc 06's cost discipline. It is the biggest and most cost-sensitive phase — the guardrails ARE the architecture.*

> **Part numbering note:** Phase 2.5's parts were mislabeled `3.1–3.8`. To avoid collision, **Phase 3 uses "Part 1 … Part 7."** Ignore the 2.5 `3.x` labels.

---

## 0. The one law that governs everything (Doc 05 §1)

**Generate once, store, reuse. Never run AI per-user when a shared precomputed result will do.** AI cost must scale with **new unique opportunities per day**, *not* with user count. Every ruling below serves that law.

Three cost shapes; push every feature to the cheapest it can occupy:
- **A — once per canonical opp** (summary, tags, embedding). ✅ Preferred.
- **B — once per user artifact, on change** (resume embedding). ✅ Acceptable, cached.
- **C — live per user interaction** (Copilot chat). ⚠️ The only dangerous shape — gate, rate-limit, cache, cheapest model.

---

## 1. Scope discipline — the cost comes LAST (binding sequencing)

Phase 3 introduces the project's **first real variable cost** (LLM API calls). So it is built the same way Phase 2 handled Razorpay/Resend/Upstash: **build the seam + guardrails first against a stub (zero spend), wire the real provider key last.** Parts 1–5 are buildable, testable, and mergeable with **no API key and no spend**. Only Parts 6–7 need the live key.

**OUT of scope / forbidden:**
- **No per-(user×opportunity) LLM call for ranking, ever.** Resume Match is vectors only. This is the single "viable vs bankrupt" decision (Doc 05 §2.2).
- **No "will this student get in" prediction.** Reframed to recurring-program *reopen* prediction (Doc 05 §2.3) — statistics, not a promise.
- **No AI on the API hot path.** Enrichment runs in the ingestion pipeline (GH Actions), never in a web request. Copilot is the *only* request-path AI, and it's gated + capped.
- **No hardcoded pricing/model assumptions.** Read the current model/pricing reference (the `claude-api` skill / live Anthropic docs) before finalizing model IDs, `max_tokens`, and cost math (Doc 05 §4/§9).

---

## 2. Locked architect decisions (so the engineer isn't blocked)

1. **`ai_client` is the single mandated seam** (Doc 05 HANDOFF #1, Doc 08). All generation AND embedding calls go through it. Provider-swappable, model-version-aware, and it writes an `ai_usage` row for every call. No raw SDK calls anywhere else.
2. **Generation model = Haiku-class.** Current ID `claude-haiku-4-5` (confirm against the live reference at wiring time; do not assume pricing). Reserve any larger model for rare, measured hard asks.
3. **Embeddings need a dedicated embeddings model** (Anthropic has no first-party embeddings API). **Decision the engineer confirms in Part 1 against current pricing/docs, then locks:** recommended candidates are Voyage (`voyage-3`-class, Anthropic's recommended partner) or OpenAI `text-embedding-3-small`. Pick one, **set the pgvector column dimension to match it exactly**, and store the model name with every vector (Doc 05 §3) so a future re-embed is a controlled migration. Wrap it behind `ai_client.embed()` so the provider is a one-file change.
4. **Spend guardrail = daily cap in `ai_usage`, config-driven, graceful degradation.** Default cap conservative and env-tunable (start ~US$2/day ≈ ₹170 — a runaway-catcher, not a real operating limit; tune against Doc 06). When the cap is hit: **fall back to non-AI behavior** (templated report, keyword search, "Copilot unavailable, try later") — never fail hard, never overspend.
5. **Blank keys fail safe, not loud** (the Phase-2 pattern): no provider key → enrichment no-ops and logs, Resume Match still works (it's pure vectors once opps are embedded — though with nothing embedded yet it returns empty), Copilot returns a clean "unavailable." Nothing 500s.

---

## 3. The build — 7 parts (each: implement → test → verify the way CI runs it → commit on a branch; backend gate = ruff + black + pytest, frontend gate = eslint + tsc + `next build` with backend DOWN; then merge)

### Part 1 — AI infrastructure (zero-cost foundation)
The seam + guardrails + schema, all against a **stub client**. No key, no spend.
- `core/ai_client.py`: `generate(...)`, `embed(...)`, both logging to `ai_usage`; provider + model IDs from config; a stub/fake implementation used when unkeyed and in tests.
- Migration: enable **pgvector**; add `opportunities.embedding vector(N)` + `opportunities.embedding_model text`; new `resume_profiles` table (user, version, embedding, model, created_at); new `ai_usage` table (ts, feature, model, input_tokens, output_tokens, est_cost, ok). (N = the Part-1 embedding-model decision, §2.3.)
- `core/ai_budget.py`: daily-spend read + `is_over_budget()` for the degradation checks.
- Config: provider keys (blank ok), model IDs, `max_tokens`, daily cap — all env-driven (Doc 08 "config not code").
- **Acceptance:** migration applies cleanly on a throwaway DB and round-trips a vector; `ai_client` stub logs `ai_usage`; full suite green; nothing calls a real provider.

### Part 2 — Enrichment pipeline (Shape A)
- `pipeline/enrich.py`: `enrich(opportunity)` → sets `summary`, `tags`, `embedding` via `ai_client`. Runs **in the ingestion pipeline, after dedup + change detection**, **idempotent** (skip if already enriched and content hash unchanged — Doc 05 §5.2). Never on the request path.
- Backfill script for existing opps (batched, resumable, respects the budget cap).
- **Acceptance:** against the stub, a crawl enriches only *new/changed* canonical opps, never re-enriches unchanged ones; idempotency proven by a re-run doing zero calls.

### Part 3 — Semantic search + Resume Match (Shape B + A, ZERO per-match LLM)
- Add pgvector cosine retrieval (HNSW index) behind the search seam; keep `tsvector`/`pg_trgm` as the lexical layer (hybrid is fine).
- Resume Match: embed the resume **once per version** (Shape B), store in `resume_profiles`; **match = cosine top-K, no LLM**; cache per `(user, resume_version)`; incrementally score only new opps against the cached vector. Pro-gated via `can()`.
- Frontend: resume upload + a "Matches for you" surface on the Phase-2.5 design system.
- **Acceptance:** Resume Match returns sensible ranked results with **provably zero LLM calls** (assert `ai_usage` has no generation rows for a match); cache hit on repeat.

### Part 4 — Reopen Prediction + Hidden flag (Shape A, mostly no LLM)
- Reopen prediction: **statistical** from `posted_at` history + curated known cycles → "usually opens ~<window>", "likely to reopen in N weeks." Labeled an estimate, never a promise. No "will you get in."
- `opportunities.is_hidden`: computed **once per opp** from source tier + cross-source scarcity + low engagement. A flag + filter, gated by `hidden_opps`. No per-user AI.
- **Acceptance:** predictions are labeled estimates; `is_hidden` computed deterministically; both gated correctly.

### Part 5 — Weekly Career Report (Shape A templated)
- Templated assembly in the **notification worker** (GH Actions cron) from precomputed data (matches, deadlines, new hidden opps). At most **one short LLM intro, cached/cohort-batched** — not per user. Gated via `can()`.
- **Acceptance:** a full report renders from templates with zero or one (cached) LLM call; delivered through the existing Resend seam.

### Part 6 — Career Copilot (Shape C — needs the real key; wired LAST)
- Pro-gated (`plans.features.copilot`); **Upstash rate-limited** (N msgs/day/Pro user, config); **RAG** context = user profile + pgvector top-K opps + bookmarks (not the whole catalog); concise `max_tokens`; **cache shared/non-personal answers**; Haiku-class; grounded (say "I don't have that," never fabricate an opportunity — Doc 05 §6).
- Frontend: chat surface, Pro-gated, on the 2.5 design system.
- **Acceptance:** gated + rate-limited + cached proven; a fabrication-resistance check; budget-cap degradation returns a clean "unavailable."

### Part 7 — Go-live + cost validation
- Wire the real provider key(s) (Anthropic + the chosen embeddings provider) into `backend/.env`, Render env, and the crawler's GH Actions secrets. Run the enrichment backfill for real. Validate measured spend against Doc 06's model; confirm the **alarm fires** and **graceful degradation** actually degrades. Re-verify every AI output is labeled + source-linked.
- **Acceptance:** real enrichment flowing; spend tracked and within the modeled band; alarm + degradation demonstrated; Phase-3 gate (below) met.

---

## 4. Cross-cutting guardrails (every part)

- **Everything through `ai_client`** — no scattered SDK calls (Doc 08 mandated seam).
- **Idempotent, post-dedup, post-change-detection enrichment** — never re-pay for unchanged content.
- **Zero per-match LLM** in Resume Match — assert it in tests.
- **Every AI output labeled + source-linked** — the summary is convenience, the source is truth (Doc 05 §6, Doc 01 R5). Inferred things say "estimate."
- **Cost controls are not optional:** `ai_usage` logging on every call, daily spend alarm, budget-cap graceful degradation, idempotency guards (Doc 05 §5).
- **Gate unchanged:** CI-green (not local-green), commit **solely as `sohan1611`** (no co-author trailer for any agent, no Dependabot), non-implementing agent reviews before commit.

## 5. Manual prerequisites (founder creates when a part needs them — like Phase 2's accounts)

1. **Anthropic API key** (generation) — needed at Part 6/7; Parts 1–5 use the stub.
2. **Embeddings provider key** (Voyage or OpenAI, per the Part-1 decision) — needed when Part 2 first embeds for real; stubbed until then.
3. **pgvector on Supabase** — enabled by the Part 1 migration (`create extension`), no account needed.

None block building/merging Parts 1–5; all integrations fail safe when unkeyed.

## 6. Gate to "Phase 3 done" (Doc 05 definition of done)

AI cost scales with *new opportunities*, not users; Resume Match makes **zero** per-match LLM calls; Copilot is gated, rate-limited, and cached; every AI output is labeled + source-linked; a runaway spend is caught by the alarm and capped by graceful degradation; enrichment is idempotent and post-dedup. When green, the architect reviews before Phase 4 (growth) — and the deferred **Razorpay wiring** (+ its webhook out-of-order fix) is finally folded in, since there's now real Pro value (AI) for the paywall to gate.

---

## HANDOFF TO ENGINEERING

1. **Build the seam and guardrails before any real call** (Part 1 against the stub). Do not let a single AI call happen before `ai_usage` logging + the budget cap exist.
2. **Confirm the embedding model against current pricing/docs first** (Part 1), set the pgvector dimension to match, store the model with every vector.
3. **Resume Match is vectors only** — if you find yourself about to call an LLM per opportunity per user, stop; that's the forbidden design.
4. **Wire the real key last** (Part 6/7). Everything before it is stub-testable and zero-cost.
5. **End with a Phase 3 Report** (like the prior reports): what shipped, real spend vs Doc 06 model, proof of zero-per-match-LLM, proof the alarm + degradation fire, and any deviations flagged for the architect.
