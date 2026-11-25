# Landing feed timeout — 2026-11-25

Work order: repair the default home feed and bound Vercel build reads. Base:
`00f6f24`, branch `fix/landing-feed-timeout`. All database work below used the
throwaway Postgres at **localhost:56432**. No production access, dotenv reads,
commits, pushes, index changes or migrations were performed against production.

## Diagnosis

The old landing path embeds the filtered source-rank/count query twice inside
each card-selection query, then executes that shape for both natural and famous
pools (a third time when relaxing the company cap). It repeatedly joins the
ranked ids back to opportunities, carries card JSON through selection, repeats
logo EXISTS predicates and full-result window counts, and repeats ranking work.

The dangerous cost is **planner-sensitive join multiplication**, rather than
merely the cost of a regex or a single count. On the synthetic dataset, one old
plan estimated the capped join at 11 rows, actually produced 3,847, and chose a
nested loop over 26,511 source-ranked rows and a materialized capped pool. It
discarded **101,983,970 join pairs**. The first selection alone took 8,131 ms;
the subsequent famous selection took another 6,635 ms. Earlier plans on the
same logical data used a hash join and finished the two selections in roughly
0.75–1.14 seconds. Re-ANALYZE after exercising different NULL-rank distributions
exposed the much slower plan. No planner settings were forced.

Representative old EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON), limit 24:

```text
Limit: actual rows=24
  Sort
    Nested Loop: estimated rows=11, actual rows=3847
      Join Filter: opportunities_1.id = opportunities.id
      Rows Removed by Join Filter: 101983970
      WindowAgg: actual rows=26511, loops=1
      Materialize: actual rows=3847, loops=26511
Execution Time: 8131.210 ms
```

History comparison:

- `62e2342` adds optional graduation/stage predicates and adds
  `eligibility_facts` to the card load profile. With default parameters,
  `eligibility_filters()` returns no predicates. It does not change landing.py.
- `a8bf7aa` adds optional visa predicates and changes country-scope predicates.
  Both are inactive for the clean default request, including `prefer_country=IN`
  (which reorders only). It does not change landing.py or the load profile.
- The repeated source/window/count/self-join shape already exists before both
  commits, following DISC-02/05. On identical current synthetic data, changing
  only the list-column profile to its historical versions still produces a
  slow first selection: pre-DISC-04 **6,395 ms**, DISC-04/06 **6,325 ms**, and
  current **6,128 ms**. These are profile comparisons, not historical data restores.

The added JSONB load and changing catalogue/statistics can expose the existing
bad shape. The exact production plan and production NULL-rank coverage remain
unknown; the incident's precise 20-second cancellation was not reproduced here.
The optional filters themselves are not evidence of the default-query regression.

## Fix and equivalence

`landing_feed_rows()` evaluates the visibility predicates once and materializes
only ids, company identity/flags and scalar ordering keys. Source ranks are
computed **before** excluding logoless companies, preserving their influence on
source diversity. Company and landing ranks run on this narrow candidate set.

A plain aggregate over those ranked candidates supplies the exact total and
capped-pool size, without full-set count windows. The natural and famous pools
are selected together with explicit final ordering, returning at most twice the
requested number of narrow rows. Python applies the unchanged quota/interleave
rules; a second indexed id lookup hydrates only the selected cards. Because this
branch is exclusively the open landing page, `open_total == total` remains exact.

The legacy query builder is retained in `tests/landing_reference.py`. Tests run
both shapes on the same transaction and assert ordered **ids**, exact totals and
every response field. Cases cover limits 1/5/24/100, default, India preference,
students true/false, roles, domestic/remote scope, graduation/stage filters,
stated-only eligibility, visa, scarce candidates and all/no famous or logo rows.
Filtered requests retain the ordinary feed query, as before.

Stored role ranks are used where present. The existing write trigger maintains
new/changed rows; its migration deliberately leaves legacy ranks NULL. Keeping
the regex fallback preserves results until the founder chooses to run the
existing `scripts.backfill_role_rank` dry-run/batched backfill. Tests and timings
include legacy NULLs, including an all-NULL run; deploying this fix does not
depend on a backfill. Production coverage can be checked separately by the founder:

```sql
SELECT count(*) AS active_rows,
       count(*) FILTER (WHERE role_rank IS NULL) AS missing_rank
FROM opportunities WHERE status = 'active';
```

No index is added: EXPLAIN identifies repeated window work and bad joins as the
problem. The replacement does a single visibility scan and a bounded primary-key
hydration lookup, already below budget with the existing indexes.

## Performance proof

Postgres **17.10 + pgvector**, fresh Alembic head `c1d8e5a9b472`, synthetic
**62,000 opportunities / 5,600 companies**. Companies: 60% logos, some ranked as
famous. Listings: 34,100 active, **26,511 open/visible**, **14,988 logo-eligible**;
skewed companies, 17 sources, tied timestamps, India/foreign/unknown countries,
remote rows, expired/stale rows, eligibility/meta arrays and nontrivial JSON/text.
The mixed dataset has **20,666 NULL role ranks**. Every comparison returns the
same ordered ids and `total = open_total = 14,988`.

