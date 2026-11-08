# Crawler source fixtures

Captured from public endpoints on 2026-11-08, using Aspirova's bot identity.
These captures did not access any database or credentials.

- `github_lists_sample.json` contains compact, unmodified record samples from
  the two configured SimplifyJobs raw JSON files. Includes active, inactive,
  direct ATS and employer records with their original posting timestamps.
  Tests add inactive fixture-derived rows to exercise the >1000-record coverage
  threshold, and mutate URLs explicitly to test wrapped-link rejection.
- `workday_search_sample.json`: the complete first page of NVIDIA's CXS response
  to `{"appliedFacets":{},"limit":20,"offset":0,"searchText":"intern"}` at
  `https://nvidia.wd5.myworkdayjobs.com/wday/cxs/nvidia/NVIDIAExternalCareerSite/jobs`.
- `workday_detail_sample.json`: the detail response for that page's first
  posting, `DFT Intern - 2027`, via the same CXS prefix plus its `externalPath`.
  NVIDIA's robots file allowed `/NVIDIAExternalCareerSite/` at capture time.

Tests intercept HTTP with `httpx.MockTransport`. Paging, caps, retries, fallback
fields, and failures use explicit mutations of these captures, never live HTTP.

Active GitHub records include posting dates older than 180 days. The adapter
ingests active, visible records regardless of posting date, preserving the full
open inventory required for absence retirement. The configured files and this
fixture contain only the two SimplifyJobs lists.
