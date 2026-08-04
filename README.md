# Aspirova

**Every opportunity. One place.** Built by a student, for students.

A career-intelligence platform that *auto-discovers* student opportunities — internships, jobs,
fellowships, research programmes, hackathons — from public sources. It is **not** a job board:
companies never post here. Everything is crawled from the source and linked back to it.

- **Live:** [aspirova.org](https://www.aspirova.org)
- **API:** [aspirova-api.onrender.com](https://aspirova-api.onrender.com)

> **Status:** built and deployed, pre-launch. It runs in production on real data but has no
> meaningful user base yet. Payments are wired and deliberately dormant — the pricing page is an
> honest waitlist, not a checkout that errors.

## What's actually running

| | |
|---|---|
| Opportunities indexed | ~19,600 |
| Companies | ~1,590 |
| Crawler sources | 11 adapters |
| Recurring programmes | 52 curated |
| Backend tests | 486 across 83 files |

Numbers move daily; `GET /stats` is the live answer.

## Architecture

```
Next.js 16 (Vercel) ──► FastAPI / Python 3.12 (Render, Singapore) ──► Postgres (Supabase, Mumbai)
                                      ▲                                        ▲
                                      │                                        │
                        Upstash Redis (cache + rate limit)     GitHub Actions (crawlers, cron)
```

Three decisions carry most of the design:

**Crawl the source, not the aggregators.** Opportunities come from company ATS endpoints —
Greenhouse, Lever, Ashby, SmartRecruiters, Workable, Recruitee, Keka — which publish structured,
semi-public JSON per company. Scraping other aggregators is legally fragile and a maintenance
treadmill; going to the source is cheaper, cleaner and more defensible.

**Postgres is the search engine, the vector store and the queue.** `tsvector` + `pg_trgm` for
search, `pgvector` for résumé matching, `SELECT … FOR UPDATE SKIP LOCKED` for the job queue. No
Elasticsearch, no Pinecone, no RabbitMQ — at this scale they would be liabilities, not assets.

**Crawl once, serve many — including for AI.** Each canonical opportunity is enriched exactly once
after deduplication, and every user reads the shared result. Résumé Match is pgvector cosine
similarity with **zero LLM calls per match**, which is the difference between viable and bankrupt.

## Recurring programmes, and the honesty rule

Alongside crawled listings, Aspirova curates **recurring annual programmes** — IIT/IISc/TIFR research
internships, ISRO/DRDO/MeitY government internships, GSoC/Outreachy/LFX open source, Mitacs/CERN/DAAD
international programmes. These cannot be modelled as job listings: one stable organisation, a new
edition each year, and long dormant periods.

They are governed by a rule enforced in code and locked by tests: **nothing is shown as "open"
unless a human has verified that edition is literally open.** No status is ever inferred from a date,
on the server or the client, and no code path may set an edition to `open` — including the seed
script that loads authored content. A stale registry degrades to *informative*, never to *wrong*.

## Cost discipline

The whole thing runs on free and near-free tiers, and the engineering reflects that. Real constraints
that drove real decisions:

- Vercel's free tier allows **4h/month** of Fluid Active CPU, so ~20,700 crawlable pages and OG
  images are served from ISR cache rather than invoking a function per request.
- Supabase egress is the binding database limit, so the test suite is run selectively against
  production rather than in full.
- GitHub Actions minutes are budgeted; the crawler was refactored to set-based bulk operations once
  round-trip latency — not commit frequency — was measured as the real bottleneck.

## Repo layout

```
backend/    FastAPI API, crawler adapters, ingestion pipeline, AI workers  (Python 3.12, uv)
frontend/   Next.js app — feed, search, SSR opportunity + programme pages  (Next 16, pnpm)
docs/       Architecture canon: strategy, data, crawler, AI, pricing, governance
.github/    CI, scheduled crawls, backups, notification workers
```

## How this is built

`docs/` is the source of truth, not documentation written afterwards. It holds the architecture, the
pricing model, the engineering rules, and an **append-only decision log** recording every binding
ruling with its reasoning — including the ones that turned out to be wrong, and why.

The work is split between two AI agents under human direction: a **Chief Architect** that designs,
reviews and rules on the canon, and an **implementation agent** that builds against written work
orders. Every change is architect-reviewed, and the merge gate is CI-green, not local-green.

Start with [`docs/README.md`](docs/README.md) — the canon index and decision log.
Current work: [`docs/handoffs/PROGRAMMES-REGISTRY-HANDOFF.md`](docs/handoffs/PROGRAMMES-REGISTRY-HANDOFF.md).

## Local setup

**Backend** — Python 3.12+ and [uv](https://docs.astral.sh/uv/):

```bash
cd backend && uv sync
uv run alembic upgrade head
uv run uvicorn api.main:app --reload
uv run pytest
```

**Frontend** — Node and pnpm:

```bash
cd frontend && pnpm install
pnpm dev
```

Both need local env files that are not in git — see `backend/.env.example` and
`frontend/.env.local.example` for the required keys, plus [`backend/README.md`](backend/README.md)
and [`frontend/README.md`](frontend/README.md).

## License

Aspirova is released under the [MIT License](LICENSE).

The MIT License covers the source code in this repository. The curated datasets committed here -
`backend/data/programmes.json`, `backend/data/programme_editions.json`, `frontend/lib/taxonomy.json`,
and `frontend/lib/skillsLexicon.json` - are authored content compiled from publicly published
information; every entry links to its official source, which remains the authoritative record.
Opportunity data served by the live product is discovered from public sources and is not distributed
in this repository.

Use the crawler at your own risk. Anyone running the ingestion code is responsible for complying
with the terms of service and robots directives of any site they point it at, and with applicable law
in their jurisdiction.
