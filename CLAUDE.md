# Aspirova — Claude Code onboarding

*This file auto-loads every session. Read it first, then `docs/`. It re-establishes the full working context on any machine.*

## What this is
**Aspirova** — an AI-powered career-intelligence platform for students that *auto-discovers* opportunities (internships/jobs/hackathons/fellowships) from public sources. **Not** a job board; companies never post here. Tagline: "Every opportunity. One place." Built by a student, intended to scale.

## The permanent role model (do not break this)
- **Claude Opus = Chief Architect / CPO / Data & AI Strategist.** Designs architecture, reviews work, makes decisions, writes planning/governance docs. **Never writes implementation code, never makes PRs, never modifies app files.**
- **Claude Sonnet = Lead Engineer.** Implements against the architect's handoffs. (OpenAI Codex could replace Sonnet later; the canon, not the agent, is authoritative.)
- Switch with `/model claude-opus-4-8` (architect) or `/model claude-sonnet-4-6` (engineer). The user drives which is active.
- **Cadence:** Opus hands off a phase → Sonnet builds it part-by-part (each part: implement → test → commit on a branch) → Sonnet writes a Phase Report → user pings Opus to review and issue the next phase.

## The canon is law
`docs/` is the single source of truth. `docs/README.md` is the index + append-only **Decision log** (never contradict a **Binding** row without an architect amendment). Docs 01-08 cover product/architecture/data/crawler/AI/pricing/roadmap/governance. Phase handoffs + reports live in `docs/handoffs/`. **Doc 08 §3 HARD RULES are the merge gate.**

## Where things stand (2026-06-30)
- **Phase 1 (Foundation + Ingestion + Read API + Frontend): DONE, reviewed (PASS), and DEPLOYED live.**
  - Backend: FastAPI on **Render Singapore** → `https://aspirova-api.onrender.com`
  - Frontend: Next.js on **Vercel** → `https://aspirova.vercel.app`
  - DB: **Supabase Postgres, ap-south-1 (Mumbai)**; crawler on **GitHub Actions** (repo `sohan1611/Aspirova`)
- **Phase 2 (Production-ready platform): HANDED OFF — start here.** Read `docs/handoffs/PHASE-2-HANDOFF.md`. Begin at **Part 2.1 (rate limiting + caching)** — most urgent, since the API is already public.
  - Binding rulings carried in: **Lever-1** (crawler set-based bulk ops) must land *before* new adapters; **rate limiting is urgent**; **Lever-2** (Supabase→Singapore migration) is deferred pending isolated `X-DB-Time-Ms` measurement; **all AI is out of scope until Phase 3.**

## Local setup (after clone/unzip on a new machine)
- **Backend:** Python 3.12+ and `uv`. `cd backend && uv sync`, then `uv run uvicorn api.main:app --reload`. Tests: `uv run pytest`. Migrations: `uv run alembic upgrade head`.
- **Frontend:** Node + `pnpm`. `cd frontend && pnpm install`, then `pnpm dev`.
- **Secrets (NOT in git — must be present locally):** `backend/.env` (`DATABASE_URL`, `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_KEY`, `CORS_ORIGINS`) and `frontend/.env.local` (`NEXT_PUBLIC_API_URL`, `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`). Templates: `backend/.env.example`, `frontend/.env.local.example`.
- **Also needed:** `git`, `gh` (GitHub CLI — used for crawl workflow triggers + PRs). Never commit `.venv/`, `node_modules/`, or any `.env*` (except the `.example` files).

## Git conventions (strict — user preference)
- Commit as **`sohan1611`** (`sohanmandal1611@gmail.com`). **Never** add a `Co-Authored-By: Claude` trailer. **Never** add Dependabot. Only `sohan1611` should appear as a contributor.
- Branch for changes; commit/push when the work for a part is done and green (ruff + black + pytest for backend; eslint + tsc for frontend).

## Cloud infra (all under the user's accounts; secrets already configured)
Supabase (Mumbai) · Render (Singapore, $7 Starter, `render.yaml` blueprint) · Vercel (Hobby) · GitHub Actions (crawler + CI). `DATABASE_URL` is set as a GitHub Actions secret. Phase 2 will add: Razorpay, Resend, Upstash, and R2/B2 (user creates these when prompted).
