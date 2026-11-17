# TRUST-06 and DISC-08: honest provenance and date labels (2026-11-17)

From the 15 Nov public-launch audit:

- **TRUST-06** (P0): "A valid crawler URL is not an authorized employer partnership." Acceptance: no misleading
  "verified" claims in 30 inspected cards.
- **DISC-08** (P1): "Crawler freshness can look like a new employer posting." Acceptance: source date vs crawler
  seen date cannot be mistaken in sampled UI.

## Finding: both were already met in production

Checked read-only on www.aspirova.org on 2026-11-17:

- **Cards.** 80 live cards across `/`, `/jobs`, `/internships`, `/competitions` and `/scholarships`: none carried
  "verified", "official", "trusted", "partner", "authorized", "certified" or "vetted". Third-party listings say so
  on the card ("via Unstop" on 58 of the 80).
- **Detail pages.** Every page states where Apply goes, from `core/destination.py` and
  `frontend/lib/applyDestination.ts`:
  - "Opens Amazon's own site (amazon.jobs)" (company)
  - "Opens SJ Innovation's careers listing, hosted on Keka (sjinnovation.keka.com)" (applicant-tracking system)
  - "Opens this listing on Unstop (unstop.com). Unstop is a job board, not Swiggy's own site." (job board)
  - "We haven't confirmed this is <company>'s own site." (unclassified)

  Each ends with "Aspirova never handles your application."
- **Dates.** `ListingFreshness` shows "Posted …" only when the source published a date, otherwise "Seen …"
  (tooltip: "Last seen on the source …"). "New" appears only for a source posting date under 7 days old. The
  detail page never invents a posted date ("Aspirova first found this listing on …"). Digest emails show no
  posted or seen dates at all.

## What changed: guards so it stays true

The production smoke suite (every 6 hours and on every Production deploy) now fails if:

1. Any card on `/internships` or `/jobs` has a line that is itself a verification badge ("Verified",
   "Official listing", "✓ Verified", "Trusted source" and similar). Whole-line matches only, so titles such as
   "Partner Manager" or "Certified Nursing Assistant" never trip it.
2. A card shows "New" without a "Posted" date beside it.
3. The first internship's detail page lacks the "Opens … Aspirova never handles your application." disclosure, or
   names a host other than the one the Apply link goes to.

The checks live in `smoke/provenance.py`, with unit tests in `smoke/tests/test_provenance.py`.

Not covered here: the ticket's "status confidence" indicator. That overlaps TRUST-02 (freshness and source
liveness service), which is still open.
