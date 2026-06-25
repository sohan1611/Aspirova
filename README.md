# Aspirova

Every opportunity. One place. Built by a student, for students.

AI-powered career intelligence platform that auto-discovers student opportunities (internships, fellowships, hackathons, research roles) from public sources — not a job board; companies never post here.

## This is a canon-governed project

All architecture, data, pricing, roadmap, and engineering rules are defined in [`docs/`](docs/README.md) — **that is the source of truth.** The implementation agent (currently Claude Sonnet) builds against the phase handoffs in [`docs/handoffs/`](docs/handoffs/00-BUILD-PLAN.md) and must not deviate from the canon without an architect-approved amendment.

- Start here: [`docs/README.md`](docs/README.md) — canon index + binding decision log
- Current build phase: [`docs/handoffs/00-BUILD-PLAN.md`](docs/handoffs/00-BUILD-PLAN.md)
- Active handoff: [`docs/handoffs/PHASE-1-HANDOFF.md`](docs/handoffs/PHASE-1-HANDOFF.md)

## Repo layout

```
backend/    FastAPI API + crawlers + ingestion pipeline (Python)
frontend/   Next.js app (feed, search, SSR opportunity pages)
docs/       Architecture canon + phase handoffs (read this first)
.github/    CI + scheduled crawler workflows
```

## Local setup

See [`backend/README.md`](backend/README.md) and [`frontend/README.md`](frontend/README.md) (added as each is scaffolded).
