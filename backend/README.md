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

## Digest status and examples (ALERT-07)

`GET /account/me` includes `digest_status` from the worker ledger: the last
successful digest's timestamp and listing count, and whether the newest attempt
failed. `last_sent_counts_by_category` categorizes the opportunity/hackathon IDs
recorded on that same successful row. Deleted listings count as `removed`;
`programme_slugs` count as `programme_update`. A newer failed attempt does not
replace the last successful send's counts. A reader with no digest rows still
gets `digest_status: null`; legacy rows without item metadata have no breakdown.

`GET /account/digest-preview` is authenticated, rate-limited and `no-store`. It
uses `preview_daily_digest` to render the reader's real next email, shown in the
account dialog as an HTML iframe. Nothing is sent or recorded. Loading, rate-limit,
error and empty states remain available; empty digests still send no email and
create no digest ledger row.

`GET /digest/sample` is public and uses the worker's generic fallback and shared
hackathon picks, without a user lookup or personal email rendering. It returns the
Asia/Kolkata calendar date, full category counts and at most 6 real listings using
the long public read-cache TTL. The signed-out Apply dialog displays this dated
example and a sign-in link; empty or failed samples render nothing. Scheduler
runs can be delayed, and previews may change before sending; no delivery time is
promised.
