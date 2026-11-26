# TRUST-02 — freshness and source liveness

Work order: launch audit TRUST-02, 2026-11-26. Base: `fee8290`, branch
`feat/freshness-service`. Deterministic only. The founder supplied the
Round 2 and Round 3 production measurements. Engineering validation uses
disposable Postgres.

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
not current freshness measurements. The founder's current measurements are
recorded in the Round 2 finding below.

## Design and implementation

**Last verified** is the later of canonical `last_seen_at` from actual returned
listing IDs and a positive destination check. A check must return `status=alive`
with HTTP 2xx or, when it records no HTTP status, an explicit Boolean
`same_posting=true`. A recent `checked_at`, a 3xx, auth wall, 403/429, timeout or
5xx never advances verification. `destination_facts.last_alive_at` retains the
last positive check across later inconclusive/gone observations for the same
URL. URL changes discard that evidence. Existing positive TRUST-01 observations
work without a backfill.

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
listings too. Legacy Python callers keep the old undated queue. Positive checks
clear verification staleness. Positively identified postings can reverse legacy TTL closure.
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

## Round 2 Workday finding

The founder's read-only production preview reported **53,991 visible** listings
and **3,137 verification-stale**. Workday accounted for **3,027 of the 3,137**
stale rows and **58% of its 5,218 visible** rows. The Workday p50/p90/p99 were
241/310/385 hours, with 18.28% within 48 hours and zero never verified (initial
crawl presence counts). The other ATS sources reported zero stale rows and a
p50 below one hour. The remaining 110 stale rows were from Arbeitnow (64),
Himalayas (38), Jobicy (4), RemoteOK (1) and HackerEarth (3).

Workday crawls at most three pages per search term and also has a 25-second
board budget and a request cap. A still-live posting can age out of those
results. Before TRUST-01 (`a18c6e9`, November 25), checked rows only received
an attempt timestamp in `meta.liveness_checked_at`. An alive outcome was not
persisted. The TRUST-01 migration leaves older destination facts null, so
historical liveness checks cannot refresh the preview's verification age.
The current CXS checker already captures the HTTP 2xx and `checked_at`, and
the stored observation advances verification. Amazon's search API belongs to
the crawl adapter. Amazon liveness uses the standard HTTP destination checker
in this revision, which also records a 2xx when the posting responds.

At the repository baseline (`fee8290`), the scheduled check used the legacy
queue, which excluded listings with application deadlines. Workday has no
deadline and is outside the rolling-source exclusions. It becomes eligible
after four days unseen and three days since the last attempt, including an
inconclusive attempt. This leaves three days before the seven-day cutoff, and a
first inconclusive result can defer the retry past that cutoff. Never-checked
rows across sources precede every retry within one shared daily cap. The
Workday tenant lock serializes requests for a host, with a 0.5-second delay and
retries that honor `Retry-After` under the lock. Each batch finishes before
the next starts, so 1,500 selections do not guarantee 1,500 finished checks.
The aggregate preview cannot establish how many rows waited in the queue or
received inconclusive responses.

Round 2 moves public-catalogue rows from partial sources to the front of the
cadence queue once they are overdue or would cross their cutoff by the next
daily run. Within that group, first attempts since last confirmation precede
retries, and each group runs in stale-deadline order. The normal retry cooldown
still applies. Workday retains tenant pacing, and network checks still run
outside database transactions. The same evidence rule now applies to Python,
SQL and retained checks when a checker confirms a posting without an HTTP code.

## Round 3 throughput and verification capacity

The founder reported these production runs. Each reached its soft time budget.

| Run | Budget | Scanned | Alive | Closed | Reopened | Inconclusive |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Daily crawl, master | 600 s | 300 | 109 | 3 | — | 188 |
| PR #237 at `cef3bb6`, limit 1,500 | 600 s | 550 | 360 | 37 | 0 | 153 |
| PR #237 at `cef3bb6`, limit 4,000 | 3,600 s | 2,150 | 1,153 | 77 | 0 | 920 |

