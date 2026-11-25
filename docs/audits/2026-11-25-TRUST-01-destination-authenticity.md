# TRUST-01 — destination authenticity

Work order: deterministic destination evidence, truthful Apply copy, conservative closure,
and private founder evaluation. No production connection, production sampling, dotenv read,
AI call, commit or push was performed for this work order.

## Investigation: the starting implementation

There are **23 adapter source slugs** in the worktree, rather than the onboarding snapshot's
16 live sources. This inventory describes code, not verified production configuration.

| Source | Apply URL origin | Source type |
| --- | --- | --- |
| greenhouse | Payload `absolute_url` | Employer ATS |
| lever | Payload `hostedUrl` | Employer ATS |
| ashby | Payload `jobUrl` | Employer ATS |
| smartrecruiters | Detail `postingUrl`, then `applyUrl`, then source URL | Employer ATS |
| workable | `application_url`, then `url`, then `shortlink` | Employer ATS |
| recruitee | `careers_apply_url`, then `careers_url`, then source URL | Employer ATS |
| keka | `https://<board>.keka.com/careers/jobdetails/<id>` | Employer ATS |
| workday | CXS `jobPostingInfo.externalUrl`, falling back to fetched source URL | Employer ATS; bounded search, not complete inventory |
| amazon | `https://www.amazon.jobs` plus payload `job_path` | Employer careers site |
| arbeitnow | Feed source URL | Aggregator; rolling feed |
| remoteok | Feed `url`, falling back to `apply_url`; normalized Apply uses that source URL | Aggregator; rolling feed |
| himalayas | `applicationLink`, `applicationUrl`, `applyUrl`, `apply_url`, then listing URL | Aggregator; Apply may already be an employer link |
| jobicy | Feed `url`, `jobUrl`, or `applyUrl`; normalized Apply uses source URL | Aggregator; rolling feed |
| unstop | `seo_url`, falling back to source URL | Aggregator for `/jobs` and `/internships`; competition platform for events |
| github_lists | Canonicalized record `url` from endorsed SimplifyJobs JSON lists | Re-poster; links commonly go directly to employers |
| devpost | Event `url`, falling back to source URL | Competition platform |
| devfolio | Event URL derived from its slug, falling back to source URL | Competition platform |
| hackerearth | Event `url` joined to platform base | Competition platform |
| isro | Official notice/detail URL collected by government adapter | Government |
| drdo | Official notice or attached notice URL | Government |
| meity_careers | First official attachment, falling back to careers page | Government |
| nec_internships | Official programme/notice URL | Government |
| nic_dii | Official DII schedule URL | Government |

Remotive is **not a current adapter**; its known feed hosts are nevertheless classified as
aggregators. Academic and government programme sites are also reached through the calendar
registry. Unrecognized domains remain unknown even when a source/company name looks familiar.