Settings: JIT on, work_mem 4 MiB, shared_buffers 128 MiB, max parallel workers per
gather 2. API/L1/L2 read caches are bypassed by direct route invocation. Database
buffers are warm/mixed, not flushed; other local tests ran during some samples.
Numbers are sums of server **Execution Time** for both SQL statements, excluding
network, ORM serialization and the additional instrumenting EXPLAIN executions.
These are local samples, not production latency or a p95 claim.

| Dataset / request | Before, ms | After, ms |
|---|---:|---:|
| Mixed ranks, default limit 20 | 12,961.797 | 260.664 |
| Mixed ranks, limit 20, prefer_country=IN | 12,940.511 | 245.070 |
| Mixed ranks, limit 24, slow-plan sample | 14,765.787 | 673.481 |
| Mixed ranks, limit 24, prefer_country=IN | 14,702.367 | 255.264 |
| All ranks stored, limit 24 | 1,074.734 | 117.918 |
| All ranks NULL, limit 24 | 1,688.276 | 463.467 |
| All ranks NULL, limit 24, prefer_country=IN | 1,665.167 | 463.601 |

For default limit 20, aggregate shared hit/read buffer accesses drop from
**451,466 to 16,457**. The final card lookup takes **0.217 ms**. The new plan has
one materialized candidate source window and one materialized company/landing
rank set, a plain aggregate, two bounded top-N selections and an Append/final
sort. It has no repeated rank-to-opportunity cross-product. Some narrow windows
spill at the stock 4 MiB work_mem; no server tuning was needed.

Reproduce after creating an empty `aspirova_perf` database on the supplied local
service and applying `alembic upgrade head` with that explicit database URL:

```powershell
backend/.venv/Scripts/python.exe backend/scripts/landing_perf.py --seed
backend/.venv/Scripts/python.exe backend/scripts/landing_perf.py --role-ranks stored --output _local/landing-perf-stored.json
backend/.venv/Scripts/python.exe backend/scripts/landing_perf.py --role-ranks null --output _local/landing-perf-null.json
backend/.venv/Scripts/python.exe backend/scripts/landing_perf.py --role-ranks mixed --output _local/landing-perf-mixed.json
backend/.venv/Scripts/python.exe backend/scripts/landing_perf.py --limit 20 --output _local/landing-perf-default20.json
```

The script disables dotenv loading and rejects destinations other than
localhost:56432/aspirova_perf, including URL query overrides. It seeds only an
empty database, retains the application's 20-second statement timeout for reads,
captures complete JSON EXPLAIN plans with adapted parameters and checks parity.
Raw plans from this run remain in the worktree's ignored `_local/` directory.

## Build behavior and validation

Vercel production builds retain the existing 3/8-second transient retries, but
one **40-second deadline covers all attempts and waits**. Exhaustion or the third
transient failure returns `failedList(null)`, preserving the unavailable/recovery
state rather than publishing a successful empty count. The deadline also aborts
the active home fetch through the existing fetchListing signal support. All five
home reads run concurrently, leaving time for rendering under Next's 60-second
page limit. Client mount recovery and later ISR fill the page. Runtime failures
still throw so ISR retains good HTML; unknown errors and non-429 4xx responses
still throw during Vercel builds. CI/local build behavior is unchanged.

Tests exercise deadline expiry during a stalled read, retry wait and later
attempt; signal propagation and cancellation; transient exhaustion; successful
retry/true zero; real 4xx/unknown failures; runtime and CI/local behavior; and a
rendered home page that keeps healthy blocks when its feed read stalls.

- Backend: **6,877 passed**, exit **0**, on a separate local throwaway
  `aspirova_landing_test` database with migrations and the CI seeds.
- Initial full pytest: 6,852 passed / 25 fixture errors because Windows denied
  the default temp directory. Re-running with the verified worktree-local
  `--basetemp=../_local/pytest-landing-20261125-full` passed every test in 240 s.
- Ruff: exit **0**. Black `--check .`: exit **0**.
- Frontend full node suite: **371 passed**, exit **0**. ESLint and
  `tsc --noEmit`: exit **0**.
- Production/Vercel deployment and a real `next build` against a stalled API
  were not run. Build behavior was verified with fake deadlines, actual modules,
  signal propagation and rendered React output. The architect should verify the
  deployed feed/revalidation after review. No production action was performed.

## Draft PR description

**Title:** Fix landing feed join explosion and bound Vercel build API reads

The default logo-preferred home feed can time out because its nested ranking
queries repeat full-result windows and choose a badly underestimated nested
loop. Materialize narrow candidates once, retain exact totals and existing
source/company/famous ordering, then hydrate only the selected cards. On 62k
synthetic listings, default-feed EXPLAIN execution fell from **12,962 ms to
261 ms**; the all-NULL role-rank case remains below **464 ms**. No index or
production backfill is required.

Vercel build reads now have a **40 s total retry budget**, abort the active home
request and render the existing recovery shell on transient exhaustion.
Non-transient/4xx, runtime and CI/local behavior is preserved. Validation:
6,877 backend tests, old/new parity, frontend node tests, Ruff, Black, ESLint and
TypeScript passed. Local evidence and production-verification limits are in this
audit; no production access or deployment was performed.
