# DISC-04 eligibility filtering — validation (2026-11-23)

Eligibility facts are parsed once when an opportunity's title, description or
source tags change, and served from the nullable `opportunities.eligibility_facts`
JSONB column. A missing dimension, or a NULL column on a row the backfill has not
reached, means **Not stated**. Graduation-year and study-level filters keep those
rows (marked "Eligibility not stated") unless the reader ticks "Only listings that
state it". Sorting is unchanged, and no regex runs at read time. The digest keeps
its original batch parser.

## Accuracy

The evaluation samples were drawn read-only from the public API. They live
outside this repository: the listing text is third-party content, and only counts
are recorded here. Run `scripts/eligibility_eval.py --sample <jsonl> --labels <jsonl>`
to reproduce the numbers with your own copy.

- **Tuning set:** 200 live listings across 20 sources and 4 categories. 120 were
  drawn at random and 80 from listings mentioning eligibility words. Labelled
  without access to the extractor; two labels were corrected after re-reading the
  full source text. The rules were developed against this set, so its scores are
  optimistic and are not the claim.
- **Held-out set:** 100 different live listings (60 random, 40 eligibility-word),
  labelled blind by a separate model run that never saw the extractor or the
  tuning labels. **These are the numbers to quote.**

Held-out results, measured before any change prompted by the held-out errors:

| dimension | stated in labels | precision | recall | used for filtering |
|---|---:|---:|---:|---|
| graduation years | 5 values | **1.00** (4/4) | 0.80 | yes |
| study level | 78 values | **0.96** (55/57) | 0.71 | yes |
| final year only | 0 | n/a | n/a | no (display) |
| required degree | 14 values | 0.75 (3/4) | 0.21 | no (display) |
| college restriction | 0 | n/a | n/a | no (display) |
| citizenship | 0 | n/a | n/a | no (display) |

Precision is the safety metric. A false statement can hide a listing a reader is
eligible for. A missed statement only leaves the listing in, marked Not stated.

The three held-out false positives were all general rule gaps:
- "or *bringing* equivalent hands-on experience" and "or equivalent *combination
  of education and* experience" were not recognised as alternatives to the
  degree.
- "graduate students working toward a *Doctor of Philosophy*" was read as
  master's level.

All three were fixed with general rules, and the tuning set did not regress.
After the fix the held-out set shows zero false positives. That figure is not
independent, because those rows motivated the fix; a fresh sample is needed for a
clean post-fix number.

For comparison, the first-pass extractor scored study-level precision 0.67 and
citizenship precision 0.13 on the tuning set. It read US export-control clauses
("citizen, permanent resident, or protected individual") as citizenship-only.
Those clauses are now ignored, because they are work-authorisation rules (DISC-06).

## Cost

- **Parsing:** median 3.2 ms per listing, p95 9.4 ms, max 14.9 ms (200 real
  descriptions, up to 15k characters). Parsing runs only when content changes.
  The backfill of about 26k live rows is roughly 1.5 minutes of CPU.
- **Filtering:** `scripts/eligibility_explain.sql` builds a synthetic 27,000-row
  table. Warm medians over 5 runs on local Postgres 17:

| query | median |
|---|---:|
| baseline, no eligibility filter | 2.49 ms |
| grad_year=2026 | 4.74 ms |
| grad_year=2026 + stage | 6.05 ms |
| grad_year=2026, stated only | 4.59 ms |

The extra cost applies only when a reader sets one of these filters.

## Rollout

1. Founder runs migration `fa5b8e3c7d21` (nullable column, lock-timeout retry,
   no rewrite) **before** the API deploys.
2. After merge, the founder runs `scripts/backfill_eligibility_facts.py --dry-run`,
   then the real run. It covers live rows in batches of 500 and prints counts only.

Until the backfill finishes, unparsed rows behave as Not stated.
