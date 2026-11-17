# Production smoke checks

Small, anonymous, read-only canaries for the public Vercel frontend and Render API.
This folder has its own uv environment; backend/frontend dependencies are untouched.

Checks: API health (one retry after 20 seconds), home search/CTA, uncaught home page
errors and horizontal overflow, at least five cards each on internships/jobs with
honest labels (no "Verified"/"Official"-style badges; "New" only next to a source
"Posted" date, never a crawler "Seen" date), the first internship's detail title,
external Apply href and its "Opens … Aspirova never handles your application."
disclosure naming the same host the Apply link goes to, calendar entries and
the drawer's HTTPS official source, calendar JSON/API coverage reconciliation,
Free/Pro pricing without ₹399, XML sitemap,
and robots.txt. Detail JSON-LD presence is recorded, not required: the frontend
intentionally omits it for listings without complete eligible JobPosting metadata.

Every page check runs at desktop **1280×800** and mobile **390×844**. A normal run
makes **14 page visits** plus four HTTP checks (one extra health request on retry,
plus calendar coverage polls while waiting for the backend deploy).
It does not traverse sitemap entries, paginate, or run optional search queries.

Install once, then run (this contacts production by default):

```sh
cd smoke
uv sync
uv run playwright install --with-deps chromium
uv run pytest
```

Override `SMOKE_SITE_URL` (default `https://www.aspirova.org`) and `SMOKE_API_URL`
(default `https://aspirova-api.onrender.com`) to target another environment.
Use `uv run pytest -v -s` to see the informational JSON-LD result for passing tests.

The suite **must stay anonymous and read-only**. Each test uses a fresh context:
no saved cookies, authentication, sign-in, or form submissions. Apply/source links
are inspected and never clicked. Browser requests other than GET/HEAD/OPTIONS are
blocked, including automatic opportunity view-tracking POSTs; service workers are
disabled so writes cannot bypass the guard. Speculative Next/browser prefetches
are blocked to avoid unnecessary renders. A future consent banner may only be
declined, never accepted for non-essential cookies.

On failure, `artifacts/` receives a per-test PNG and console log (including page
errors and the assertion). HTTP-only failures get a local diagnostic screenshot;
if browser setup itself fails, only a diagnostic log can be saved. Artifacts are
git-ignored and uploaded for seven days by the workflow. The workflow runs every
six hours at minute 17 UTC, on manual dispatch, and on successful Production
deployment statuses; preview statuses are skipped. Concurrency allows one active
run and one pending run. GitHub's normal failed-workflow notifications are the
alert; the owner must enable Actions email notifications for this repository.

The coverage check compares `/calendar/coverage` to the actual source-row count in
`backend/data/hiring_calendar_2027.json` at the checked-out commit. Deployment events
check out the deployment SHA. The eight buckets must sum to the source rows,
metadata gaps and unexplained rows must be empty, and some programmes must be
published. Pending imports are recorded in test output and failure context but
are allowed immediately after deploy; the daily refresh gates those after import.
Source rows track programmes, not a count of open opportunities. See the
[CAL-04 audit](../docs/audits/2026-11-17-cal-04-calendar-reconciliation.md).

Before comparing counts, the canary waits up to **360 seconds**, polling every
**20 seconds**, for a 200 coverage response whose `source_digest` matches both
checked-out calendar JSON files. Vercel and Render deploy independently: the
frontend can finish while the API still serves the preceding source data or
returns 404 for a newly added endpoint. Connection failures are failed polls too.
A wait logs elapsed seconds and poll count; a timeout reports the expected digest,
last HTTP status and last digest, and points to the Render deploy. A matching
response is checked immediately, so genuine coverage failures still fail.

The digest is the first 16 hex characters of SHA-256 over canonical source JSON,
a single newline byte, then canonical metadata JSON. Each object is encoded with
`json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)`
and UTF-8, so formatting and line endings do not affect deployment identity.
This remains anonymous and read-only; it never triggers a deploy or import.

The pure comparison cases in `tests/test_calendar_coverage.py` run without network
or browser fixtures: `uv run pytest tests/test_calendar_coverage.py`.

Offline code checks: `uv run ruff check .` and `uv run black --check .`.

`uv.lock` could not be generated in the implementation sandbox: Playwright was
not available in its offline cache. Run `cd smoke && uv lock` with registry access
before committing this suite. The workflow's `uv sync` can resolve it in the meantime.
