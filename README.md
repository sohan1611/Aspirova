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