After the master run, Workday had **5,215 visible and 2,973 stale** listings.
The stale total comprised 2,785 without a stored check and 188 unknown with
an attempt less than three days old. Every other tier-1 source had zero stale
listings in that snapshot. The ten-minute branch run reduced Workday to **5,178 visible
and 2,576 stale**. Its 37 closures were real 404/410 responses. It scanned
0.92 rows/s and confirmed 0.60 alive/s, with 153/550 (27.8%) inconclusive.

The hour-long branch run used the same code, before the Round 3 changes.
Workday fell from **2,576 to 1,737 stale** and from **5,178 to 5,107 visible**.
Of those still stale, 534 had no stored check and 1,203 were unknown with a
check less than three days old. HackerEarth had one unknown and every other
source had zero stale listings. The run averaged 0.60 scans/s and 0.32 alive/s.
The inconclusive share rose from 28% to 43%. That makes unknown outcomes the
larger remaining Workday backlog. Sustained throttling or blocking by client
IP or shared Workday data centre (`wdN`) is plausible. The runs also sampled
different parts of the queue, and their totals give no HTTP reason breakdown.

The previous worker submitted 50 rows together in freshness-priority order.
The SQL has no tenant interleaving. Several workers could queue behind the same
Workday host lock while work for other hosts waited in the executor or the next
batch. A Workday request holds the lock through its 0.5-second delay, HTTP call
and any retry or backoff. The worker waited for the entire batch before its
set-based database writes, built a new HTTP client and executor per batch, and
reserved up to 50 seconds for the next 50 rows as if they could arrive in five
equal waves. The production totals measure end-to-end throughput. Database
time, network time and the production tenant distribution are unmeasured.

The dispatcher preserves SQL selection and order within each Workday data
centre. It admits one Workday CXS check per `wdN` across all its tenants.
With the 0.5-second delay before each request, including retries, each data
centre has a ceiling of two request starts per second. This is the pre-Round-3
ceiling for a single busy tenant, now shared across the data centre. The
previous worker could run multiple tenants on the same data centre at once.
Other data centres and sources use available workers. The dispatcher reuses
the HTTP client and executor. Once 50 results are ready, it drains the
in-flight checks, writes and commits the batch, then resumes dispatch. This
preserves #224 and the crawler's per-tenant lock and request delay.

A 429 or 503 pauses the whole data-centre queue for at least 30 seconds, or
longer if its `Retry-After` header (seconds or HTTP date) requires it. Three
consecutive HTTP timeouts in that data centre also trigger a 30-second pause.
The triggering check retains its inconclusive reason. The scheduler holds
queued checks outside the worker pool. A cooldown beyond the soft deadline
leaves those rows unattempted and eligible for a later run.

A local, counts-only mock used 60 valid CXS responses from three grouped
tenants (30/15/15), the real 0.5-second pacing, 10 workers, and 100/50/50 ms
simulated HTTP latency. The baseline finished in 26.58 s (**2.26 rows/s**)
and the initial Round 3 WIP finished in 18.07 s (**3.32 rows/s**) by
parallelizing three tenants on one data centre. With the final cap the three
tenants finished in 34.80 s (**1.72 rows/s**) on a shared data centre and
18.24 s (**3.29 rows/s**) when distributed across three. Production
throughput and the effect on unknown outcomes are pending.
The regression tests block one tenant's first check and verify that 24 checks
from two other data centres finish while the 500-row queue waits. They also
exercise pausing and resuming across tenants on the same data centre.

CXS direct 2xx with valid posting details already verifies a listing, and
404/410 already supplies closure evidence. A generic HTML page, malformed JSON
or a payload without the adapter's posting-detail shape now stays inconclusive
on 2xx. Other CXS inconclusive cases include malformed listing URLs, exhausted
timeouts, 403/429, other 4xx (including 401), 5xx and redirects without safe
terminal evidence. DNS and transport failures, auth and parked pages also stay
inconclusive for general destinations.
The daily script adds per-source totals and the fixed reason buckets
`timeout`, `403`, `429`, `5xx`, `other_4xx`, `parse_or_shape`, `redirect`,
`lock_or_budget` and `other`. The existing summary lines remain available
for tooling.

