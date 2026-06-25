"""Dedup engine: collapse raw listings into one canonical opportunity per
real-world opportunity (Doc 03 sec 7, Doc 04 sec 9).

Phase 1 scoring: blocking by company_id + trigram similarity on
title_normalized + location agreement. Doc 04 sec 9 also calls for embedding
cosine similarity as a scoring signal - deferred until opportunity_embeddings
exists (Doc 05 sec 2.1, Phase 3/Step 5 of the build plan). Revisit the
threshold once real embeddings are available to combine with trigram.

Location agreement is NOT optional, even in Phase 1 - confirmed against
real ingested data: GitLab posts "Senior Solutions Architect" as 10
genuinely distinct real openings (Germany, US-West, US-Northeast, India,
UAE, ...), each with a different apply_url. Title-only matching collapsed
all 10 into one canonical opportunity, silently discarding 9 real
application links. Title similarity alone is not a sufficient signal.

THRESHOLD HISTORY (both rounds measured against real GitLab data, not
guessed): an initial 0.6 threshold (chosen from a synthetic example set)
turned out to have no safe margin once tested against real titles - pairs
that must NOT merge ("Staff Backend Engineer" vs "Senior Backend Engineer",
0.788; "Account Executive - US East" vs "- US West", 0.848; 7 more
real examples in the 0.63-0.85 range, all genuinely different roles/
territories/seniority levels) score in the SAME range as pairs that should
merge under a looser standard ("software engineering intern" vs "software
engineer intern", 0.828). There is no single threshold that separates those
two populations - title trigram similarity is a purely lexical signal blind
to seniority/territory semantics, which is exactly why Doc 04 sec 9 always
specified combining it with embedding cosine similarity (deferred to Phase
3, Doc 05 sec 2.1). Genuine real duplicates within Greenhouse's own board
(a re-posted req, a one-letter typo fix) scored 0.93-1.0 - cleanly separable
from every false-merge case at 0.90. Phase 1, with exactly one source, only
needs to catch near-exact re-posts; cross-source fuzzy matching is a Phase-3
problem. False splits (an unmerged near-duplicate shown twice) are the
deliberately-preferred failure mode over false merges (a hidden real
opportunity) per Doc 01 R5.
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core import models

TITLE_SIMILARITY_THRESHOLD = 0.90


def find_matching_opportunity(
    session: Session,
    company_id: int | None,
    title_normalized: str,
    location: str | None = None,
) -> models.Opportunity | None:
    """Returns the existing active opportunity this listing is the same
    real-world opportunity as, or None if it should become a new canonical
    opportunity.

    Blocking: without a company anchor we cannot safely dedup in Phase 1
    (comparing titles across the whole table would be both slow and prone
    to false merges) - such listings always become new opportunities.

    Location agreement: once a location is known on the incoming listing,
    only merge into an existing opportunity at the SAME location (exact,
    case-insensitive - Phase 1 has one source, so location-string format is
    internally consistent; cross-source format differences are a Phase-2
    concern once Lever/Ashby/aggregators are added). If either side has no
    location info, fall back to title similarity alone.
    """
    if company_id is None:
        return None

    similarity = func.similarity(models.Opportunity.title_normalized, title_normalized)
    query = (
        select(models.Opportunity)
        .where(models.Opportunity.company_id == company_id)
        .where(models.Opportunity.status == "active")
        .where(similarity >= TITLE_SIMILARITY_THRESHOLD)
    )
    if location:
        query = query.where(func.lower(models.Opportunity.location) == location.lower())
    query = query.order_by(similarity.desc()).limit(1)

    return session.scalars(query).first()
