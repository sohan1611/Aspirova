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

## Where things stand (2026-09-04)
*Phases 1 and 2 are long done. This section drifted two months out of date and was rewritten;
keep it current, because it is the first thing every session reads.*

- **Live and healthy.** Backend on **Render Singapore** (`https://aspirova-api.onrender.com`),
  frontend on **Vercel** at **`https://www.aspirova.org`** (the `aspirova.vercel.app` domain still
  serves and canonicalises to it), crawler + digests on **GitHub Actions**. All production routes
  answer 200.
- **Database (since 2026-10-21): self-managed Postgres 17 on a DigitalOcean droplet,
  `aspirova-db`, `168.144.242.186`, Singapore (SGP1), ~₹810/mo.** It moved off Supabase Pro
  (₹2,900/mo). **Supabase still serves Auth and Storage (resume PDFs)**, to be downgraded to its
  Free plan after the 7-day rollback window. The app connects as `aspirova_app` (not a
  superuser) over TLS; operate the box over SSH as root. Everything is in
  `infra/db/RUNBOOK.md`: provisioning, rollback, disaster recovery. **Never run tests or write
  scripts against it. It is production.**
- **Scale:** ~25,800 visible opportunities across **16 sources** and 5,638 companies. Auth is live
  (Google, GitHub, email). Application tracking, listing filters/sort/search, and both digests all
  ship and work.
- **The binding constraint is DISTRIBUTION, not engineering.** 12 registered users, 1 bookmark all
  time, 0 saved searches. Features are not the bottleneck and have not been for months — see the
  2026-09-04 audit. Weigh any proposed supply-side work against that.

### Rulings that still bind day-to-day
- **Lever-2 (moving the DB *for latency*) stays CLOSED.** Re-measured 2026-09-04: the variance
  was database CPU, not the Mumbai hop, so fix query shape. The 2026-10-21 move was for **cost**.
  It landed in Singapore only because Render runs there (decision log, 2026-10-21).
- **Absence is evidence only when the crawl that missed a listing could have seen it.** Only
  `FULL_INVENTORY_SOURCES` may retire on absence; see `pipeline/expire.py`. Violating this closed
  ~2,000 live jobs in one crawl.
- **All AI remains deferred by founder ruling.** Deterministic paths only; anything that writes
  `summary` must respect `meta.summary_source` so the AI upgrade is not foreclosed.
- **Nothing ships on a green gate alone** (Doc 08 §3): exercise a change against real production
  data or a real rendered DOM and record the numbers in the PR.

## Local setup (after clone/unzip on a new machine)
- **Backend:** Python 3.12+ and `uv`. `cd backend && uv sync`, then `uv run uvicorn api.main:app --reload`. Tests: `uv run pytest`. Migrations: `uv run alembic upgrade head`.
- **Frontend:** Node + `pnpm`. `cd frontend && pnpm install`, then `pnpm dev`.
- **Secrets (NOT in git — must be present locally):** `backend/.env` (`DATABASE_URL`, `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_KEY`, `CORS_ORIGINS`) and `frontend/.env.local` (`NEXT_PUBLIC_API_URL`, `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`). Templates: `backend/.env.example`, `frontend/.env.local.example`.
- **Also needed:** `git`, `gh` (GitHub CLI — used for crawl workflow triggers + PRs). Never commit `.venv/`, `node_modules/`, or any `.env*` (except the `.example` files).

## Git conventions (strict — user preference)
- Commit as **`sohan1611`** (`sohanmandal1611@gmail.com`). **Never** add a `Co-Authored-By: Claude` trailer. **Never** add Dependabot. Only `sohan1611` should appear as a contributor.
- Branch for changes; commit/push when the work for a part is done and green (ruff + black + pytest for backend; eslint + tsc for frontend).

## Cloud infra (all under the user's accounts; secrets already configured)
DigitalOcean (Singapore droplet, the app database, daily backups) · Supabase (Mumbai, Auth + Storage only) · Render (Singapore, $7 Starter, `render.yaml` blueprint) · Vercel (Hobby) · GitHub Actions (crawler + CI). `DATABASE_URL` (the droplet) and `SUPABASE_DB_URL` (Supabase, used only for the nightly Auth backup) are GitHub Actions secrets. Phase 2 will add: Razorpay, Resend, Upstash, and R2/B2 (user creates these when prompted).
