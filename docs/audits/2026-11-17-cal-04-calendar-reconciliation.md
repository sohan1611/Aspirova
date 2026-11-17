# CAL-04 — Calendar count and coverage reconciliation

The authored JSON currently contains 169 source rows. A row describes a tracked
programme, including tentative, future, rolling and closed cycles. It does not
assert that applications are open. The previously observed 151 active programmes
was a database snapshot, not the number of authored rows. Imports, category
constraints, authored retirements and the selected window can explain differences;
use the reconciliation rather than assuming any historical snapshot is current.

## The row partition

Every actual JSON row appears in exactly one bucket. The first five are counts;
`skipped`, `pending_import` and `unexplained` are lists, counted by their lengths.

| Bucket | Meaning |
| --- | --- |
| `published_dated` | An active calendar programme has its authored cycle-year edition and appears in the default dated public calendar. |
| `published_rolling` | It appears in the public rolling / apply-anytime list and was not already counted as dated. |
| `outside_window` | An active, dated cycle is outside the default window, including past and far-future windows, and is not closed. |
| `closed` | Its cycle-year edition is closed and it is not shown in either public list. |
| `retired` | The programme is inactive or the watchlist explicitly retires its slug, including a matched registry alias. |
| `skipped` | No programme exists and the live `ck_programmes_category` constraint rejects the source category. The list gives the row ID, authored slug and reason. |
| `pending_import` | Source and metadata exist but there is no matching programme and no known category rejection. |
| `unexplained` | Any other state, such as a missing cycle-year edition, missing/ambiguous metadata or multiple matching programmes. Lists row ID and authored slug (empty if metadata cannot identify one). Must be empty. |

Retirement takes precedence. Among active imported rows, publication takes
precedence over closed/outside classification: closed editions can remain visible
in the public calendar and therefore count as published, without claiming they
are open. A missing authored cycle-year edition is unexplained even if a projected
edition exists. Recurrence occurrences and multiple editions count only once per
source row, identified by `metadata.row_id`; stable registry aliases use the same
metadata matching as the calendar API/importer.

The dated and rolling selection comes directly from `core/calendar_public.py`,
the same `build_calendar` called by `GET /calendar`. Its default window helper is
also used by the offline coverage gate. The default page period (`next12`) is
today in IST through the day before the clamped twelve-month anniversary,
inclusive (29 February becomes 28 February before subtracting a day). The API
still accepts explicit `from` and `to`; use the coverage window for comparison.

`source_rows` counts the actual JSON array, not its declared `count`.
`metadata_programmes` counts the sidecar mapping. `rows_without_metadata` and
`metadata_without_row` are counts with corresponding `_ids` lists; both should be
zero. `active_programmes` counts **all** active DB programmes, including the
separately reported `registry_only_active` (curated registry or other programmes
without a calendar source row). These are separate metrics, not extra row buckets.
`published_total = published_dated + published_rolling` counts source programmes,
not repeated occurrences, all registry programmes, or open applications.

## Reading the report and API

The daily refresh keeps its existing import summary (`imported`, `skipped`) and
logs exactly one `Calendar reconciliation {json}` line after committing import
and liveness updates. The payload contains the source digest, counts, the window (`from`, `to`,
`as_of`), metadata-gap IDs and public row IDs/slugs/reasons. No user fields, URLs,
SQL parameters or credentials are added to that line.

`GET /calendar/coverage` returns the same payload, publicly and read-only, with
the same per-IP rate-limit bucket, read-cache TTL and cache headers as `/calendar`.
Private calendar watch routes remain outside the shared cache. To compare with
`GET /calendar?from=...&to=...`, use the reported window with no filters and count
distinct source `metadata.row_id` values in `items` and `rolling`; registry-only
items have no source row and recurrence may produce many entries per programme.
The two endpoints can reflect different snapshots within the existing cache TTL.

Deploy smoke uses the checked-out source array and the existing `SMOKE_API_URL`
fixture. Deployment events check out the deployment SHA. It requires metadata
parity, an exact eight-bucket sum, no unexplained rows and a positive published
total. Pending imports are allowed just after a deploy and recorded in diagnostics;
the daily refresh is their gate. Smoke has no database connection.

### Deploy-order wait (PR #209 follow-up)

On 17 November 2026, Vercel completed at about 08:29:20 UTC, while Render went
live at 08:29:54. The deployment canary checked out the new SHA but hit the old
API, receiving 404 for coverage. Later data-only changes can instead return old
counts. A health response alone cannot identify which calendar data is loaded.

`source_digest` now identifies both loaded source JSON objects. Canonicalise each
with `json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)`
and encode as UTF-8; hash canonical source + `b"\n"` + canonical metadata with
SHA-256 and take the first 16 hex characters. Formatting, key order and line
endings do not change the digest. Reconciliation's `to_dict()` includes it in
both the coverage API response and the refresh log line.

Before checking coverage, smoke computes the same digest independently from the
checked-out files. It polls read-only coverage every 20 seconds for up to 360
seconds until HTTP 200 and the matching digest arrive. Old digests, missing
digests, 404s and transient fetch exceptions are failed polls. A wait prints
elapsed seconds and poll count. A timeout names the expected digest, last status
and last digest and directs the operator to check the Render deploy. Once the
digest matches, all existing coverage assertions run immediately; the wait does
not excuse incorrect buckets or unexplained rows.

The weekly career report is a user-facing email, so it deliberately carries no
internal calendar metrics. The founder's view of these numbers is the daily
"Calendar reconciliation" log line and `GET /calendar/coverage`.

## When refresh goes red

The import is already committed when pending/unexplained rows make the command
exit 1. Do not roll it back to hide the discrepancy. Read the single reconciliation
line, then inspect the listed public row IDs/slugs in the source and metadata.
For pending rows, inspect whether import omitted a newly added row; repair the
import/source issue and rerun the idempotent refresh. For unexplained rows, check
the authored cycle-year edition, alias/name collisions and metadata pairing.
For skipped rows, apply the existing category migration through the normal DB
runbook process; reconciliation never changes schema. A skipped row is explicitly
accounted for, not silently treated as a pending import. Never test against the
production database. If metadata mismatches appear, correct the source/sidecar
pair and redeploy; smoke deliberately fails them.

The existing offline `scripts.calendar_coverage` command is exercised by pytest
coverage tests in CI (the CLI is not a separate workflow step). CAL-04 adds the
runtime DB comparison and the deployment API comparison to that authored gate.

## Copy audit

Searched frontend copy, calendar page metadata/OG surfaces, email templates,
Telegram post generation, the weekly-report workflow and worker, README status
lines and the smoke README. No current calendar-derived claim of “169 open
opportunities” or equivalent was found. The calendar already labels its computed
result “programmes”; monthly counts describe displayed calendar entries. Telegram
uses crawled `Opportunity` candidates rather than calendar rows. Existing generic
opportunity counts refer to crawled listings. No frontend copy or UI change was
needed, and historical binding decision-log rows were left intact.

## Production numbers

Live numbers are always at `GET /calendar/coverage` and in the daily refresh's
"Calendar reconciliation" line; neither needs database access to read. The first
production reading after deployment is recorded on PR #209. No production data
was fetched or changed during implementation.
