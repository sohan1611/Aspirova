# Part 2.3 — Isolated DB-Hop p95 (the Lever-2 Input)

*Doc handoffs/PHASE-2-HANDOFF.md §4: "the migration decision is data-driven:
if X-DB-Time-Ms p95 is itself over budget → Singapore consolidation is
justified; if the DB hop is fast and total time is dominated by compute →
the answer is a bigger Render instance or caching, not a DB move." This
records that measurement. The verdict is the architect's call — this is
data, not a decision.*

## Methodology

Same as the Phase-1 measurement (Doc handoffs/PHASE-1-REPORT.md §6): a
persistent `httpx.Client` (not a fresh process per request — that pays its
own TLS handshake and was discarded there as a methodology artifact), n=30
samples per endpoint, against the live `https://aspirova-api.onrender.com`.

Run **after** merging Phase 2 to `master` and confirming Render's
auto-deploy picked it up (verified live: `/dream-companies` returns 401,
not 404; `/feed` carries `X-Cache`/`X-Total-Time-Ms`/`X-DB-Time-Ms`
headers). Upstash is not configured yet (a manual prerequisite, §10), so
the cache fails open on every request — every sample below is a genuine,
uncached DB round trip, which is exactly what isolating the DB hop needs.

## Results (2026-07-05, n=30/endpoint)

| Endpoint | client wall-clock p50 / p95 / max | X-Total-Time-Ms p50 / p95 / max | X-DB-Time-Ms p50 / p95 / max |
|---|---|---|---|
| `/feed?limit=20` | 324.9 / 521.8 / 622.6 ms | 202.4 / 292.7 / 448.9 ms | 135.2 / 201.5 / 380.0 ms |
| `/search?q=software+engineer` | 401.6 / 418.3 / 1318.8 ms | 206.9 / 207.7 / 1218.0 ms | 139.6 / 140.6 / 1150.7 ms |
| `/opportunity/{slug}` | 292.1 / 308.3 / 340.4 ms | 192.0 / 192.9 / 197.7 ms | 126.3 / 126.8 / 128.8 ms |

**The isolated DB-hop p95 (Render Singapore → Supabase Mumbai) is 127–202ms
across the three endpoints** — roughly 65–70% of total server-side time in
every case, consistent with a genuine, consistent cross-region cost rather
than noise.

**X-Total-Time-Ms p95 (192–293ms) is itself comfortably under the 300ms
target** in every endpoint, even with the full DB hop included and with
Upstash caching not yet live to help further. This is a materially
different picture than the Phase-1 measurement (p95 361–388ms, over
target) — though the two aren't a controlled A/B (Part 2.4's crawler
refactor, general load, and simple day-to-day variance all differ between
the two measurements too, not just the new instrumentation).

The gap between client wall-clock p95 and X-Total-Time-Ms p95 (roughly
110–230ms) is network transit between the test machine and Render
Singapore, not server-side cost — expected, not a concern.

One outlier: `/search`'s max (1318.8ms wall-clock / 1150.7ms DB-time) was a
single slow sample, not reflected in its p95 — consistent with the
Phase-1 report's own finding that production latency is "over target and
highly variable," i.e. real but not dominant at the p95 level.

## What this suggests (not a ruling)

Per the handoff's own decision rule: the DB hop is real and measurable
(~130–200ms), but total server-side time is *already* under the 300ms
target including it, before Upstash caching is even configured. This
leans toward **not** treating Lever-2 (Singapore consolidation) as urgent
right now — but the actual go/no-go call is the architect's, not
engineering's, per the standing role model.

## Re-running this yourself

```bash
uv run python -m scripts.measure_latency --n 30
```
