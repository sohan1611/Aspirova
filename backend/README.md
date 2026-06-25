# Aspirova Backend

FastAPI read API + GitHub Actions-invoked crawlers + ingestion pipeline.

**Read [`../docs/`](../docs/README.md) first** — that's the architecture canon this code must conform to. Phase-by-phase build instructions live in [`../docs/handoffs/`](../docs/handoffs/00-BUILD-PLAN.md).

## Setup

1. Copy `.env.example` to `.env` and fill in your Supabase credentials.
2. Install dependencies: `uv sync`
3. Run the API: `uv run uvicorn api.main:app --reload`
4. Check it's alive: http://localhost:8000/health

## Tests

```
uv run pytest
```

## Lint

```
uv run ruff check .
uv run black --check .
```
