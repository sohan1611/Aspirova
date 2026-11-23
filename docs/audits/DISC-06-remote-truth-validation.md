# DISC-06 remote truth and work authorization — validation (2026-11-23)

A remote role is never assumed to be open worldwide. Remote mode, remote regions,
existing work authorization, visa sponsorship and time-zone windows come only
from listing text, source tags (github_lists `sponsorship`), and remote-board
location restrictions when the listing is remote. They are stored in the
existing `eligibility_facts` JSONB (parser version 3, no migration). A missing
key means **Not stated**.

## Filters
- **Domestic C:** physical country C, or a remote role whose region is not stated
  (shown and marked) or covers C. Coverage means C itself, WORLDWIDE, or a region
  token containing C (`regions_for_country`).
- **Domestic + remote abroad:** the same rule, without requiring a country-less row.
- **Abroad C:** other countries, minus remote rows whose stated region covers C.
- **`visa=needs` (opt-in):** drops rows that state no visa sponsorship, or that
  require existing work authorization for another country. Rows that don't
  state it stay.

## Accuracy
Truth labels for the same two samples as DISC-04 (200 tuning, 100 held-out live
listings from the public API, kept outside the repository). They were labelled
blind by a separate model run that never saw the extractor.

Held-out results, measured before any change prompted by held-out errors:

| dimension | precision | recall | used for filtering |
|---|---:|---:|---|
| remote regions | **0.92** (12/13) | 0.80 | yes (domestic / remote abroad) |
| work authorization | **1.00** (7/7) | 0.54 | yes (`visa=needs`) |
| visa sponsorship | **1.00** (1/1) | 0.20 | yes (`visa=needs`) |
| time zones | 1.00 (2/2) | 1.00 | no (display) |
| remote mode | 1.00 (4/4) | 0.10 | no (display) |

The held-out errors pointed at general rule gaps, which were then fixed:
- "Remote - Japan" read as WORLDWIDE because of a "work from anywhere" culture line.
- "ineligible for visa sponsorship" and "unable to offer … immigration
  sponsorship" were missed.
- A "Bonus" bullet section swallowed a later citizenship line.
- An E-Verify notice was read as an authorization rule.

After the fixes, both sets score precision 1.00 on every filtering dimension.
Tuning recall: regions 0.76, work authorization 0.91, visa 0.89. The held-out
figures after the fixes are not independent, so the table above is the claim.
Remote mode is deliberately conservative: it uses only explicit
work-arrangement statements, and conflicting statements leave it Not stated.

All DISC-04 dimensions score exactly as before on both sets.

## Local check (throwaway database, real Chrome, 1280 and 390 px)
Seven seeded listings: US-only remote, worldwide, unstated, India-only, onsite
Bengaluru, LATAM, US/Canada with Eastern hours.
- Domestic IN keeps Bengaluru, India-only, worldwide and unstated, and drops
  US-only, US/Canada and LATAM.
- Domestic US keeps US-only, US/Canada, worldwide and unstated.
- `visa=needs` drops only the US role that refuses sponsorship.
- Cards read "Remote · India only", "Remote · Worldwide", "On-site", and
  "Remote — where you can work from is not stated".
- `scrollWidth` is 390 at 390 px. No page errors.

## Rollout
No migration. After merge, once Vercel serves the new frontend, the founder reruns
`scripts/backfill_eligibility_facts.py`. It re-reads every row with version < 3.
