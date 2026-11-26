# TRUST-02 — freshness and source liveness

Work order: launch audit TRUST-02, 2026-11-26. Base: `fee8290`, branch
`feat/freshness-service`. Deterministic only. No production access or production
measurement was performed. `backend/.env` was not read. No new dependencies.

## Investigation: what existed

Code inventory is **23 adapters**, not the older onboarding snapshot's 16 live
sources. This is an inventory of supported code, not confirmation that all 23
are enabled in production.

Every canonical opportunity has `first_seen_at` (discovery), `last_seen_at`
(positive crawl presence), optional `posted_at` (source date, not verification),
optional `deadline`, `closed_at`, and `status`. Provenance `seen_at` is initial
link creation, not an every-crawl heartbeat. `source_state.last_crawled_at`
describes a successfully finalized scope, not every listing in that scope.
`crawl_runs` records outcomes and COVERAGE; a partial run can be useful contact
without proving absence. TRUST-01's `destination_facts.checked_at` is the most
recent *attempt*, including unknown/auth/gone; its observation has the HTTP
status. It was not safe to call that timestamp “last verified”.

In the table, **board absence** means one complete employer board, never the
entire ATS vendor. **Inventory absence** means source-wide membership in
`FULL_INVENTORY_SOURCES`. All rows can close on an explicit passed deadline and
existing liveness 404/410 rules when applicable; Greenhouse's existing confirmed
soft-404 rule also remains. Dates below describe adapter inputs and may be null.

