Public captures from 12 November 2026 UTC (13 November IST), trimmed from
`_local/gov-samples/`. `provenance.json` records original URLs, status and SHA-256
of the **untrimmed** samples. No application forms, credentials or PDFs are copied.
Decorative SVGs, navigation and unrelated CMS fields are removed. ISRO retains
multiple notices in one `.row.list`, expired and undated archive rows.

Adapter slugs: `meity_careers`, `nic_dii`, `drdo`, `nec_internships`, `isro`.
Fixtures deliberately preserve MeitY's conflicting NIELIT due dates and missing
ACF, NIC's programme-end discrepancy and exact inline registration dates, DRDO's
CASDIC extension and selected/retired-consultant notices, and NEC's intake links.

Date-only application cutoffs use 23:59:59 IST; date-only publication uses
midnight IST. DRDO's generic card End Date remains inferred. Missing/conflicting
application dates remain unknown. Undated notices have a 45-day last-seen TTL,
guarded by recent source contact; dated notices use the existing deadline sweep.
None of these adapters authorises absence retirement.

Run the read-only probe from `backend/`:

```
uv run python -m scripts.probe_sources --source meity_careers,nic_dii,drdo,nec_internships,isro
```

No database environment variables are needed. In GitHub Actions, dispatch
**Probe government sources (US)** with the same comma-separated `sources` input.
It runs on `ubuntu-latest`, uses no secrets, and prints JSON health, coverage,
filter counts and up to five titles/deadlines per source. A degraded/broken
source produces a nonzero exit. US reachability remains unverified until that
workflow is run after merge.