`scripts/discover_boards.py` shares GitHub's list fetcher, extracts exact ATS board identities
(including Workday's `tenant|wdN|site`), verifies them, and attaches company board data through
`seed_boards_batch`. Discovery does not itself insert application URLs. The next ATS crawl
provides them. GitHub ingestion skips known ATS links handled through this discovery path,
closed/invisible entries and known wrapped links; it removes tracking parameters and Ashby's
`/application` suffix. Its `meta.list_repo` and `meta.attribution` retain list provenance.

Calendar imports take `official_portal` into `programmes.url`. Authored registry seeds also use
`programmes.url`; annual evidence is separate in `programme_editions.source_url`, `verified_at`
and notes. Programme verification already calls the shared liveness function, so it inherits
the safer redirect/auth interpretation. This work order's stored facts/backfill and card/job
UI target **opportunities**, not a new programme schema or calendar workflow.

Storage before this change:

- `raw_listings.source_url` and `raw_payload` preserve upstream records.
- `opportunities.apply_url` is the canonical outbound link; `primary_source` owns canonical
  changes. `opportunity_sources.source_url`, `raw_listing_id` and `is_primary` retain dedup
  provenance. Secondary copies cannot overwrite canonical fields; existing direct-link
  upgrades remain in `pipeline/ingest.py`.
- `companies.domain`, `ats_type`, `ats_board_id` provide ownership context. A company name
  or source slug alone does not prove that a URL belongs to it.
- Source metadata includes `platform`, tags, GitHub list attribution, and government notice
  evidence. There was no persisted destination-facts object. `meta.liveness_checked_at`
  stored a rotation timestamp, rather than the outcome or terminal host.

Existing validation and liveness:

- `NormalizedListing` fell back to a web source URL when Apply failed `core.domains.http_url`.
  That helper checked scheme/host, but did not reject credentials or private IP destinations.
  GitHub and government adapters also have their own URL normalization/restrictions.
- `core/destination.py` classified the stored host at read time. It recognized broad ATS host
  suffixes without checking the company's board identity. Detail and saved-listing responses
  used it; feed cards only showed a source attribution. Old ATS copy called any recognized
  host the named company's careers listing. Unstop was treated as an event platform.
- Generic liveness followed redirects automatically, classified 404/410 as closed, 401/403,
  timeout and 5xx as inconclusive, and successful redirects (including login pages) as alive.
  Greenhouse's known `error=true` landing page was a soft 404. Workday checked CXS detail,
  rather than its always-successful HTML shell, but closed a 403 when a search control worked.
- `pipeline/liveness.py` selects active, undated, unclosed, unflagged, non-overridden listings
  unseen for four days and not checked for three days, excluding rolling-window sources.
  This selection remains. `_mark_closed` remains the only closure operation used here.
- `pipeline/expire.py` separately handles passed deadlines and proven crawl absence.
  `FULL_INVENTORY_SOURCES` is exactly `unstop`, `devpost`, `devfolio`, `github_lists`.
  Recent/complete coverage and the minimum-coverage breaker remain unchanged. Workday search
  absence and incomplete government traversal cannot prove closure.
- Detail Apply buttons already kept the real SSR outbound anchor, with the sign-in gate
  and `safeExternalUrl` guard. This work retains those flows and hardens the guard.

## Design and implementation

`core/destination_facts.py` provides the pure version-2 classifier. It takes explicit URL,
company domain/ATS board, source context, optional observation and timestamp inputs. It
returns URL validity, ASCII/IDNA host, registrable domain, one of the seven requested types,
verified-employer boolean, aggregator attribution/warning, status and warnings. URL hashes
tie observations to the exact link without copying query tokens into public metadata.
Explicit email Apply is opt-in at the classifier boundary; current HTTP Apply UI does not
introduce a new mail workflow.

Registrant parsing uses **one new pinned dependency**,
[`publicsuffixlist==1.1.2.20261109`](https://pypi.org/project/publicsuffixlist/1.1.2.20261109/).
Python's standard library and the repo's existing parent/subdomain helpers cannot compute
registrable domains reliably for suffixes such as `co.uk` or private tenants such as
`github.io`. The original backend had no PSL. The dependency bundles its
PSL and has no runtime dependency tree; no updater or network fetch is used. Upgrading the
snapshot requires an explicit dependency change and classifier-version review.

Facts live in the dedicated nullable **`opportunities.destination_facts` JSONB column**.
They never enter `meta`. Revision `c1d8e5a9b472` revises `ab6c9d2e4f71` and adds the
column without a default, index or backfill, using the repo's savepoint/lock_timeout retries.
List, detail and saved-item serializers expose the column; the shared list load profile
selects it up front so serialization cannot cause an extra query per card.

`computed_at` belongs to deterministic classification. `input_key` fingerprints the URL,
primary source, company id, domain and exact ATS binding; `url_key` identifies HTTP evidence.
The Opportunity hook runs only on insert or changes to `apply_url`, `company_id` or
`primary_source`. Meta-only writes never enter it. Equal input keys return the existing
facts unchanged, including the computation timestamp. Unchanged ingestion therefore writes
no destination update. Eligibility's existing metadata hook is unchanged.

There is **no Company update listener and no company-wide opportunity update**. Company
edits leave child rows alone. The next ingest or founder backfill detects stale evidence by
its fingerprint and refreshes only those facts. Loaded company evidence takes precedence over
the transaction-scoped lookup cache, including company edits in the same ORM transaction.
Backfill also detects changed URLs/sources and missing or older versions, skips future versions,
and writes only changed facts in bounded batches. Source metadata remains byte-for-byte intact.

Network results live in the same column: `checked_at`, status, warnings, terminal host/domain
and the observation record are supplied by the background check. No crawl/backfill advances
an HTTP check time. Reclassification preserves a matching observation; changing the URL
invalidates the old check instead of carrying its status to the new destination. `unchecked`
means there is no HTTP evidence for that URL.

`pipeline/destination_check.py` runs only from the existing liveness path (also reused by
existing programme verification). It limits redirects to five hops, reads at most 64 KiB per
generic response, checks elapsed time between reads/hops and retains the existing HTTP
timeouts. It rejects non-public literal IPs and non-public DNS answers before requests.
Permitted redirects are HTTP-to-HTTPS, same registrable site, exact matching ATS boards or
a company-tied known ATS board. Shared ATS domains do not make unrelated tenants trusted.
Greenhouse's known soft-404 redirects retain their existing interpretation.

Unrelated redirects stop **before fetching the target**. The recorded target host/domain is
observed from Location, not claimed as a checked terminal page. Downgrades, loops, hop limits,
invalid redirects, parked/for-sale signals and login walls remain visible evidence. HTTP 401
or a login host/path/form supports `sign_in_required`, including Workday. A bare 403 is not
evidence of an auth wall: 403/429 without login evidence are `unknown` with `blocked_403` or
`blocked_429`, never closed and never labelled sign-in required. Timeouts/5xx remain unknown.
Only existing positive liveness evidence reaches `_mark_closed`. A concurrent replacement
of the Apply URL cannot cause that new URL to be closed by an old check. No new absence or
closure path, read-time network request, AI call, workflow, or public per-row log is added.

`DestinationLabel.tsx` uses the EligibilityLabel text size/color, wraps long hosts and notices,
and appears on cards and the job page. It names the stored host, discloses re-posters even
when they link to an employer (without calling that employer link an aggregator page), labels
external sign-in requirements, and exposes unverified
redirect/parked/missing-page evidence. Missing facts are tolerated; the detail view retains
a conservative host fallback. Every integer version >=1 is accepted. Legacy ATS copy no
longer claims employer ownership while backfill is pending. Normalized ingest URLs and the
frontend guard reject unsafe schemes, credentials, malformed hosts and local/private IPs.

## Founder commands and rollout

**The founder must run the new migration from this worktree before merge/backend deployment.**
Deploy the frontend that tolerates a null column before running backfill. Keep the reviewer's
`publicsuffixlist==1.1.2.20261109` pin; no version bump is needed.
Set `DATABASE_URL` securely in the local shell to the chosen database; do not paste it into
logs. The new backfill/sampler require that variable explicitly and do not load dotenv files.

```powershell
Set-Location 'D:\Downloads\Aspirova\.claude\worktrees\destination-trust\backend'
uv sync --locked
uv run alembic upgrade c1d8e5a9b472
uv run python -m scripts.backfill_destination_facts --dry-run --batch 500
uv run python -m scripts.backfill_destination_facts --apply --batch 500
uv run python -m scripts.backfill_destination_facts --dry-run --batch 500
```

The dry run uses PostgreSQL READ ONLY and computes candidate changes without writing.
Apply uses short locked batches and updates only the facts column. Current matching inputs
and future versions are skipped; stale company-evidence fingerprints are recomputed. Repeating
apply without input changes writes zero rows and retains `computed_at` and HTTP timestamps.
Both modes print counts only and sanitize failures. Neither mode makes HTTP requests,
changes closure status, or rewrites source metadata. Completed batches survive interruption.
HTTP observations continue through the existing scheduled liveness job.

For the regression sample, choose a read-only production role if available; the sampler
also sets the transaction itself to READ ONLY:

```powershell
uv run python -m scripts.destination_eval sample --n 100 --out ../_local/eval/trust01/sample.jsonl
uv run python -m scripts.destination_eval score --sample ../_local/eval/trust01/sample.jsonl --labels ../_local/eval/trust01/labels.jsonl
```

The sampler reserves recorded 404/410/auth boundary examples when available, then
round-robins sources and distinct registrable domains before repeat domains;
it uses opportunities/company context only and never reads users or sends HTTP requests.
It refuses fewer than 100 rows, existing output files, or any output path outside the
git-ignored `_local/eval/trust01/` directory. A human independently creates `labels.jsonl`,
one JSON object per sampled id:

```json
{"id": 123, "type": "aggregator", "domain": "jobicy.com", "valid": true, "employer_verified": false, "status": "sign_in_required"}
```

Allowed types are `employer_ats`, `employer_site`, `aggregator`, `government`, `academic`,
`competition_platform`, `unknown`. Status is `unchecked`, `alive`, `gone`, `sign_in_required`,
`unknown`, or `invalid`. Domain labels describe the stored URL; redirect evidence has separate
terminal fields. Keep absent HTTP evidence `unchecked`; do not invent a successful check.

Score runs offline and prints only aggregate counts: type precision as TP/(TP+FP), recall as
TP/(TP+FN), exact-domain matches, validity/ownership accuracy, and missing/auth outcomes.
Exit 0 requires >=100 fully labelled sample rows, no mismatches, and both an HTTP 404 and auth
examples. Exit 1 means failed/incomplete acceptance; exit 2 means invalid input or tool error.
If the production sample lacks recorded gone/auth cases, acceptance stays incomplete; gather
those through the existing liveness workflow rather than assigning fabricated observations.
The committed fake-HTTP tests separately exercise 404, 410, 401, 403, login, timeout and 5xx.

For full validation on a disposable Postgres with pgvector installed, explicitly set its
local `DATABASE_URL` before migrations/tests:

```powershell
uv run alembic upgrade head
uv run pytest
uv run ruff check .
uv run black --check .
```

From `frontend/`:

```powershell
node --test lib/*.test.mjs
node node_modules/eslint/bin/eslint.js .
node node_modules/typescript/bin/tsc --noEmit
```

## Validation and remaining evidence — review round 1

- The reviewer's five failing regression cases pass locally **unchanged**: competition
  backfill, role backfill at batch sizes 1/2/500, and the slow liveness transaction test.
  The slow test function was compared against `origin/master` as bytes and is identical.
- The global socket DNS test double was removed. Fake HTTP tests now inject DNS acceptance
  only into the destination checker, so database connection resolution is untouched.
  Candidates and ATS context are frozen into plain values before the batch commit; there
  is no database access until HTTP checks finish. The real fake-transport path additionally
  asserts that the Session has no open transaction for 404/410/401/403/503 responses.
- Focused classifier, HTTP, ORM, API-loading, migration and liveness checks: **161 passed**.
  These assert that metadata-only writes do not update facts, unchanged ingests preserve
  computation timestamps, company edits do not UPDATE opportunities, and backfill repairs
  stale company evidence. The new column upgrade/downgrade and bounded lock retries pass.
- Related ingest/provenance/absence/retirement/backfill checks: **268 passed**, five
  vector-dependent cases deselected. Original metadata assertions have been restored;
  the prototype's metadata-comparison helper has been removed.
- Frontend lib node tests: **325 passed**. Opportunity page tests: **26 passed** after the
  trivial test-loader fix supplying the named `RemoteLabel` stub alongside its default
  export. This fixes the reported undefined-element failures without changing app behavior.
- Ruff, Black --check, eslint, TypeScript, lockfile validation and git diff --check all
  exited **0**. The installed dependency reports exactly
  `publicsuffixlist 1.1.2.20261109`; no local vendored parser is used for this review run.
- **Full migration-backed backend suite remains unverified here:** local PostgreSQL has no
  available `vector` extension. Destination SQL checks use an isolated local metadata schema
  whose unused embedding column is an array. The four unchanged backfill regression cases
  also map null vector casts to that local array type in an uncommitted test runner. This
  exercises their real JSONB/ORM updates but does not test pgvector behavior or the full
  Alembic chain. No production connection or `backend/.env` access was made.
- The earlier 390px browser inspection remains blocked by the unavailable browser host.
  The real notice DOM has wrapping safeguards and a render regression, but pixel/layout
  verification remains required.
- Production sampling and independent human labels were deliberately not run. The private
  sampler/scorer and synthetic hundred-row regression are ready for the founder.

## Review round 2 — evidence required for an auth label

The reviewer supplied a real 100-row production URL check: 78 alive, 10 gone (eight 410,
two 404), eight labelled sign-in required and four unknown. All eight sign-in labels were
false: five Himalayas and three Workday pages returned bare 403 to automated clients but
opened publicly in a browser. No login URL, form or redirect evidence was recorded.

The checker now requires HTTP 401, a login/SSO/auth host or path, or a detected login form.
Bare 403/429 responses stay unknown and record a blocked warning. This includes Workday CXS;
neither a working control nor a 403 alone can establish an authentication requirement.
A 403 carrying a valid login Location or a login form still records an auth wall. Isolated
sign-in wording and ordinary sign-in navigation do not qualify as a login form.

The frontend already displays the sign-in notice only for `sign_in_required`; new render
tests prove blocked 403/429 add neither a sign-in label nor an unknown-status notice. Offline
HTTP-403 scoring also requires recorded login-wall evidence instead of assuming authentication.
The existing slow-check regression function remains unchanged from `origin/master`.

Targeted pytest: **155 passed**, including Himalayas-style bot blocks, Workday CXS 403s,
401, login-host redirects, login forms, closure exclusion and the unchanged slow-check test.
Frontend lib tests: **326 passed**. Ruff, Black --check, eslint and TypeScript all exited **0**.
Tests used the existing local PostgreSQL compatibility schema; full pgvector validation
remains unavailable locally. No production URL was fetched in this round, and `_local/`
and the independent labeller's artifacts were not read or changed.

## Review round 3 — exact board forms and platform types

The reviewer scored the independently labelled 100-row production sample: domain and
validity 100/100, HTTP status 99/100 (one transient 502 answered 200 on recheck), gone handling
10/10, and bare-403 handling 8/8 unknown. Employer verification was 85/100, with **zero
invented employer origins**. The 15 disagreements were conservative false negatives.
These are reviewer-supplied baseline results; the production sample was not read or rerun here.

Classifier **v2** adds Workday `wdN.myworkdaysite.com/recruiting/<tenant>/<site>/...` and
normalizes Workday identities as `tenant|wdN|site`, including locale-prefixed myworkdayjobs
URLs and casing differences in the recorded site. All three identity components must
match the company's board. Recruitee, Keka, Personio and BambooHR DNS slugs compare without
case sensitivity; path-based Greenhouse, Lever, Ashby, SmartRecruiters and Workable tokens
retain exact comparisons. The existing eight token-based crawler adapters are covered;
Personio/BambooHR are additional strictly matched destination forms, not new adapters.
An exact company-domain/ATS binding remains ownership evidence under an inconclusive bot
block or timeout. Redirect, parked and other untrusted-target warnings still withhold an
origin claim; liveness and sign-in status do not change as part of these type corrections.

Unstop's `/jobs` and `/internships` paths remain aggregator listings. Its other paths,
including competitions, hackathons and quizzes, are competition-platform destinations.
Their UI says **Hosted on Unstop**, with no claim that the platform is the employer's own
page. Arbeitnow is recognized on any ICANN registrable TLD, including `.nl` and `.co.uk`;
an Arbeitnow-named tenant of `github.io` or an unrelated suffix remains unknown.

**Deliberately unchanged:** Devfolio subdomains and HackerEarth hackathon pages remain
`employer_verified=false` even when the platform was recorded as the company. The platform
does not prove organiser identity. Nine of the 15 independent-label disagreements are this
intentional rule, not permission to invent an employer origin. GitHub-list career hosts
without company-domain evidence also remain unknown; the optional host-name heuristic was
not adopted.

The existing founder backfill detects v1 facts as older and recomputes them as v2. It still
preserves matching network observations, skips future versions and is idempotent after
refresh. No schema migration, dependency change or production access is added in this round.
Targeted classifier/HTTP/PostgreSQL/liveness tests: **217 passed**. Frontend lib tests:
**328 passed**. Ruff, Black --check, eslint and TypeScript all exited **0**. `_local/`
was not read or changed. The full pgvector-backed suite remains unavailable locally.

## Draft PR text

**Title:** Label Apply destinations with versioned evidence and preserve auth walls

Apply links could identify an arbitrary ATS-hosted URL as the named employer's careers
page, and a login redirect could look live. Store deterministic destination facts, require
company-domain or exact ATS-board evidence before showing employer origin, and disclose
aggregators on cards and job pages. Existing background liveness now records bounded
redirects, login/parked targets and terminal domains. Auth walls never close a listing;
bare 403/429 responses stay unknown without a sign-in claim. HTTP 404/410 retain the existing
closure rules and coverage protections.

Adds a private read-only sampler, offline counts-only scorer and idempotent dry-run-first
backfill. Adds one nullable JSONB column with bounded migration-lock retries. Facts stay outside
source metadata, unchanged inputs keep stable timestamps, and company evidence refreshes lazily
without company-wide row locks. Deploy the tolerant frontend before founder backfill. Source,
classifier, fake-HTTP, focused PostgreSQL and frontend checks are recorded above. Full
pgvector-backed tests, browser verification at 390px and the founder's independently labelled
100-row production sample remain required before claiming the complete launch gate.