- Workday needs at least `ceil(2,600 / 7) = 372` positive confirmations
  per day for listings missed by the partial crawl. The old branch's 360 in
  600 seconds left a shortfall even before other sources. At the observed
  alive share over the hour (1,153/2,150), 372 requires about 694 attempts.
- For the other partial sources, use the count each crawl does not re-see.
  Daily positive demand is that count divided by 7 for Amazon, 10 for
  HackerEarth, 30 for RemoteOK, Arbeitnow and Jobicy, 60 for Himalayas, and
  45 for government notices, rounded up per source. Those steady-state
  populations are unmeasured. Round 2 did count 110 already-stale rows across
  the other partial sources. Covering those 110 in one day as well as
  Workday's 372 would require about 899 attempts at that alive share.
- The daily step now allows **2,400 seconds and 4,000 selections**. Even at
  the slower hour-long pre-fix rate, that budget projects about **1,433 scans
  and 769 alive confirmations per day**. That is about 397 confirmations above
  Workday's estimated steady-state need if the rate and outcome mix hold. The
  post-change Workday rate must average at least `372 / 2,400 = 0.155` alive/s
  to cover the Workday need over the full budget. Other sources share that time.
  The step retains its 60-minute hard cap and the job its 375-minute cap.
- Run a short counts-only `--dry-run` from the updated checkout. The Workday
  reason counts show whether 429/5xx/timeouts, 403, or redirect and payload
  problems dominate the unknown checks in that sample. They guide whether to
  investigate shared throttling, access blocks, or endpoint handling first.
  A short sample cannot locate an IP/shared-data-centre limit or measure the
  sustained rate. Use the daily totals and the read-only preview to verify
  capacity and the remaining backlog before enabling the discovery cutoff.
  Workday stays at 168 hours.

## Measurement and rollout

`scripts.freshness_slo` uses one **REPEATABLE READ, READ ONLY** transaction and a
120-second statement cap. Per-source and per-tier metrics include visible,
never-verified and stale counts, p50/p90/p99 verification ages, target hours,
and the percentage within target. Empty configured sources and tiers get an
explicit zero. Output contains only source or tier labels and aggregate metrics.
Connection failure emits a counts-only failure and exits 1.

