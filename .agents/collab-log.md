# Claude <-> Codex collaboration log

Chronological, newest at the bottom. Gists only, no transcripts, no secrets.

## 2026-07-06 — Work order 1 (Claude → Codex)
- Task: fix red CI — /pricing statically prerenders and fetches /plans at build time, ECONNREFUSED with no backend; add a canonical fallback mirroring seed_plans.py + fix the stale ci.yml comment.
- Codex: added typed FALLBACK_PLANS (5 plans, exact seed values) + try/catch around getPlans() in app/pricing/page.tsx; corrected the ci.yml Build comment. Hit the known Windows sandbox CreateProcessAsUserW=5 limit, so it edited but could not self-verify.
- Review: verified pass — Claude ran `pnpm build` with no backend up (succeeds; /pricing stays ○ static, / and /opportunity/[slug] stay ƒ), plus `pnpm lint` and `tsc --noEmit` clean. Committed as sohan1611.

## 2026-07-06 — Work order 2 (Claude → Codex): Phase 3 Part 1 — AI infrastructure (zero-cost foundation)
- Task: build the `ai_client` seam (generate + embed, stub when unkeyed, usage logging), `ai_usage` + `resume_profiles` + `opportunities.embedding` schema (pgvector migration), `ai_budget` daily-cap helper, config, stub-only tests — no key, no spend. Locked: generation `claude-haiku-4-5`, embeddings `text-embedding-3-small` (1536-dim).
- Codex: delivered all of it — `ai_client.py` (deterministic normalized hash stub vectors, lazy key-guarded provider paths, usage logged via a separate session so it can't corrupt the caller's txn), `ai_budget.py`, models, migration `d4b9a2e7c6f1` (down `7c1e5a9f3d6b`), config, `test_ai_client.py` + `test_ai_budget.py`. Self-flagged that `uv.lock` needed regenerating (sandbox can't run `uv lock`).
- Review: verified pass — Claude regenerated `uv.lock` (pgvector 0.4.2); ruff + black clean; full migration chain applies on a `pgvector/pgvector:pg17` container (extension enables, vector round-trips); all 3 new tests pass; confirmed the separate-session usage logging leaks zero rows past the test rollback. Applied the additive migration to production Supabase (user-authorized), full suite green against prod (136), committed as sohan1611, CI green.

## 2026-07-06 — Work order 3 (Claude → Codex): Phase 3 Part 2 — enrichment pipeline
- Task: build `enrich_opportunity` (summary + tags + embedding via ai_client, idempotent) + `enrich_pending` worker (key-guarded so it no-ops in prod until Part 7, budget-aware), clear enrichment on content change in ingest_one, an enrich_worker.py CLI, and stub tests. Not wired into any workflow.
- Codex: delivered all four — enrich.py (defensive tag parsing, idempotency guard, key guard, per-opp budget stop + commit), ingest.py content-change invalidation, enrich_worker.py, test_enrich.py.
- Review: verified pass — ruff clean; black reformatted 2 files (Codex couldn't run it); on a fresh pgvector container all 5 enrich tests pass with ZERO leaked opportunities/tags/ai_usage (per-opp commits are savepoint-contained by the rollback fixture); full suite green against production (141), zero test-row leak in prod. Committed as sohan1611.
