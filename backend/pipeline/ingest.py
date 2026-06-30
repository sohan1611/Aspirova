"""Ingest pipeline: adapter output -> raw_listings -> dedup -> canonical
opportunities, with full provenance (Doc 03 sec 3.3-3.5, Doc 04 sec 7 & 9).
Idempotent at every stage - re-running the same raw listing makes zero new
rows (Doc 04 sec 9: "re-running a crawl must not create duplicate canonical
opps").
"""

import hashlib
import re

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core import models
from core.adapters import NormalizedListing, RawListing
from pipeline.dedup import find_matching_opportunity
from pipeline.normalize import normalize_title


def _slugify(text: str) -> str:
    slug = text.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    return re.sub(r"-+", "-", slug).strip("-")


def _make_opportunity_slug(company_name: str, title: str, raw: RawListing) -> str:
    base = _slugify(f"{company_name}-{title}")[:80] or "opportunity"
    # Disambiguator derived from the listing that CREATED this opportunity -
    # never recomputed on a later dedup merge, so existing slugs/links never
    # change once set (Doc 03 sec 3.4).
    disambiguator = hashlib.sha256(f"{raw.external_id}|{raw.source_url}".encode()).hexdigest()[:8]
    return f"{base}-{disambiguator}"


def _ensure_provenance(
    session: Session,
    opportunity: models.Opportunity,
    source_id: int,
    raw: RawListing,
    raw_row: models.RawListing,
    *,
    is_primary: bool,
) -> None:
    existing_link = session.scalar(
        select(models.OpportunitySource).where(
            models.OpportunitySource.opportunity_id == opportunity.id,
            models.OpportunitySource.source_id == source_id,
            models.OpportunitySource.source_url == raw.source_url,
        )
    )
    if existing_link is None:
        session.add(
            models.OpportunitySource(
                opportunity_id=opportunity.id,
                source_id=source_id,
                source_url=raw.source_url,
                raw_listing_id=raw_row.id,
                is_primary=is_primary,
            )
        )
    elif existing_link.raw_listing_id != raw_row.id:
        # Keep provenance pointing at the current raw_listings row - it can
        # go stale if raw_listings was pruned and a fresh row created on a
        # later crawl (Doc 03 sec 8 retention).
        existing_link.raw_listing_id = raw_row.id


def ingest_normalized_listing(
    session: Session,
    source_id: int,
    company_id: int | None,
    raw: RawListing,
    normalized: NormalizedListing,
) -> tuple[models.Opportunity, bool]:
    """Returns (opportunity, is_new_canonical_opportunity).

    Idempotent: a repeat call with byte-identical raw content (same
    content_hash) is a near-no-op - only last_seen_at is touched.
    """
    raw_row = session.scalar(
        select(models.RawListing).where(
            models.RawListing.source_id == source_id,
            models.RawListing.external_id == raw.external_id,
        )
    )

    if raw_row is not None and raw_row.opportunity_id is not None:
        # Identity fast-path: this raw listing is already linked to a
        # canonical opportunity by (source_id, external_id) identity - the
        # strongest possible match, stronger than fuzzy dedup. Re-link and
        # refresh directly; never re-run dedup or risk creating a new
        # opportunity here.
        #
        # This is the fix for a real production bug (confirmed live: 2 of
        # ~2,321 listings in GH Actions run 28420810872): when a listing's
        # CONTENT changes (e.g. its location is edited) but raw_row already
        # points at an opportunity, the old code fell through to
        # find_matching_opportunity() - whose exact-location filter
        # correctly refuses to self-match a listing whose location just
        # changed, returning None - which then tried to INSERT a new
        # opportunity at the SAME deterministic slug (the hash suffix is
        # derived from external_id|source_url, neither of which changed),
        # raising opportunities_slug_key.
        opportunity = session.get(models.Opportunity, raw_row.opportunity_id)
        content_changed = raw_row.content_hash != raw.content_hash

        if content_changed:
            raw_row.content_hash = raw.content_hash
            raw_row.raw_payload = raw.raw_payload
            if len(normalized.description_raw or "") > len(opportunity.description_raw or ""):
                opportunity.description_raw = normalized.description_raw
            opportunity.title = normalized.title
            opportunity.title_normalized = normalize_title(normalized.title)
            opportunity.location = normalized.location
            opportunity.is_remote = normalized.is_remote
            opportunity.deadline = normalized.deadline
            opportunity.deadline_confidence = normalized.deadline_confidence

        opportunity.last_seen_at = func.now()
        raw_row.processed = True

        _ensure_provenance(session, opportunity, source_id, raw, raw_row, is_primary=False)

        return opportunity, False

    if raw_row is None:
        raw_row = models.RawListing(
            source_id=source_id,
            source_url=raw.source_url,
            external_id=raw.external_id,
            content_hash=raw.content_hash,
            raw_payload=raw.raw_payload,
        )
        session.add(raw_row)
    else:
        raw_row.content_hash = raw.content_hash
        raw_row.raw_payload = raw.raw_payload

    title_normalized = normalize_title(normalized.title)
    match = find_matching_opportunity(
        session, company_id, title_normalized, location=normalized.location
    )

    if match is not None:
        if len(normalized.description_raw or "") > len(match.description_raw or ""):
            match.description_raw = normalized.description_raw
        match.last_seen_at = func.now()
        opportunity, is_new = match, False
    else:
        slug = _make_opportunity_slug(normalized.company_name, normalized.title, raw)
        existing_by_slug = session.scalar(
            select(models.Opportunity).where(models.Opportunity.slug == slug)
        )
        if existing_by_slug is not None:
            # Safety net for the variant where raw_listings was pruned
            # (Doc 03 sec 8 retention policy) but the opportunity it
            # originally created still exists: there's no raw_row to
            # identity-match through above, but the deterministic slug is
            # still a reliable merge key. Soft-merge instead of a hard
            # INSERT failure.
            opportunity = existing_by_slug
            if len(normalized.description_raw or "") > len(opportunity.description_raw or ""):
                opportunity.description_raw = normalized.description_raw
            opportunity.last_seen_at = func.now()
            is_new = False
        else:
            opportunity = models.Opportunity(
                slug=slug,
                company_id=company_id,
                title=normalized.title,
                title_normalized=title_normalized,
                category=normalized.category,
                location=normalized.location,
                is_remote=normalized.is_remote,
                description_raw=normalized.description_raw,
                apply_url=normalized.apply_url,
                posted_at=normalized.posted_at,
                deadline=normalized.deadline,
                deadline_confidence=normalized.deadline_confidence,
            )
            session.add(opportunity)
            is_new = True

    session.flush()  # need opportunity.id for the FKs below

    raw_row.opportunity_id = opportunity.id
    raw_row.processed = True

    _ensure_provenance(session, opportunity, source_id, raw, raw_row, is_primary=is_new)

    return opportunity, is_new