`--diagnose` adds per-source counts for visible stale rows by destination
status and by `destination_facts.checked_at` age (`never`, `<3d`, `3-7d`,
`>7d`) in the same read-only snapshot. `never` means no stored destination
timestamp. Older workers could record only an attempt in listing metadata.
Unrecognized source/status values are grouped under fixed labels.

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
2. Clear the initial Workday backlog with the updated worker and preview as
   described above. Deploy the tolerant frontend and backend together, then
   enable the changed daily workflow. Liveness/rescue use existing
   database/revalidation secrets.
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
uv run python -m scripts.freshness_slo --diagnose
# External checks, no database writes by default.
uv run python -m scripts.rescue_closed_listings
uv run python -m scripts.check_listing_liveness --dry-run --max-seconds 300 --limit 500
# Apply only after reviewing the dry run; the scheduled job uses the same bounds.
uv run python -m scripts.rescue_closed_listings --apply
uv run python -m scripts.check_listing_liveness --apply --max-seconds 2400 --limit 4000
```

## Validation and limits

The full Round 1 backend suite passed **6,944 tests** on the migrated Postgres
instance on localhost port 56432 with the CI plan and listing seeds. This
includes all six reported regressions and the #224 slow-check test. All 44 #235
landing query parity cases also passed in a separate run. Ruff, Black on 31
changed Python files, and `git diff --check` passed. The Windows sandbox
blocked removal of the old pytest temp folders. The 382 frontend Node tests
passed, along with ESLint and TypeScript.

The full Round 2 backend suite passed **6,966 tests** on a fresh, migrated
database on localhost port 56432, including the unchanged #224 transaction
test and the TRUST-01 checks. Ruff, Black on the five changed Python files,
and all **382 frontend Node tests** passed. The counts-only diagnostic was
also exercised on the disposable database.

The final Round 3 backend suite passed **6,980 tests** on a fresh, migrated
database on localhost port 56432. This includes the unchanged #224 test,
the TRUST-01 closure checks, the Workday pacing and cooldown tests, and the
dry-run check for unchanged listing data. Ruff and Black passed.

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

Production impact counts are recorded above. Round 3 production
throughput and a real 390px rendering remain pending.

## File map

| File | Change |
| --- | --- |
| `backend/core/freshness.py` | Cadences, rescue bounds, Python/SQL verification and stale definitions. |
| `backend/core/destination_facts.py` | Retain URL-bound positive checks across later inconclusive observations. |
| `backend/crawlers/runner.py` | Durable crawl journals, prefetch barriers, returned-ID refresh and reopen. |
| `backend/pipeline/crawl_safety.py` | Latest-outcome and historical-volume absence circuit breaker. |
| `backend/pipeline/expire.py` | Apply breaker, exclude Amazon, record absence reason and honor newer verification. |
| `backend/pipeline/retirement.py` | Report rolling-feed soft aging without writing a TTL hard closure. |
| `backend/pipeline/liveness.py` | Cadence priority, Workday data-centre pacing and cooldowns, per-source counts and transaction/race guards. |
| `backend/pipeline/destination_check.py` | Conservative same-posting evidence, optional response validation and transport failure reasons. |
| `backend/crawlers/workday.py` | Share CXS posting-detail shape check with liveness. |
| `backend/crawlers/common.py` | Reuse Retry-After parsing for Workday data-centre cooldowns. |
| `backend/pipeline/saved_search_alerts.py` | Exclude stale saved-search picks. |
| `backend/scripts/check_listing_liveness.py` | Enable cadence, refresh page caches and add per-source outcomes and reason buckets. |
| `backend/scripts/rescue_closed_listings.py` | Bounded, serial, dry-run-first rescue command. |
| `backend/scripts/landing_perf.py` | Compare the live landing query across revisions. |
| `backend/scripts/freshness_slo.py` | Read-only per-source/tier counts, percentiles, impact preview and optional stale destination diagnostic. |
| `backend/scripts/expire_missing.py` | Report soft-aging and dead-board counts without board addresses. |
| `backend/api/filters.py` | Retain the posting-age rule and add verification staleness to the shared display and outbound predicates. |
| `backend/api/schemas.py` | Nullable verification timestamp, freshness state and threshold on list/detail. |
| `.github/workflows/crawl-tier1.yml` | Expand the daily liveness budget and schedule bounded rescue and read-only SLO reporting. |
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
| `backend/tests/test_liveness_round3.py` | Exercise tenant fairness, pacing, budget, Workday response shape and counts-only reporting. |
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
Define last verified from actual crawl presence or positive destination checks,
retain that evidence across unknown checks, and soft-age listings by source.
Retain the Binding posting-age exclusion and add source verification staleness
to discovery and outbound picks. Detail pages explain the relevant stale state.
Both predicates leave hard closure to independent evidence.

Commit crawl-start evidence, require a successful complete run and a recent-volume
baseline before absence retirement, and exclude bounded Amazon searches. Add
bounded same-posting rescue and a read-only source/tier percentile reporter
with a per-source and total deploy-impact preview. `--diagnose` shows stale
visible rows by destination status and time since the last stored attempt.
Preserve inventory provenance, unknown/auth behavior, scoped ingest locks and
transaction-free network checks. No migration or dependencies.

### Round 3

The founder's ten-minute branch run was 28% inconclusive. The hour-long run
reached 43%, and 1,203 of the remaining stale Workday listings had a recent
unknown result. The worker now gives each Workday data centre one request
at a time and pauses its queue on 429, 503 or three consecutive timeouts.
It honours Retry-After while other sources and data centres keep running.
Daily liveness gets 40 minutes and a 4,000-row cap. A dry run shows the
inconclusive reasons by source without writing any listing data.
