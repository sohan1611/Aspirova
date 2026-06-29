# Aspirova Frontend

Next.js (App Router) read UI: feed/search, SSR opportunity detail pages, basic auth, bookmarks.

**Read [`../docs/`](../docs/README.md) first** — that's the architecture canon this code must conform to.

## Setup

1. Copy `.env.local.example` to `.env.local` and fill in the Supabase anon key + URL (same project as `backend/.env`).
2. Make sure the backend is running (`cd ../backend && uv run uvicorn api.main:app --reload`).
3. Install dependencies: `pnpm install`
4. Run the dev server: `pnpm dev`
5. Open http://localhost:3000

## Lint

```
pnpm lint
```