| Source | Coverage / absence authority | Date evidence today | Previous aging closure |
| --- | --- | --- | --- |
| greenhouse | Full board; board absence | `updated_at` feeds `posted_at`; no source deadline | None |
| lever | Full board; board absence | `createdAt`; no deadline | None |
| ashby | Full board; board absence | `publishedAt`; no deadline | None |
| smartrecruiters | Paginated board, declared total; board absence only after completion | Detail `releasedDate`; no deadline | None |
| recruitee | Full board; board absence | `published_at` / `created_at`; no deadline | None |
| workable | Full board; board absence | Publication date; no deadline | None |
| keka | Full board; board absence | Posting date when supplied; no deadline | None |
| amazon | Bounded term searches, 1,000 per query; **no absence authority** | Parsed posting date; no deadline | Old generic ATS branch did not exclude Amazon |
| workday | Bounded CXS term searches; **no absence authority** | CXS `startDate` / relative `postedOn` | None; CXS detail liveness |
| unstop | Full inventory; declared totals and paging coverage | `approved_date`, registration/application deadline | Inventory absence; adapter ignores already-old expired records |
| devpost | Full inventory when declared-total paging completes | Event deadline | Inventory absence |
| devfolio | Full inventory when every required listing set completes | Event deadline; no posted date | Inventory absence |
| github_lists | Full inventory only after all configured files validate; inactive entries excluded | `date_posted`; generally undated | Inventory absence |
| remoteok | Rolling newest window, although COVERAGE can say the fetched list is complete; **no absence** | Source posting date; no deadline | 30 days unseen while source reachable |
| arbeitnow | Rolling pages / bounded results; **no absence** | `created_at`; no deadline | 30 days unseen while reachable |
| jobicy | Bounded window; **no absence** | `pubDate`; no deadline | 30 days unseen while reachable |
| himalayas | Bounded window, kept count distinct from raw catalogue total; **no absence** | Source publication date; no deadline | **60** days unseen, not 30 (#162) |
| hackerearth | Event discovery, partial inventory; **no absence** | Event start and registration/end deadline | Deadline only |
| meity_careers | Government notice discovery; **no absence** | Notice posting date and extracted cutoff, if stated | Undated unseen notice after 45 days |
| nic_dii | Government notice discovery; **no absence** | Notice date / stated cutoff | Undated unseen notice after 45 days |
| drdo | Government notice discovery; **no absence** | Notice date / stated cutoff | Undated unseen notice after 45 days |
| nec_internships | Government notice discovery; **no absence** | Notice date / stated cutoff | Undated unseen notice after 45 days |
| isro | Government notice discovery; **no absence** | Notice date / stated cutoff | Undated unseen notice after 45 days |

Other existing closure/visibility rules:

* `expire.py` requires fresh SourceState (2 days) and a 6-hour absence margin.
  Source-wide expiry already required at least half the *currently open*
  catalogue and rejected recorded incomplete coverage, but did **not** require
  latest-run success. A failed ingest with complete fetch coverage could close
  rows using an older SourceState. There was no recent historical volume check.
* A hard-killed fetch left no new finished CrawlRun, allowing an older success
  to look like current evidence. ATS finalization does not advance SourceState
  on errors, but its expiry branch did not inspect the newest failed run.
* Repeated dead-board retirement uses the last three empty/not-found outcomes
  across at least 48 hours, rejects intervening errors, and checks board-qualified
  provenance. This existing stronger evidence path remains.
* The **305-day posting/discovery-age rule** stays in force under the
  [2026-08-17 Binding decision](../README.md#decision-log-append-only). A listing with an
  effective posting date older than 305 days and no future deadline stays stale.
  The effective date is `posted_at`, falling back to `first_seen_at`.
  Evergreen Lever requisitions can reappear in every crawl while remaining old.
  Source verification staleness is an additional exclusion.
* Closed rows have a 14-day grace. `cleanup_expired_competitions` actually
  hard-deletes closed rows across categories, as well as sufficiently old
  deadline-expired hackathons, competitions and internships and legacy expired
  rows. Withdrawals and manual report/duplicate closures are protected there.
  Rescue cannot recover a row already deleted; rediscovery must ingest it again.
* Re-seen rolling rows reopen only an explicit `rolling_window_ttl` closure
  (#163); full-inventory aggregator presence reopens rows unless a deadline or
  founder override still closes them. Government deadline extensions retain
  their specific same-ID, old-deadline and cancellation guards. Direct ATS
  re-seen closure recovery was missing and is added here.
* The old liveness worker selected only active, **undated**, unclosed listings
  unseen for 4 days, excluded rolling sources, and rotated every outcome for
  3 days. Its transaction/network separation from #224 remains in place.

Calendar programmes are separate entities. Editions have `verified_at`, explicit
status, opens/closes dates, and an official reference. The weekly review uses
90-day non-null verification aging and seasonal review months; missing
verification remains “expected”, never “open”. URL liveness flags review rather
than auto-promoting editions. Automatic overdue close also stamps `verified_at`,
so it cannot be substituted for a positive destination check. The daily calendar
refresh and weekly human review stay separate from opportunity cadence and SLOs.

### What time since verified could measure

Before this change the defensible lower-bound observation was canonical
`last_seen_at`, augmented only by a current **alive + 2xx** destination observation.
A newer unknown attempt could overwrite the old positive check. Posting dates,
source contact and a SourceState heartbeat must not refresh all rows of a board.

The existing `report_crawl_staleness` measures **source contact** (success OR
partial within 48 hours). COVERAGE measures enumeration, including bounded raw
windows, not age of every visible listing. Neither reports per-listing p50/p90/p99.
The canon records historical failures (approximately 2,000 erroneous absence
closures and the Himalayas 1,679-row TTL incident); these are incident evidence,
not current freshness measurements. There is no current production distribution
available in this checkout. No observed SLO percentage is claimed.

## Design and implementation

**Last verified** is the later of canonical `last_seen_at` from actual returned
listing IDs and a destination check with `status=alive` and HTTP 2xx. Merely
having a recent `checked_at`, a 3xx, auth wall, 403/429, timeout or 5xx never
advances it. `destination_facts.last_alive_at` retains the last positive check
across later inconclusive/gone observations for the same URL; URL changes discard
that evidence. Existing positive TRUST-01 observations work without a backfill.

Derive the timestamp with a Python helper and equivalent native SQL expression.
There is **no column, migration, index or bulk backfill**. Existing list reads
already load destination facts; there are no new joins, per-row queries, reader
writes or network calls. SQL ranking adds bounded timestamp/JSON evaluation
alongside its existing sort. Production-size query cost is unmeasured here and
must be checked before asserting a performance gate; a generated/stored column
is not justified without that measurement.

`core/freshness.py` is the active cadence configuration for every adapter and an
unknown-source fallback. “Tier” here is **freshness service priority**, independent
of the scheduler's historical `crawl_tier=1` daily group.

| Service tier / sources | Expected crawl | Liveness rotation | Soft stale threshold | Proposed SLO (founder rules) |
| --- | --- | --- | --- | --- |
| 1: all ATS, Unstop, GitHub lists | 24 h | 24 h | 168 h | At least 95% of visible rows verified within 48 h |
| 2: Devpost, Devfolio, HackerEarth; unknown source fallback | 24 h | 72 h | 240 h | At least 90% within 96 h |
| 2: five official government notice sources | 24 h | 72 h | 1,080 h (45 d) | At least 90% within 96 h |
| 3: RemoteOK, Arbeitnow, Jobicy | 24 h | 168 h | 720 h (30 d) | At least 90% within 240 h |
| 3: Himalayas | 24 h | 168 h | 1,440 h (60 d) | At least 90% within 240 h |

A listing is stale when either the posting-age rule applies or its last
verification is beyond the source threshold. Discovery and outbound picks
apply both checks, including feed, search, trending, landing, similar listings,
sitemap, company and saved-search alerts, digests, weekly reports, and Telegram.
Landing uses a per-row SQL expression. The detail page stays readable and
explains whether the posting is old or verification is overdue. Staleness
leaves `closed_at` unchanged.

Successful crawl presence refreshes verification for returned IDs. Returned
pages with a reversible stale or closed state are queued for freshness
revalidation. Direct ATS presence also reopens eligible closed returned rows.
The Greenhouse posted-date fast path and scoped row-locking changes (#225), and
concurrent ATS grouping/order/rollback isolation (#227), are retained. No code
in `pipeline/ingest.py` changes. Reopen updates match only already-closed returned
IDs, never lock all active rows of a company.

The scheduled liveness CLI opts into cadence checks for dated and partial-source
listings too. Legacy Python callers keep the old undated queue. A 2xx clears
verification staleness. Positively identified postings can reverse legacy TTL closure.
Checks are tied to unchanged URLs and a fresh post-check database read. Current
deadlines, safety withdrawals and manual corrections still win. A 404 result
cannot override a crawl confirmation newer than the check started. Absence
comparison also respects successful destination verification newer than a crawl.

**Rescue:** daily, last 7 days of partial-source closures and explicit absence
closures (plus legacy unlabelled closures from inventory-capable sources).
At most 100 candidates, 180-second soft budget, one worker, at least 1 second
between posting checks, and a 24-hour retry floor for all outcomes. Rescue uses
its own shorter retry floor so a rolling feed's 7-day liveness rotation cannot
outlast the rescue window. Only 2xx with the same terminal posting path/query
and a matching contiguous posting title reopens a hard-closed row. A redirect
to a generic careers page, parked/login page, changed posting, 404/410 or unknown
does not reopen it. Workday keeps its CXS detail endpoint and tenant pacing.
This conservative title check can miss valid postings; it does not infer a match.
Dry run is default; counts are the only public output. Checks and rescue notify
the existing page revalidation seam after committing; no transaction spans that
network call either.

**Absence circuit breaker:** retain the inventory allowlist and 2-day/6-hour/current
open-count protections, and additionally require finished success, zero errors,
and complete coverage when recorded. Latest volume must be at least half the
median of up to seven successful comparable runs from the previous 30 days,
scoped to the same source or ATS board. Missing legacy coverage remains compatible
with old records; newly recorded partial/unknown coverage fails closed. No
baseline permits a successful nonempty bootstrap, subject to existing guards.

Commit a running journal row before fetching and finish that same row afterwards.
A crash leaves `running`, blocking retirement. ATS prefetch has a separately
committed per-source batch barrier before any HTTP: incomplete/skipped boards
hold absence for their source, while another source can finish normally.
Per-board failures and low-volume guards remain independent. The breaker prints
counts and a GitHub Actions warning, preserving existing best-effort workflow
semantics. It does not block explicit passed deadlines or repeated confirmed
dead-board evidence. Amazon joins Workday in the bounded-search exclusion.

## Measurement and rollout

`scripts.freshness_slo` uses one **REPEATABLE READ, READ ONLY** transaction and a
120-second statement cap. Per-source and per-tier metrics include visible,
never-verified and stale counts, p50/p90/p99 verification ages, target hours,
and the percentage within target. Empty configured sources and tiers get an
explicit zero. Output contains only source or tier labels and aggregate metrics.
Connection failure emits a counts-only failure and exits 1.

The preview starts with open, active, unhidden, student-facing listings that pass
today's posting-age rule. Each `FRESHNESS IMPACT` line gives the baseline count,
how many would become stale under the combined rule, and how many would remain
visible. The preview prints counts for each configured source and the total.
Other source keys are grouped into `other`. Never-verified rows fail the target
and are excluded from verification-age percentiles. Tier percentiles aggregate
individual verification ages. The proposed targets are observational.

1. Run database checks below on the disposable instance; review query plans and
   a real 390px rendering. No schema migration is needed for TRUST-02 (the
   TRUST-01 destination column migration must already be present).
2. Deploy the tolerant frontend and backend together, then enable the changed
   daily workflow. Liveness/rescue use existing database/revalidation secrets.
   The workflow retains serialized runs and adds a bounded rescue and read-only
   measurement tail. Overall timeout includes these steps.
3. Founder records the impact preview and SLO output before rollout and after
   at least three daily runs. Compare source and tier tails and capacity exhaustion, not only source contact.
   Approve or amend the proposed targets after seeing those counts. Increase
   bounded throughput or adjust cadence only on that evidence; never relax
   absence safety to improve a freshness percentage.
4. No blanket reopen/backfill: old TTL closures recover on positive crawl/check
   evidence. Inspect rescue dry-run counts before an ad-hoc applied rescue.

### Exact founder commands

From `backend`, with the **throwaway** Postgres 17 + pgvector server running:

```powershell
uv run python -c "import psycopg; c=psycopg.connect('postgresql://postgres:test@localhost:56432/postgres', autocommit=True); c.execute('CREATE DATABASE test_freshness_trust02_review'); c.close()"
$env:DATABASE_URL = 'postgresql+psycopg://postgres:test@localhost:56432/test_freshness_trust02_review'
$env:DELIVERY_TEST_DATABASE_URL = $env:DATABASE_URL
uv run alembic upgrade head
uv run python -m scripts.seed_plans
uv run python -m scripts.seed_ci
New-Item -ItemType Directory -Force _local | Out-Null
$changedPythonFiles = @(git diff --name-only fee8290 -- '*.py' | ForEach-Object { $_ -replace '^backend/', '' })
uv run pytest --basetemp=_local/pytest-trust02-review
uv run ruff check .
uv run black --check @changedPythonFiles
```

Choose a new database name if that review database already exists; do not drop a
shared database. Create `_local` first if absent. From `frontend`:

```powershell
node --test
node node_modules/eslint/bin/eslint.js .
node node_modules/typescript/bin/tsc --noEmit
```

Only the founder runs these with their intended production database configured
in the existing environment. Restore that configuration after the local test
override; never copy its value into public logs:

```powershell
# Read-only production measurement; safe counts for the review log.
uv run python -m scripts.freshness_slo
# External checks, no database writes by default.
uv run python -m scripts.rescue_closed_listings
# Apply only after reviewing the dry run; the scheduled job uses the same bounds.
uv run python -m scripts.rescue_closed_listings --apply
uv run python -m scripts.check_listing_liveness --apply
```

## Validation and limits

The full Round 1 backend suite passed **6,944 tests** on the migrated Postgres
instance on localhost port 56432 with the CI plan and listing seeds. This
includes all six reported regressions and the #224 slow-check test. All 44 #235
landing query parity cases also passed in a separate run. Ruff, Black on 31
changed Python files, and `git diff --check` passed. The Windows sandbox
blocked removal of the old pytest temp folders. The 382 frontend Node tests
passed, along with ESLint and TypeScript.

The source-diversity fixtures used 30-day-old crawl timestamps. Those breached
the thresholds for Greenhouse and Unstop, while RemoteOK was near its cutoff.
The pagination test retains the original posting dates and source assertions.
Its fixtures now represent listings seen in a recent crawl. Telegram's
13-day-old domestic fixture likewise keeps its posting and discovery dates and
now reflects a recent crawl. The old fixture grouped discovery and last seen
13 days in the past, beyond the 10-day fallback verification threshold.
A separate Telegram test checks verification-stale exclusion. Other visibility fixtures now represent current crawl evidence.

The current #235 query ran on the same 62,000-row synthetic catalogue at
`fee8290` and on the branch, with 20,666 missing stored role ranks and 14,988
logo-eligible rows. Using `landing_perf.py --current-only`, the median sum of
Postgres execution times across three paired runs was 711 ms before and 558 ms
after for default landing, and 632 ms before and 482 ms after for India-preferred
landing. Each pair returned the same listing IDs and counts. These are local samples with warm or mixed buffers and concurrent test
activity. The legacy reference query timed out at 20 seconds on this data, so
the #235 fixtures cover parity separately.

Production impact counts and a real 390px rendering remain pending.

## File map

| File | Change |
| --- | --- |
| `backend/core/freshness.py` | Cadences, rescue bounds, Python/SQL verification and stale definitions. |
| `backend/core/destination_facts.py` | Retain URL-bound positive checks across later inconclusive observations. |
| `backend/crawlers/runner.py` | Durable crawl journals, prefetch barriers, returned-ID refresh and reopen. |
| `backend/pipeline/crawl_safety.py` | Latest-outcome and historical-volume absence circuit breaker. |
| `backend/pipeline/expire.py` | Apply breaker, exclude Amazon, record absence reason and honor newer verification. |
| `backend/pipeline/retirement.py` | Report rolling-feed soft aging without writing a TTL hard closure. |
| `backend/pipeline/liveness.py` | Cadence queue, retained checks, same-posting rescue, transaction and race guards. |
| `backend/pipeline/destination_check.py` | Conservative same-posting title/path/query evidence. |
| `backend/pipeline/saved_search_alerts.py` | Exclude stale saved-search picks. |
| `backend/scripts/check_listing_liveness.py` | Enable cadence, refresh page caches, print reopen counts. |
| `backend/scripts/rescue_closed_listings.py` | Bounded, serial, dry-run-first rescue command. |
| `backend/scripts/landing_perf.py` | Compare the live landing query across revisions. |
| `backend/scripts/freshness_slo.py` | Read-only per-source/tier counts, percentiles, target coverage and per-source/total impact preview. |
| `backend/scripts/expire_missing.py` | Report soft-aging and dead-board counts without board addresses. |
| `backend/api/filters.py` | Retain the posting-age rule and add verification staleness to the shared display and outbound predicates. |
| `backend/api/schemas.py` | Nullable verification timestamp, freshness state and threshold on list/detail. |
| `.github/workflows/crawl-tier1.yml` | Schedule rescue and read-only SLO reporting with bounded timeouts. |
| `frontend/lib/types.ts` | Optional freshness response fields for mixed deployments. |
| `frontend/lib/freshness.ts` | Missing-data-safe, hydration-aware freshness wording. |
| `frontend/components/FreshnessLabel.tsx` | Small wrapping freshness label. |
| `frontend/components/OpportunityCard.tsx` | Display freshness on cards. |
| `frontend/app/opportunity/[slug]/page.tsx` | Display freshness by the Apply destination. |
| `frontend/app/opportunity/[slug]/opengraph-image.tsx` | Apply the same stale policy to the social preview deadline. |
| `frontend/lib/freshness.test.mjs` | Data tolerance, relative/stale wording and rendered markup. |
| `backend/tests/test_company_list.py`, `test_facets.py`, `test_feed_filters.py`, `test_search.py`, `test_sitemap.py` | Refresh verification timestamps in fixtures intended to be visible. |
| `backend/tests/test_feed_source_diversity.py` | Use recent verification while retaining posting dates and source-order assertions. |
| `backend/tests/test_post_telegram.py` | Keep discovery age independent of verification and cover the source cutoff. |
| `backend/tests/test_freshness.py` | Cadence/evidence/breaker contracts, network transaction boundary and DB acceptance fixtures. |
| `backend/tests/test_audit_retirement.py` | Update historical TTL expectations to soft aging; keep board/provenance checks. |
| `backend/tests/test_government_retirement.py` | Assert soft aging while retaining deadline and extension behavior. |
| `backend/tests/test_runner.py` | Isolate new durable-journal operations from dispatch-only fake sessions. |
| `backend/tests/test_ats_parallel_ingest.py` | Preserve ingest/rollback checks; separate journal metadata from listing snapshots. |
| `backend/tests/test_crawler_reliability.py` | Isolate prefetch journal I/O in unit fake sessions. |
| `backend/tests/test_crawler_sources_runner.py` | Account for returned-ID reopen alongside unchanged refresh. |
| `docs/README.md` | Append the authorized Binding freshness/absence decision. |
| `docs/audits/2026-11-26-TRUST-02-freshness.md` | Investigation, design, proposed SLOs, runbook, validation and draft PR. |

## Draft PR text

**Title:** Add source freshness, safe absence retirement and bounded closure rescue

Listings can look current after their last successful check, while failed or
truncated full-inventory crawls can reuse older coverage to close live rows.
Define last verified from actual crawl presence or successful 2xx evidence,
retain that evidence across unknown checks, and soft-age listings by source.
Retain the Binding posting-age exclusion and add source verification staleness
to discovery and outbound picks. Detail pages explain the relevant stale state.
Both predicates leave hard closure to independent evidence.

Commit crawl-start evidence, require a successful complete run and a recent-volume
baseline before absence retirement, and exclude bounded Amazon searches. Add
bounded same-posting rescue and a read-only source/tier percentile reporter
with a per-source and total deploy-impact preview.
Preserve inventory provenance, unknown/auth behavior, scoped ingest locks and
transaction-free network checks. No migration or dependencies.

Round 1 validation is recorded above. Production impact counts and the 390px
browser check remain pending.
